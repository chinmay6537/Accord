"""Public demo for the landing page. No login, nothing is saved, and it never calls a paid API:
it always uses the offline rules engine, so strangers cannot spend your Claude credits."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .agreement import build_agreement
from .extract import extract_rules
from .parser import parse_chat

router = APIRouter(prefix="/api/demo", tags=["demo"])

MAX_CHARS = 8000        # about 150 chat lines
PER_MINUTE = 8
_hits: dict[str, deque] = defaultdict(deque)


class DemoIn(BaseModel):
    text: str


@router.post("")
def demo(body: DemoIn, request: Request):
    ip = request.client.host if request.client else "?"
    q, t = _hits[ip], time.time()
    while q and t - q[0] > 60:
        q.popleft()
    if len(q) >= PER_MINUTE:
        raise HTTPException(429, "Slow down a little. Sign up to use Accord without limits.")
    q.append(t)

    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Paste a chat first")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"The demo takes up to {MAX_CHARS:,} characters. Sign up to use full chats.")
    msgs = parse_chat(text)
    if len(msgs) < 2:
        raise HTTPException(400, "Could not find chat messages. Paste a WhatsApp export (lines like '12/10/2026, 10:16 am - Name: message').")

    terms = extract_rules(msgs)
    cite = {m["id"]: {"sender": m["sender"], "date": m["date"], "text": m["text"]} for m in msgs}
    fields = [("scope", "What was agreed"), ("price", "Price"), ("delivery", "Delivery"), ("payment_terms", "Payment")]
    return {
        "messages": len(msgs),
        "summary": terms.get("summary", ""),
        "parties": [p["name"] for p in terms["parties"]],
        "terms": [{"label": lab, "value": terms[k].get("value", ""),
                   "refs": [cite[i] for i in terms[k].get("source_ids", []) if i in cite][:2],
                   "changes": sum(1 for s in terms.get("superseded", []) if s["field"] == k)} for k, lab in fields],
        "missing": [{"field": m["field"], "nudge": m["nudge"]} for m in terms.get("missing", [])],
        "agreement": build_agreement("Your deal", terms, "friendly"),
    }
