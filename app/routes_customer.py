"""What a logged-in customer sees and can do.

A customer never creates tickets. They receive them from a dealer, check every term against the references
behind it, message the dealer if something looks off, and only then approve (or ask for a change)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db, evidence, proof
from .auth import need_customer
from .common import get_deal, now, set_deal

router = APIRouter(prefix="/api/my", tags=["customer"])

FIELDS = [("scope", "What was agreed"), ("price", "Price"), ("delivery", "Delivery"), ("payment_terms", "Payment")]
LABEL = dict(FIELDS)

SQL = (
    "SELECT d.id, d.title, d.status, d.description, d.due_date, d.sent_at, d.created, "
    "u.name AS dealer_name, u.business_name AS dealer_business, u.email AS dealer_email, u.phone AS dealer_phone, "
    "c.name AS my_name, "
    "COALESCE((SELECT MAX(e.ts) FROM evidence e WHERE e.deal_id=d.id), d.created) AS updated "
    "FROM deals d JOIN customers c ON c.id=d.customer_id JOIN users u ON u.id=d.dealer_id "
    "WHERE c.user_id=? AND d.status IN ('sent','confirmed','change_requested')"
)

TRAIL_KINDS = ("evidence_added", "terms_extracted", "terms_confirmed", "agreement_generated", "owner_approved",
               "comment_added", "counterparty_confirmed", "counterparty_requested_change")


def _mine(deal_id: str, user: dict) -> dict:
    with db.conn() as c:
        r = c.execute(SQL + " AND d.id=?", (user["id"], deal_id)).fetchone()
    if not r:
        raise HTTPException(404, "Request not found")
    return dict(r)


def _checks(deal_id: str, user_id: str) -> dict:
    with db.conn() as c:
        rows = c.execute("SELECT field, result, note FROM checks WHERE deal_id=? AND user_id=?", (deal_id, user_id)).fetchall()
    return {r["field"]: {"result": r["result"], "note": r["note"]} for r in rows}


@router.get("/tickets")
def my_tickets(user: dict = Depends(need_customer)):
    with db.conn() as c:
        rows = c.execute(SQL + " ORDER BY updated DESC", (user["id"],)).fetchall()
    out = []
    for r in rows:
        t = dict(r)
        t.pop("dealer_email"), t.pop("dealer_phone")
        t["checked"] = sum(1 for v in _checks(t["id"], user["id"]).values() if v["result"] == "match")
        out.append(t)
    return out


@router.get("/dealers")
def my_dealers(user: dict = Depends(need_customer)):
    """Dealers who have sent this customer something, with contact details and counts."""
    with db.conn() as c:
        rows = c.execute(SQL, (user["id"],)).fetchall()
    out = {}
    for r in rows:
        d = out.setdefault(r["dealer_name"], {"name": r["dealer_name"], "business": r["dealer_business"], "email": r["dealer_email"],
                                              "phone": r["dealer_phone"], "total": 0, "waiting": 0})
        d["total"] += 1
        d["waiting"] += r["status"] == "sent"
    return sorted(out.values(), key=lambda d: -d["waiting"])


@router.get("/tickets/{deal_id}")
def review(deal_id: str, user: dict = Depends(need_customer)):
    """Everything the customer needs to verify the dealer's version: each term with the messages behind it,
    how it changed, what is still open, the evidence on file and whether its trail is intact."""
    t = _mine(deal_id, user)
    d = get_deal(deal_id)
    msgs = {m["id"]: m for m in (d["messages"] or [])}
    terms = d["terms"] or {}

    def refs(ids):
        return [{"id": m["id"], "sender": m["sender"], "date": m["date"], "time": m["time"], "text": m["text"],
                 "kind": m.get("kind", "chat"), "source": m.get("item_name", "")}
                for i in ids if (m := msgs.get(i))]

    rows = []
    for key, label in FIELDS:
        term = terms.get(key) or {}
        row = {"key": key, "label": label, "value": (term.get("value") or "").strip(),
               "refs": refs(term.get("source_ids", [])), "edited": bool(term.get("edited")),
               "extracted_value": term.get("extracted_value"),
               "history": [{"old": s["old"], "new": s["new"], "refs": refs(s.get("source_ids", []))}
                           for s in terms.get("superseded", []) if s["field"] == key]}
        if key == "price":
            row["gst"] = (term.get("gst") or "not_mentioned")
        rows.append(row)

    open_points = [{"field": m["field"], "why": m["why"]} for m in terms.get("missing", [])] + \
                  [{"field": a["field"].replace("_", " ").title(), "why": a["issue"]} for a in terms.get("ambiguities", [])]

    v = proof.verification(deal_id)
    chain = evidence.get_chain(deal_id)
    return {
        **{k: t[k] for k in ("id", "title", "status", "description", "due_date", "sent_at", "dealer_name",
                             "dealer_business", "dealer_email", "dealer_phone", "my_name")},
        "agreement": d["agreement"],
        "parties": [p["name"] for p in terms.get("parties", [])],
        "terms": rows,
        "open_points": open_points,
        "evidence": [{"id": i["id"], "kind": i["kind"], "name": i["name"], "label": i["label"], "added": i["added"],
                      "size": i["size"], "sha256": i["sha256"], "machine_text": i["text_status"] == "machine"}
                     for i in proof.items(deal_id)],
        "proof": {"valid": v["valid"], "entries": v["length"], "head": v["head"], "broken_at": v["broken_at"],
                  "bad_files": len(v["bad_files"])},
        "trail": [{"seq": e["seq"], "kind": e["kind"], "ts": e["ts"], "hash": e["entry_hash"],
                   "name": e["meta"].get("name", ""), "note": e["meta"].get("note", "")}
                  for e in chain if e["kind"] in TRAIL_KINDS],
        "checks": _checks(deal_id, user["id"]),
    }


class CheckIn(BaseModel):
    result: str          # "match" | "mismatch" | "clear"
    note: str = ""


@router.put("/tickets/{deal_id}/checks/{field}")
def set_check(deal_id: str, field: str, body: CheckIn, user: dict = Depends(need_customer)):
    t = _mine(deal_id, user)
    if t["status"] != "sent":
        raise HTTPException(409, "This request is no longer waiting for your answer")
    if field not in LABEL:
        raise HTTPException(404, "Unknown term")
    if body.result not in ("match", "mismatch", "clear"):
        raise HTTPException(400, "Choose match or does not match")
    with db.conn() as c:
        if body.result == "clear":
            c.execute("DELETE FROM checks WHERE deal_id=? AND user_id=? AND field=?", (deal_id, user["id"], field))
        else:
            c.execute("INSERT INTO checks (deal_id,user_id,field,result,note,updated) VALUES (?,?,?,?,?,?) "
                      "ON CONFLICT(deal_id,user_id,field) DO UPDATE SET result=excluded.result, note=excluded.note, updated=excluded.updated",
                      (deal_id, user["id"], field, body.result, body.note.strip()[:300], now()))
    return {"checks": _checks(deal_id, user["id"])}


class RespondIn(BaseModel):
    action: str  # "agree" | "change"
    note: str = ""


@router.post("/tickets/{deal_id}/respond")
def respond(deal_id: str, body: RespondIn, user: dict = Depends(need_customer)):
    t = _mine(deal_id, user)
    if t["status"] != "sent":
        raise HTTPException(409, "This request is not waiting for your answer")
    if body.action not in ("agree", "change"):
        raise HTTPException(400, "Choose approve or ask for a change")
    d = get_deal(deal_id)
    checks = _checks(deal_id, user["id"])
    terms = d["terms"] or {}
    needed = [k for k, _ in FIELDS if (terms.get(k, {}).get("value") or "").strip()]   # blank terms were never agreed

    note = body.note.strip()
    if body.action == "agree":
        todo = [LABEL[k] for k in needed if checks.get(k, {}).get("result") != "match"]
        if todo:
            raise HTTPException(400, "Check each term against your records first: " + ", ".join(todo))
    else:
        for k, c in checks.items():
            if c["result"] == "mismatch" and c["note"]:
                note += ("; " if note else "") + f"{LABEL[k]}: {c['note']}"
        if not note:
            raise HTTPException(400, "Tell the dealer what to change")

    kind = "counterparty_confirmed" if body.action == "agree" else "counterparty_requested_change"
    entry = evidence.append(deal_id, kind, d["agreement"].encode(),
                            {"name": user["name"], "user_id": user["id"], "via": "account", "note": note[:500],
                             "checks": {k: c["result"] for k, c in checks.items()}})
    status = "confirmed" if body.action == "agree" else "change_requested"
    set_deal(deal_id, status=status)
    return {"ok": True, "status": status, "receipt": entry["entry_hash"]}
