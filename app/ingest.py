"""Turns uploaded evidence (chats, voice notes, screenshots, documents, typed notes) into text,
and merges everything into one timeline for term extraction.

Text status of every item:
  ready      text was read straight from the file (chat export, PDF, Word, plain text)
  typed      the user typed it (call notes, or a transcript they wrote themselves)
  machine    produced by speech-to-text or OCR; the user should check it
  confirmed  a machine transcript the user has checked/edited
  needs_text nothing could be read; the user can type what it says, otherwise it is ignored
"""
import base64
import html
import io
import mimetypes
import os
import re
import zipfile
from datetime import datetime

from .parser import clean, parse_chat

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

AUDIO = {".opus", ".ogg", ".oga", ".mp3", ".m4a", ".aac", ".wav", ".amr", ".3gp", ".webm", ".flac"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
DOC = {".pdf", ".docx", ".txt", ".text", ".md", ".csv"}

MAX_TEXT_PER_ITEM = 8000


def ext(name: str) -> str:
    return os.path.splitext(name.lower())[1]


def decode(data: bytes) -> str:
    return clean(data.decode("utf-8-sig", errors="ignore"))


def guess_mime(name: str) -> str:
    if ext(name) == ".opus":
        return "audio/ogg"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def detect_kind(name: str, hint: str | None, data: bytes) -> str:
    if hint == "note":
        return "note"
    e = ext(name)
    if e in AUDIO:
        return "voice"
    if e in IMAGE:
        return "image"
    if e in (".pdf", ".docx"):
        return "document"
    if e in (".txt", ".text", ".md", ".csv", ""):
        return "chat" if len(parse_chat(decode(data))) >= 2 else "document"
    return "file"


# ------------------------------------------------------------------ readers

def read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:60]).strip()


def read_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def transcribe_audio(name: str, data: bytes) -> str:
    """Whisper through the OpenAI API. Returns "" when no key is set or the call fails."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return ""
    try:
        import httpx

        send_name = os.path.splitext(name)[0] + (".ogg" if ext(name) == ".opus" else ext(name))
        r = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (send_name, data, guess_mime(send_name))},
            data={"model": "whisper-1"},
            timeout=180,
        )
        r.raise_for_status()
        return r.json().get("text", "").strip()
    except Exception as e:
        print("Transcription failed:", e)
        return ""


OCR_PROMPT = (
    "This is a screenshot related to a business deal (a chat, message, invoice or note). Copy out all text you "
    "can read, exactly as written, keeping the original language and any numbers. For chat screenshots use one "
    "line per message as 'Sender: message'. Do not add commentary. If nothing is readable, reply with nothing."
)


def ocr_image(name: str, data: bytes) -> str:
    """Reads text from a screenshot with Claude vision. Returns "" when unavailable."""
    mt = IMG_MIME.get(ext(name))
    if not os.getenv("ANTHROPIC_API_KEY") or not mt or len(data) > 5 * 1024 * 1024:
        return ""
    try:
        import anthropic

        r = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mt,
                                             "data": base64.b64encode(data).decode()}},
                {"type": "text", "text": OCR_PROMPT},
            ]}],
        )
        return r.content[0].text.strip()
    except Exception as e:
        print("Screenshot reading failed:", e)
        return ""


def extract_text(kind: str, name: str, data: bytes) -> tuple[str, str]:
    """Returns (text, text_status)."""
    if kind == "chat":
        return decode(data), "ready"
    if kind == "note":
        return decode(data), "typed"
    if kind == "voice":
        t = transcribe_audio(name, data)
        return (t, "machine") if t else ("", "needs_text")
    if kind == "image":
        t = ocr_image(name, data)
        return (t, "machine") if t else ("", "needs_text")
    if kind == "document":
        try:
            if ext(name) == ".pdf":
                t = read_pdf(data)
            elif ext(name) == ".docx":
                t = read_docx(data)
            else:
                t = decode(data).strip()
        except Exception as e:
            print("Document reading failed:", e)
            t = ""
        return (t, "ready") if t else ("", "needs_text")
    return "", "needs_text"


# ------------------------------------------------------------------ timeline

def month_first(msgs: list[dict]) -> bool:
    """WhatsApp exports follow the phone's locale. If any 'second number' is above 12, it is month-first."""
    first_big = second_big = False
    for m in msgs:
        parts = m["date"].split("/")
        try:
            a, b = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            continue
        first_big |= a > 12
        second_big |= b > 12
    return second_big and not first_big


