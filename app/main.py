import io
import json
import os
import random
import re
import secrets
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, evidence, ingest
from .agreement import build_agreement
from .extract import extract_terms
from .parser import clean, parse_chat

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "data/uploads"))
MAX_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_BYTES = MAX_MB * 1024 * 1024
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"  # shows OTP on screen instead of sending an SMS
OPEN_STATES = ("collecting", "draft")  # evidence can be added or changed only before sending

app = FastAPI(title="Handshake to Contract")
db.init()
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ------------------------------------------------------------------ helpers

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def _hash_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()


def _open_deal(deal_id: str) -> dict:
    d = _deal(deal_id)
    if d["status"] not in OPEN_STATES:
        raise HTTPException(409, "This deal was already sent. Start a new case to change the evidence.")
    return d


# ---- evidence items

def _items(deal_id: str, include_removed: bool = False) -> list[dict]:
    q = "SELECT * FROM items WHERE deal_id=?" + ("" if include_removed else " AND removed=0") + " ORDER BY id"
    with db.conn() as c:
        rows = c.execute(q, (deal_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["removed"] = bool(d["removed"])
        out.append(d)
    return out


def _item(deal_id: str, item_id: int) -> dict:
    with db.conn() as c:
        r = c.execute("SELECT * FROM items WHERE id=? AND deal_id=?", (item_id, deal_id)).fetchone()
    if not r:
        raise HTTPException(404, "Evidence item not found")
    d = dict(r)
    d["removed"] = bool(d["removed"])
    return d


def _editable(it: dict) -> bool:
    return it["kind"] in ("voice", "image", "note", "file") or it["text_status"] == "needs_text"


def _pub_item(it: dict) -> dict:
    out = {k: it[k] for k in ("id", "kind", "name", "label", "mime", "size", "sha256", "text_status",
                              "occurred_at", "speaker", "added")}
    out["editable"] = _editable(it)
    text = it["text"] or ""
    if out["editable"]:
        out["text"] = text[:20000]
    else:
        out["preview"] = text[:500]
    if it["kind"] == "chat":
        out["message_count"] = len(parse_chat(text))
    return out


def _evidence_state(deal_id: str) -> dict:
    items = _items(deal_id)
    return {"items": [_pub_item(i) for i in items], "readiness": ingest.readiness(items)}


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", os.path.basename(name))[:80] or "file"


def _add_evidence(deal_id: str, name: str, data: bytes, hint: str | None = None, label: str = "",
                  occurred_at: str = "", speaker: str = "", allow_zip: bool = True) -> list[dict]:
    """Stores one file (or every file inside a WhatsApp zip), fingerprints it and logs it."""
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"“{name}” is bigger than {MAX_MB} MB")
    if not data:
        raise HTTPException(400, f"“{name}” is empty")

    created: list[dict] = []
    if allow_zip and name.lower().endswith(".zip") and zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = [i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX")
                     and not os.path.basename(i.filename).startswith(".")]
            if len(infos) > 60 or sum(i.file_size for i in infos) > 4 * MAX_BYTES:
                raise HTTPException(400, "That zip is too big. Add the files one by one.")
            for i in infos:
                inner = z.read(i)
                if inner and len(inner) <= MAX_BYTES:
                    created += _add_evidence(deal_id, os.path.basename(i.filename), inner, allow_zip=False)
        if not created:
            raise HTTPException(400, "Nothing usable inside that zip.")
        return created

    kind = ingest.detect_kind(name, hint, data)
    text, status = ingest.extract_text(kind, name, data)
    sha = evidence.sha(data)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO items (deal_id,kind,name,label,mime,size,sha256,path,text,text_status,occurred_at,speaker,added,removed)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (deal_id, kind, name, label.strip(), ingest.guess_mime(name), len(data), sha, "", text, status,
             occurred_at.strip(), speaker.strip(), _now()),
        )
        item_id = cur.lastrowid
    folder = UPLOAD_DIR / deal_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{item_id}_{_safe_name(name)}"
    path.write_bytes(data)
    with db.conn() as c:
        c.execute("UPDATE items SET path=? WHERE id=?", (str(path), item_id))
    evidence.append(deal_id, "evidence_added", data, {"item_id": item_id, "kind": kind, "name": name, "size": len(data)})
    created.append(_item(deal_id, item_id))
    return created


