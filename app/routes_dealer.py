"""Everything the dealer dashboard needs: overview, tickets, customers, segments.
A "ticket" is a deal: one agreement the dealer is trying to get on record with one customer."""
import secrets
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db, evidence
from .auth import need_dealer
from .common import dealer_deal, norm_phone, now, set_deal

router = APIRouter(prefix="/api", tags=["dealer"])

DEAL_TYPES = ("supply", "service", "repair", "rental", "other")
GST = ("", "included", "extra", "not_sure")
PRIORITY = ("normal", "urgent")
CHANNEL = ("", "whatsapp", "call", "in_person", "mixed")
STATUSES = ("collecting", "draft", "sent", "confirmed", "change_requested")


# ------------------------------------------------------------------ segments

class SegmentIn(BaseModel):
    name: str


def _segment(seg_id: int, user: dict) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM segments WHERE id=? AND dealer_id=?", (seg_id, user["id"])).fetchone()
    if not r:
        raise HTTPException(404, "Segment not found")
    return dict(r)


@router.get("/segments")
def list_segments(user: dict = Depends(need_dealer)):
    with db.conn() as c:
        rows = c.execute(
            "SELECT s.id, s.name, (SELECT COUNT(*) FROM customers c WHERE c.segment_id=s.id) AS customers "
            "FROM segments s WHERE s.dealer_id=? ORDER BY s.name", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@router.post("/segments")
def add_segment(body: SegmentIn, user: dict = Depends(need_dealer)):
    name = body.name.strip()[:40]
    if not name:
        raise HTTPException(400, "Give the segment a name")
    try:
        with db.conn() as c:
            c.execute("INSERT INTO segments (dealer_id,name,created) VALUES (?,?,?)", (user["id"], name, now()))
    except Exception:
        raise HTTPException(409, "You already have a segment with that name")
    return list_segments(user)


@router.put("/segments/{seg_id}")
def rename_segment(seg_id: int, body: SegmentIn, user: dict = Depends(need_dealer)):
    _segment(seg_id, user)
    name = body.name.strip()[:40]
    if not name:
        raise HTTPException(400, "Give the segment a name")
    try:
        with db.conn() as c:
            c.execute("UPDATE segments SET name=? WHERE id=?", (name, seg_id))
    except Exception:
        raise HTTPException(409, "You already have a segment with that name")
    return list_segments(user)


@router.delete("/segments/{seg_id}")
def delete_segment(seg_id: int, user: dict = Depends(need_dealer)):
    _segment(seg_id, user)
    with db.conn() as c:
        c.execute("UPDATE customers SET segment_id=NULL WHERE segment_id=?", (seg_id,))  # customers stay
        c.execute("DELETE FROM segments WHERE id=?", (seg_id,))
    return list_segments(user)


# ------------------------------------------------------------------ customers

class CustomerIn(BaseModel):
    name: str
    phone: str = ""
    email: str = ""
    business: str = ""
    segment_id: int | None = None
    notes: str = ""


def _customer(cid: int, user: dict) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM customers WHERE id=? AND dealer_id=?", (cid, user["id"])).fetchone()
    if not r:
        raise HTTPException(404, "Customer not found")
    return dict(r)


def _clean_customer(body: CustomerIn, user: dict) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Enter the customer's name")
    if body.segment_id is not None:
        _segment(body.segment_id, user)
    return {"name": body.name.strip()[:80], "phone": norm_phone(body.phone), "email": body.email.strip().lower()[:120],
            "business": body.business.strip()[:80], "segment_id": body.segment_id, "notes": body.notes.strip()[:1000]}


CUSTOMER_SQL = (
    "SELECT c.*, s.name AS segment_name, (c.user_id IS NOT NULL) AS has_account, "
    "(SELECT COUNT(*) FROM deals d WHERE d.customer_id=c.id) AS tickets, "
    "(SELECT MAX(d.created) FROM deals d WHERE d.customer_id=c.id) AS last_ticket "
    "FROM customers c LEFT JOIN segments s ON s.id=c.segment_id WHERE c.dealer_id=?"
)


@router.get("/customers")
def list_customers(q: str = "", segment_id: int | None = None, user: dict = Depends(need_dealer)):
    sql, args = CUSTOMER_SQL, [user["id"]]
    if q.strip():
        sql += " AND (c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ? OR c.business LIKE ?)"
        args += [f"%{q.strip()}%"] * 4
    if segment_id is not None:
        sql += " AND c.segment_id=?"
        args.append(segment_id)
    with db.conn() as c:
        rows = c.execute(sql + " ORDER BY c.name", args).fetchall()
    return [{k: v for k, v in dict(r).items() if k != "invite_token"} | {"has_account": bool(r["has_account"])} for r in rows]


@router.post("/customers")
def add_customer(body: CustomerIn, user: dict = Depends(need_dealer)):
    f = _clean_customer(body, user)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO customers (dealer_id,name,phone,email,business,segment_id,notes,invite_token,created) VALUES (?,?,?,?,?,?,?,?,?)",
            (user["id"], f["name"], f["phone"], f["email"], f["business"], f["segment_id"], f["notes"],
             secrets.token_urlsafe(12), now()))
        cid = cur.lastrowid
    return get_customer(cid, user)