def chat_dt(date_s: str, time_s: str, mf: bool) -> datetime | None:
    try:
        a, b, y = (int(x) for x in date_s.split("/"))
    except ValueError:
        return None
    y += 2000 if y < 100 else 0
    day, mon = (b, a) if mf else (a, b)
    t = time_s.lower().replace(".", "").replace(" ", "")
    tt = None
    for fmt in ("%I:%M%p", "%I:%M:%S%p", "%H:%M:%S", "%H:%M"):
        try:
            tt = datetime.strptime(t, fmt)
            break
        except ValueError:
            continue
    try:
        return datetime(y, mon, day, tt.hour if tt else 0, tt.minute if tt else 0, tt.second if tt else 0)
    except ValueError:
        return None


def iso_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def usable(it: dict) -> bool:
    return bool((it.get("text") or "").strip()) and it.get("text_status") != "needs_text"


def build_messages(items: list[dict]) -> list[dict]:
    """Merges every usable item into one time-ordered list of numbered messages.
    Chat messages keep their own timestamps. Other items use the 'when' the user gave them;
    items with no 'when' go to the end (and the readiness check warns about it)."""
    rows = []
    order = 0
    for it in items:
        if it.get("removed") or not usable(it):
            continue
        if it["kind"] == "chat":
            parsed = parse_chat(it["text"])
            mf = month_first(parsed)
            last = datetime.min
            for m in parsed:
                dt = chat_dt(m["date"], m["time"], mf) or last
                last = dt
                order += 1
                rows.append((dt, order, {"date": m["date"], "time": m["time"], "sender": m["sender"],
                                         "text": m["text"], "kind": "chat", "party": True,
                                         "item_id": it["id"], "item_name": it["label"] or it["name"]}))
        else:
            dt = iso_dt(it.get("occurred_at") or "")
            text = it["text"].strip()
            if len(text) > MAX_TEXT_PER_ITEM:
                text = text[:MAX_TEXT_PER_ITEM] + " …(cut)"
            order += 1
            rows.append((dt or datetime.max, order, {
                "date": dt.strftime("%d/%m/%Y") if dt else "undated",
                "time": dt.strftime("%H:%M") if dt else "",
                "sender": it.get("speaker") or it.get("label") or it["name"],
                "text": text, "kind": it["kind"], "party": bool(it.get("speaker")),
                "item_id": it["id"], "item_name": it.get("label") or it["name"]}))
    rows.sort(key=lambda r: (r[0], r[1]))
    out = []
    for i, (_, _, m) in enumerate(rows, 1):
        m["id"] = i
        out.append(m)
    return out


def readiness(items: list[dict]) -> dict:
    """Plain-language checklist shown before analysis."""
    active = [i for i in items if not i.get("removed")]
    blockers, warnings = [], []
    msgs = build_messages(active)

    if not active:
        blockers.append("Add at least one chat, voice note, screenshot, document or note.")
    elif not msgs:
        blockers.append("Nothing readable yet. Add a chat export, or type what was said in a voice note or screenshot.")

    for it in active:
        n = it["label"] or it["name"]
        if it["text_status"] == "needs_text":
            warnings.append(f"“{n}” has no text yet. Type what it says, or it will be left out.")
        elif it["text_status"] == "machine":
            warnings.append(f"“{n}” was read by a machine. Check it before relying on it.")
        elif it["kind"] != "chat" and usable(it) and not it.get("occurred_at") and len(active) > 1:
            warnings.append(f"“{n}” has no date. If the price or deadline changed, the order matters.")

    parties = list(dict.fromkeys(m["sender"] for m in msgs if m["party"]))
    if msgs and len(parties) < 2:
        warnings.append("Only one person found. Add the chat, or fill in “who said it” on your notes.")

    return {"can_analyze": bool(msgs), "blockers": blockers, "warnings": warnings,
            "people": parties, "readable": len({m["item_id"] for m in msgs}), "total": len(active)}