def _verification(deal_id: str) -> dict:
    """Chain check plus a re-hash of every stored file against what the chain recorded."""
    v = evidence.verify(deal_id)
    expected = {e["meta"].get("item_id"): e["content_hash"]
                for e in evidence.get_chain(deal_id) if e["kind"] == "evidence_added"}
    bad = []
    for it in _items(deal_id, include_removed=True):
        p = Path(it["path"]) if it["path"] else None
        ok = bool(p and p.is_file() and evidence.sha(p.read_bytes()) == it["sha256"] == expected.get(it["id"]))
        if not ok:
            bad.append(it["id"])
    v["bad_files"] = bad
    v["valid"] = v["valid"] and not bad
    return v


def _public(d: dict) -> dict:
    return {
        "id": d["id"], "title": d["title"], "status": d["status"], "messages": d["messages"],
        "terms": d["terms"], "agreement": d["agreement"], "tone": d["tone"], "token": d["token"],
        "chain": evidence.get_chain(d["id"]),
        "verification": _verification(d["id"]),
    }


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


# ------------------------------------------------------------------ evidence collection

def _new_case(title: str) -> str:
    deal_id = uuid.uuid4().hex[:8]
    with db.conn() as c:
        c.execute(
            "INSERT INTO deals (id,title,status,chat_text,tone,token,created) VALUES (?,?,?,?,?,?,?)",
            (deal_id, title.strip()[:80] or "Untitled deal", "collecting", "", "friendly",
             secrets.token_urlsafe(8), _now()),
        )
    return deal_id


class CaseIn(BaseModel):
    title: str = ""


@app.post("/api/cases")
def create_case(body: CaseIn):
    return _public(_deal(_new_case(body.title)))


@app.get("/api/cases/{deal_id}/items")
def list_items(deal_id: str):
    _deal(deal_id)
    return _evidence_state(deal_id)


@app.post("/api/cases/{deal_id}/items")
async def add_items(deal_id: str, kind: str = Form(""), name: str = Form(""), label: str = Form(""),
                    occurred_at: str = Form(""), speaker: str = Form(""), text: str = Form(""),
                    files: list[UploadFile] = File(default=[])):
    """Add files (any number), pasted chat text (kind=chat) or a typed note (kind=note)."""
    d = _open_deal(deal_id)
    added = 0
    for f in files:
        if f.filename:
            _add_evidence(deal_id, f.filename, await f.read(), label=label, occurred_at=occurred_at, speaker=speaker)
            added += 1
    if text.strip():
        if kind == "note":
            nm = _safe_name(label or "note") + ".txt"
            _add_evidence(deal_id, nm, text.encode(), hint="note", label=label, occurred_at=occurred_at, speaker=speaker)
        else:
            _add_evidence(deal_id, _safe_name(name or "pasted-chat.txt"), text.encode(), hint="chat")
        added += 1
    if not added:
        raise HTTPException(400, "Choose a file, paste a chat, or type a note first.")
    if d["status"] == "draft":
        _set(deal_id, status="collecting")  # evidence changed: terms must be read again
    return _evidence_state(deal_id)


class ItemEdit(BaseModel):
    label: str | None = None
    speaker: str | None = None
    occurred_at: str | None = None
    text: str | None = None


@app.put("/api/cases/{deal_id}/items/{item_id}")
def edit_item(deal_id: str, item_id: int, body: ItemEdit):
    d = _open_deal(deal_id)
    it = _item(deal_id, item_id)
    if it["removed"]:
        raise HTTPException(400, "This item was removed")
    changes = {}
    for k in ("label", "speaker", "occurred_at"):
        v = getattr(body, k)
        if v is not None and v.strip() != (it[k] or ""):
            changes[k] = v.strip()
    if body.text is not None and body.text != (it["text"] or ""):
        if not _editable(it):
            raise HTTPException(400, "The text of an original chat or document can't be edited. Add a note instead.")
        changes["text"] = body.text
        changes["text_status"] = "typed" if it["text_status"] in ("needs_text", "typed") or it["kind"] == "note" else "confirmed"
    elif body.text is not None and it["text_status"] == "machine" and _editable(it):
        changes["text_status"] = "confirmed"  # "looks right" without edits
    if not changes:
        return _evidence_state(deal_id)
    cols = ", ".join(f"{k}=?" for k in changes)
    with db.conn() as c:
        c.execute(f"UPDATE items SET {cols} WHERE id=?", (*changes.values(), item_id))
    new = _item(deal_id, item_id)
    snapshot = {k: new[k] for k in ("label", "speaker", "occurred_at", "text", "text_status")}
    evidence.append(deal_id, "evidence_edited", _hash_json(snapshot),
                    {"item_id": item_id, "name": new["name"], "changed": sorted(k for k in changes if k != "text_status")})
    if d["status"] == "draft":
        _set(deal_id, status="collecting")
    return _evidence_state(deal_id)


