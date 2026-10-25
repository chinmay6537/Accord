"""Small helpers shared by every route file."""
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from . import db

SHARED_STATES = ("sent", "confirmed", "change_requested")  # states a customer is allowed to see


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def norm_phone(p: str) -> str:
    """Last 10 digits, so +91 98765 43210 and 09876543210 match."""
    return re.sub(r"\D", "", p or "")[-10:]


def get_deal(deal_id: str) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Deal not found")
    d = dict(r)
    for k in ("messages", "terms"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def set_deal(deal_id: str, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.conn() as c:
        c.execute(f"UPDATE deals SET {cols} WHERE id=?", (*fields.values(), deal_id))


def dealer_deal(deal_id: str, user: dict) -> dict:
    """A deal, only if it belongs to this dealer. Anyone else gets a plain 404."""
    d = get_deal(deal_id)
    if d["dealer_id"] != user["id"]:
        raise HTTPException(404, "Deal not found")
    return d