@router.get("/customers/{cid}")
def get_customer(cid: int, user: dict = Depends(need_dealer)):
    _customer(cid, user)
    with db.conn() as c:
        row = c.execute(CUSTOMER_SQL + " AND c.id=?", (user["id"], cid)).fetchone()
    out = dict(row) | {"has_account": bool(row["has_account"])}
    out["invite_path"] = f"/join/{row['invite_token']}"
    out["ticket_list"] = list_tickets(customer_id=cid, user=user)
    return out


@router.put("/customers/{cid}")
def edit_customer(cid: int, body: CustomerIn, user: dict = Depends(need_dealer)):
    _customer(cid, user)
    f = _clean_customer(body, user)
    with db.conn() as c:
        c.execute("UPDATE customers SET name=?,phone=?,email=?,business=?,segment_id=?,notes=? WHERE id=?",
                  (f["name"], f["phone"], f["email"], f["business"], f["segment_id"], f["notes"], cid))
    return get_customer(cid, user)


@router.delete("/customers/{cid}")
def delete_customer(cid: int, user: dict = Depends(need_dealer)):
    _customer(cid, user)
    with db.conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM deals WHERE customer_id=?", (cid,)).fetchone()["n"]
        if n:
            raise HTTPException(409, "This customer has tickets, so they can't be deleted. Their history stays.")
        c.execute("DELETE FROM customers WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ tickets

class TicketIn(BaseModel):
    title: str
    customer_id: int
    description: str
    deal_type: str = "supply"
    est_value: float | None = None
    advance: float | None = None
    due_date: str = ""
    gst: str = ""
    priority: str = "normal"
    channel: str = ""
    notes: str = ""


def _clean_ticket(body: TicketIn, user: dict) -> dict:
    title, desc = body.title.strip()[:80], body.description.strip()[:2000]
    if not title:
        raise HTTPException(400, "Give the ticket a title")
    if not desc:
        raise HTTPException(400, "Describe the deal in a few words")
    _customer(body.customer_id, user)
    if body.deal_type not in DEAL_TYPES:
        raise HTTPException(400, "Unknown deal type")
    if body.gst not in GST or body.priority not in PRIORITY or body.channel not in CHANNEL:
        raise HTTPException(400, "One of the options is not valid")
    for v in (body.est_value, body.advance):
        if v is not None and v < 0:
            raise HTTPException(400, "Amounts can't be negative")
    if body.est_value is not None and body.advance is not None and body.advance > body.est_value:
        raise HTTPException(400, "The advance is more than the deal value")
    if body.due_date:
        try:
            date.fromisoformat(body.due_date)
        except ValueError:
            raise HTTPException(400, "Use a real date for delivery")
    return {"title": title, "customer_id": body.customer_id, "description": desc, "deal_type": body.deal_type,
            "est_value": body.est_value, "advance": body.advance, "due_date": body.due_date, "gst": body.gst,
            "priority": body.priority, "channel": body.channel, "notes": body.notes.strip()[:2000]}


def new_ticket(user: dict, f: dict) -> str:
    deal_id = uuid.uuid4().hex[:8]
    with db.conn() as c:
        c.execute(
            "INSERT INTO deals (id,title,status,chat_text,tone,token,created,dealer_id,customer_id,description,"
            "deal_type,est_value,advance,due_date,gst,priority,channel,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (deal_id, f["title"], "collecting", "", "friendly", secrets.token_urlsafe(8), now(), user["id"],
             f["customer_id"], f["description"], f["deal_type"], f["est_value"], f["advance"], f["due_date"],
             f["gst"], f["priority"], f["channel"], f["notes"]))
    return deal_id