@app.delete("/api/cases/{deal_id}/items/{item_id}")
def remove_item(deal_id: str, item_id: int):
    d = _open_deal(deal_id)
    it = _item(deal_id, item_id)
    if not it["removed"]:
        with db.conn() as c:
            c.execute("UPDATE items SET removed=1 WHERE id=?", (item_id,))
        # The original stays stored and fingerprinted; only its use in the analysis stops.
        evidence.append(deal_id, "evidence_removed", it["sha256"].encode(),
                        {"item_id": item_id, "name": it["name"]})
        if d["status"] == "draft":
            _set(deal_id, status="collecting")
    return _evidence_state(deal_id)


INLINE_OK = ("audio/", "image/png", "image/jpeg", "image/webp", "image/gif")


@app.get("/api/cases/{deal_id}/items/{item_id}/file")
def item_file(deal_id: str, item_id: int):
    it = _item(deal_id, item_id)
    p = Path(it["path"])
    if not p.is_file():
        raise HTTPException(404, "The stored file is missing")
    inline = it["mime"].startswith(INLINE_OK)
    headers = {"X-Content-Type-Options": "nosniff"}
    if not inline:
        headers["Content-Disposition"] = f'attachment; filename="{_safe_name(it["name"])}"'
    return Response(p.read_bytes(), media_type=it["mime"] if inline else "application/octet-stream", headers=headers)


class AnalyzeIn(BaseModel):
    title: str = ""


@app.post("/api/cases/{deal_id}/analyze")
def analyze(deal_id: str, body: AnalyzeIn):
    d = _open_deal(deal_id)
    msgs = ingest.build_messages(_items(deal_id))
    if not msgs:
        raise HTTPException(400, "Nothing readable yet. Add a chat, or type what was said in your voice notes.")
    terms = extract_terms(msgs)
    fields = {"messages": json.dumps(msgs), "terms": json.dumps(terms), "status": "draft", "agreement": None}
    if body.title.strip():
        fields["title"] = body.title.strip()[:80]
    _set(deal_id, **fields)
    evidence.append(deal_id, "terms_extracted", _hash_json(terms),
                    {"engine": terms.get("engine"), "messages": len(msgs),
                     "sources": len({m["item_id"] for m in msgs})})
    return _public(_deal(deal_id))


# ------------------------------------------------------------------ owner API

@app.post("/api/deals")
async def create_deal(title: str = Form("Untitled deal"), chat_text: str = Form(""),
                      file: UploadFile | None = File(None)):
    """One-shot: chat in, terms out. Kept for scripts and tests; the UI uses /api/cases."""
    if file is not None and file.filename:
        raw, fname = await file.read(), file.filename
    else:
        raw, fname = clean(chat_text).strip().encode(), "pasted-chat.txt"
    if len(parse_chat(raw.decode("utf-8", errors="ignore"))) < 2:
        raise HTTPException(400, "Could not read any messages. Use WhatsApp > Export chat > Without media.")
    deal_id = _new_case(title)
    _add_evidence(deal_id, fname, raw, hint="chat")
    return analyze(deal_id, AnalyzeIn())


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
    if not d["terms"]:
        raise HTTPException(400, "Read the evidence first")
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
    if not d["terms"]:
        raise HTTPException(400, "Read the evidence first")
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
        "notice": "Evidence bundle. Verify by recomputing each entry_hash from its fields and prev_hash, and each "
                  "file's sha256 from the original file. Not legal advice; check stamp duty and validity for your state.",
        "generated_at": _now(),
        "deal": {"id": d["id"], "title": d["title"], "status": d["status"]},
        "evidence_items": [_pub_item(i) | {"removed": i["removed"]} for i in _items(deal_id, include_removed=True)],
        "messages": d["messages"], "terms": d["terms"], "agreement": d["agreement"],
        "verification": _verification(deal_id),
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
    """Is this exact file in any evidence trail? Tries the raw bytes, then a whitespace-normalised text form."""
    raw = await file.read()
    hashes = [evidence.sha(raw), evidence.sha(clean(raw.decode("utf-8", errors="ignore")).strip().encode())]
    matches = []
    for h in dict.fromkeys(hashes):
        matches += [m for m in evidence.find_by_content_hash(h) if m["kind"] == "evidence_added"]
    return {"sha256": hashes[0], "matches": matches, "ok": bool(matches)}


# ------------------------------------------------------------------ counterparty API

@app.get("/api/c/{token}")
def party_view(token: str):
    d = _by_token(token)
    if not d["agreement"] or d["status"] in ("draft", "collecting"):
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
