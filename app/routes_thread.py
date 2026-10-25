"""Chat and comments between the dealer and the customer on one ticket.

kind="chat"    ordinary message
kind="comment" a comment on the final agreement. These are also written to the tamper-evident trail.
Available once the ticket has been sent. The browser polls GET ?after=<last id> every few seconds."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db, evidence
from .auth import need_user
from .common import SHARED_STATES, get_deal, now

router = APIRouter(prefix="/api/tickets", tags=["thread"])


def _access(deal_id: str, user: dict) -> dict:
    d = get_deal(deal_id)
    if user["role"] == "dealer":
        ok = d["dealer_id"] == user["id"]
    else:
        with db.conn() as c:
            ok = bool(c.execute("SELECT 1 FROM customers WHERE id=? AND user_id=?",
                                (d["customer_id"], user["id"])).fetchone())
    if not ok or d["status"] not in SHARED_STATES:
        raise HTTPException(404, "Conversation not found")
    return d


@router.get("/{deal_id}/thread")
def read_thread(deal_id: str, after: int = 0, user: dict = Depends(need_user)):
    _access(deal_id, user)
    with db.conn() as c:
        rows = c.execute("SELECT id, sender_id, sender_name, sender_role, kind, body, created FROM messages "
                         "WHERE deal_id=? AND id>? ORDER BY id", (deal_id, after)).fetchall()
    return [dict(r) | {"mine": r["sender_id"] == user["id"]} for r in rows]


class MessageIn(BaseModel):
    body: str
    kind: str = "chat"


@router.post("/{deal_id}/thread")
def post_message(deal_id: str, body: MessageIn, user: dict = Depends(need_user)):
    d = _access(deal_id, user)
    text = body.body.strip()
    if not text:
        raise HTTPException(400, "Write something first")
    if len(text) > 2000:
        raise HTTPException(400, "That message is too long (2000 characters max)")
    if body.kind not in ("chat", "comment"):
        raise HTTPException(400, "Unknown message type")
    if body.kind == "comment" and not d["agreement"]:
        raise HTTPException(400, "There is no agreement to comment on yet")
    with db.conn() as c:
        cur = c.execute("INSERT INTO messages (deal_id,sender_id,sender_name,sender_role,kind,body,created) VALUES (?,?,?,?,?,?,?)",
                        (deal_id, user["id"], user["name"], user["role"], body.kind, text, now()))
        mid = cur.lastrowid
    if body.kind == "comment":
        evidence.append(deal_id, "comment_added", text.encode(),
                        {"name": user["name"], "role": user["role"], "message_id": mid, "note": text[:200]})
    return {"id": mid}