TICKET_SQL = (
    "SELECT d.id, d.title, d.status, d.deal_type, d.est_value, d.due_date, d.priority, d.created, d.customer_id, "
    "c.name AS customer_name, s.name AS segment_name, "
    "COALESCE((SELECT MAX(e.ts) FROM evidence e WHERE e.deal_id=d.id), d.created) AS updated "
    "FROM deals d LEFT JOIN customers c ON c.id=d.customer_id LEFT JOIN segments s ON s.id=c.segment_id "
    "WHERE d.dealer_id=?"
)


@router.post("/tickets")
def create_ticket(body: TicketIn, user: dict = Depends(need_dealer)):
    return get_ticket(new_ticket(user, _clean_ticket(body, user)), user)


@router.get("/tickets")
def list_tickets(status: str = "", customer_id: int | None = None, segment_id: int | None = None, q: str = "",
                 user: dict = Depends(need_dealer)):
    sql, args = TICKET_SQL, [user["id"]]
    if status:
        if status not in STATUSES:
            raise HTTPException(400, "Unknown status")
        sql += " AND d.status=?"
        args.append(status)
    if customer_id is not None:
        sql += " AND d.customer_id=?"
        args.append(customer_id)
    if segment_id is not None:
        sql += " AND c.segment_id=?"
        args.append(segment_id)
    if q.strip():
        sql += " AND (d.title LIKE ? OR c.name LIKE ? OR d.description LIKE ?)"
        args += [f"%{q.strip()}%"] * 3
    with db.conn() as c:
        rows = c.execute(sql + " ORDER BY updated DESC", args).fetchall()
    return [dict(r) for r in rows]


@router.get("/tickets/{deal_id}")
def get_ticket(deal_id: str, user: dict = Depends(need_dealer)):
    d = dealer_deal(deal_id, user)
    with db.conn() as c:
        cu = c.execute("SELECT c.id, c.name, c.phone, c.email, c.business, (c.user_id IS NOT NULL) AS has_account, "
                       "s.name AS segment_name FROM customers c LEFT JOIN segments s ON s.id=c.segment_id "
                       "WHERE c.id=?", (d["customer_id"],)).fetchone()
    keys = ("id", "title", "status", "description", "deal_type", "est_value", "advance", "due_date", "gst",
            "priority", "channel", "notes", "created", "sent_at", "token")
    out = {k: d[k] for k in keys}
    out["customer"] = (dict(cu) | {"has_account": bool(cu["has_account"])}) if cu else None
    out["history"] = [{"seq": e["seq"], "kind": e["kind"], "ts": e["ts"], "meta": e["meta"]}
                      for e in evidence.get_chain(deal_id)]
    return out


@router.put("/tickets/{deal_id}")
def edit_ticket(deal_id: str, body: TicketIn, user: dict = Depends(need_dealer)):
    d = dealer_deal(deal_id, user)
    if d["status"] not in ("collecting", "draft"):
        raise HTTPException(409, "This ticket was already sent, so its details are locked.")
    f = _clean_ticket(body, user)
    set_deal(deal_id, **f)
    return get_ticket(deal_id, user)


# ------------------------------------------------------------------ overview

@router.get("/dealer/overview")
def overview(user: dict = Depends(need_dealer)):
    with db.conn() as c:
        counts = {r["status"]: r["n"] for r in c.execute(
            "SELECT status, COUNT(*) AS n FROM deals WHERE dealer_id=? GROUP BY status", (user["id"],))}
        n_customers = c.execute("SELECT COUNT(*) AS n FROM customers WHERE dealer_id=?", (user["id"],)).fetchone()["n"]
        confirmed_value = c.execute(
            "SELECT COALESCE(SUM(est_value),0) AS v FROM deals WHERE dealer_id=? AND status='confirmed'",
            (user["id"],)).fetchone()["v"]
    tickets = list_tickets(user=user)
    return {
        "counts": {s: counts.get(s, 0) for s in STATUSES},
        "total": sum(counts.values()), "customers": n_customers, "confirmed_value": confirmed_value,
        "needs_attention": [t for t in tickets if t["status"] in ("change_requested", "sent")][:8],
        "recent": tickets[:8],
    }
