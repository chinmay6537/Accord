import json
import os
import random
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, evidence
from .agreement import build_agreement
from .extract import extract_terms
from .parser import clean, parse_chat

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"  # shows OTP on screen instead of sending an SMS

app = FastAPI(title="Handshake to Contract")
db.init()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ------------------------------------------------------------------ helpers

def _deal(deal_id: str) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Deal not found")
    d = dict(r)
    for k in ("messages", "terms"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def _by_token(token: str) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT id FROM deals WHERE token=?", (token,)).fetchone()
    if not r:
        raise HTTPException(404, "This confirmation link is not valid")
    return _deal(r["id"])


def _set(deal_id: str, **fields):
    cols = ", ".join(f"{k}=?" for k in fields)
    with db.conn() as c:
        c.execute(f"UPDATE deals SET {cols} WHERE id=?", (*fields.values(), deal_id))


def _public(d: dict) -> dict:
    return {
        "id": d["id"], "title": d["title"], "status": d["status"], "messages": d["messages"],
        "terms": d["terms"], "agreement": d["agreement"], "tone": d["tone"], "token": d["token"],
        "chain": evidence.get_chain(d["id"]),
        "verification": evidence.verify(d["id"], d["chat_text"]),
    }


def _hash_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()


# ------------------------------------------------------------------ pages

@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/sample")
def sample():
    return Response((ROOT / "samples" / "wedding_cards_hinglish.txt").read_text(encoding="utf-8"),
                    media_type="text/plain; charset=utf-8")


@app.get("/c/{token}")
def confirm_page(token: str):
    return FileResponse(STATIC / "confirm.html")


# ------------------------------------------------------------------ owner API

@app.post("/api/deals")
async def create_deal(title: str = Form("Untitled deal"), chat_text: str = Form(""),
                      file: UploadFile | None = File(None)):
    if file is not None and file.filename:
        chat_text = (await file.read()).decode("utf-8", errors="ignore")
    chat_text = clean(chat_text).strip()
    msgs = parse_chat(chat_text)
    if len(msgs) < 2:
        raise HTTPException(400, "Could not read any messages. Use WhatsApp > Export chat > Without media.")

    deal_id = uuid.uuid4().hex[:8]
    terms = extract_terms(msgs)
    with db.conn() as c:
        c.execute(
            "INSERT INTO deals (id,title,status,chat_text,messages,terms,tone,token,created) VALUES (?,?,?,?,?,?,?,?,?)",
            (deal_id, title.strip() or "Untitled deal", "draft", chat_text, json.dumps(msgs),
             json.dumps(terms), "friendly", secrets.token_urlsafe(8),
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
    evidence.append(deal_id, "chat_export", chat_text.encode(), {"messages": len(msgs)})
    evidence.append(deal_id, "terms_extracted", _hash_json(terms), {"engine": terms.get("engine")})
    return _public(_deal(deal_id))


@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str):
    return _public(_deal(deal_id))


class TermEdits(BaseModel):
    scope: str = ""
    price: str = ""
    delivery: str = ""
    payment_terms: str = ""


@app.put("/api/deals/{deal_id}/terms")
def save_terms(deal_id: str, edits: TermEdits):
    d = _deal(deal_id)
    terms = d["terms"]
    for k, v in edits.model_dump().items():
        terms[k]["value"] = v.strip()
    _set(deal_id, terms=json.dumps(terms))
    evidence.append(deal_id, "terms_confirmed", _hash_json(terms), {"by": "owner"})
    return _public(_deal(deal_id))


class ToneIn(BaseModel):
    tone: str = "friendly"


@app.post("/api/deals/{deal_id}/agreement")
def make_agreement(deal_id: str, body: ToneIn):
    d = _deal(deal_id)
    tone = body.tone if body.tone in ("friendly", "formal") else "friendly"
    text = build_agreement(d["title"], d["terms"], tone)
    _set(deal_id, agreement=text, tone=tone)
    evidence.append(deal_id, "agreement_generated", text.encode(), {"tone": tone})
    return _public(_deal(deal_id))


@app.post("/api/deals/{deal_id}/send")
def send_for_confirmation(deal_id: str, request: Request):
    d = _deal(deal_id)
    if not d["agreement"]:
        raise HTTPException(400, "Generate the agreement first")
    _set(deal_id, status="sent")
    evidence.append(deal_id, "owner_approved", d["agreement"].encode(), {"by": "owner"})
    out = _public(_deal(deal_id))
    out["confirm_url"] = f"{str(request.base_url).rstrip('/')}/c/{d['token']}"
    return out


@app.get("/api/deals/{deal_id}/bundle")
def bundle(deal_id: str):
    d = _deal(deal_id)
    data = {
        "notice": "Evidence bundle. Verify by recomputing each entry_hash from its fields and prev_hash. "
                  "Not legal advice; check stamp duty and legal validity for your state.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deal": {"id": d["id"], "title": d["title"], "status": d["status"]},
        "messages": d["messages"], "terms": d["terms"], "agreement": d["agreement"],
        "verification": evidence.verify(deal_id, d["chat_text"]),
        "evidence_chain": evidence.get_chain(deal_id),
    }
    return Response(json.dumps(data, indent=2, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="evidence-{deal_id}.json"'})


@app.post("/api/deals/{deal_id}/demo-tamper")
def demo_tamper(deal_id: str):
    """Demo only: silently edits one past log entry so the verifier can catch it."""
    if not DEMO_MODE:
        raise HTTPException(403, "Disabled")
    chain = evidence.get_chain(deal_id)
    if len(chain) < 2:
        raise HTTPException(400, "Nothing to tamper with yet")
    with db.conn() as c:
        c.execute("UPDATE evidence SET meta=? WHERE deal_id=? AND seq=2",
                  (json.dumps({"engine": "edited-after-the-fact"}), deal_id))
    return _public(_deal(deal_id))


@app.post("/api/verify-file")
async def verify_file(file: UploadFile = File(...)):
    raw = await file.read()
    text = clean(raw.decode("utf-8", errors="ignore")).strip().encode()
    h = evidence.sha(text)
    matches = evidence.find_by_content_hash(h)
    return {"sha256": h, "matches": matches, "ok": bool(matches)}


# ------------------------------------------------------------------ counterparty API

@app.get("/api/c/{token}")
def party_view(token: str):
    d = _by_token(token)
    if not d["agreement"] or d["status"] == "draft":
        raise HTTPException(404, "This agreement is not ready yet")
    return {"title": d["title"], "agreement": d["agreement"], "status": d["status"],
            "parties": [p["name"] for p in d["terms"]["parties"]]}


class OtpIn(BaseModel):
    phone: str


@app.post("/api/c/{token}/otp")
def party_otp(token: str, body: OtpIn):
    d = _by_token(token)
    otp = f"{random.randint(0, 999999):06d}"
    _set(d["id"], otp=otp)
    # Production: send via an SMS/WhatsApp provider here (Twilio, MSG91, ...).
    return {"sent": True, "demo_otp": otp if DEMO_MODE else None}


class RespondIn(BaseModel):
    name: str
    otp: str
    action: str  # "agree" | "change"
    note: str = ""


@app.post("/api/c/{token}/respond")
def party_respond(token: str, body: RespondIn, request: Request):
    d = _by_token(token)
    if not d["otp"] or body.otp.strip() != d["otp"]:
        raise HTTPException(400, "That code is not right. Ask for a new one.")
    if body.action not in ("agree", "change") or not body.name.strip():
        raise HTTPException(400, "Enter your name and choose an option")
    kind = "counterparty_confirmed" if body.action == "agree" else "counterparty_requested_change"
    entry = evidence.append(
        d["id"], kind, d["agreement"].encode(),
        {"name": body.name.strip(), "note": body.note.strip()[:500], "otp_verified": True,
         "ip": request.client.host if request.client else "", "ua": request.headers.get("user-agent", "")[:120]},
    )
    _set(d["id"], status="confirmed" if body.action == "agree" else "change_requested", otp="")
    return {"ok": True, "status": "confirmed" if body.action == "agree" else "change_requested",
            "receipt": entry["entry_hash"]}
