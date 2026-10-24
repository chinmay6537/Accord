"""Tamper-evident evidence chain.

Every event (chat uploaded, terms confirmed, agreement generated, party confirmed...)
becomes one entry. Each entry stores the SHA-256 of the content AND the hash of the
previous entry, so changing anything in the past breaks every hash after it.
"""
import hashlib
import json
from datetime import datetime, timezone

from .db import conn

GENESIS = "0" * 64
FIELDS = ("seq", "kind", "content_hash", "meta", "ts", "prev_hash")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry_hash(e: dict) -> str:
    body = {k: e[k] for k in FIELDS}
    return sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def _row_to_entry(r) -> dict:
    return {
        "seq": r["seq"],
        "kind": r["kind"],
        "content_hash": r["content_hash"],
        "meta": json.loads(r["meta"]),
        "ts": r["ts"],
        "prev_hash": r["prev_hash"],
        "entry_hash": r["entry_hash"],
    }


def append(deal_id: str, kind: str, content: bytes, meta: dict | None = None) -> dict:
    with conn() as c:
        last = c.execute(
            "SELECT seq, entry_hash FROM evidence WHERE deal_id=? ORDER BY seq DESC LIMIT 1",
            (deal_id,),
        ).fetchone()
        e = {
            "seq": (last["seq"] + 1) if last else 1,
            "kind": kind,
            "content_hash": sha(content),
            "meta": meta or {},
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prev_hash": last["entry_hash"] if last else GENESIS,
        }
        e["entry_hash"] = _entry_hash(e)
        c.execute(
            "INSERT INTO evidence (deal_id, seq, kind, content_hash, meta, ts, prev_hash, entry_hash)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (deal_id, e["seq"], kind, e["content_hash"], json.dumps(e["meta"]),
             e["ts"], e["prev_hash"], e["entry_hash"]),
        )
    return e


def get_chain(deal_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM evidence WHERE deal_id=? ORDER BY seq", (deal_id,)
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def verify(deal_id: str, chat_text: str | None = None) -> dict:
    """Recompute every hash. Returns validity and the first broken entry (if any)."""
    chain = get_chain(deal_id)
    prev = GENESIS
    broken_at = None
    for e in chain:
        if e["prev_hash"] != prev or _entry_hash(e) != e["entry_hash"]:
            broken_at = e["seq"]
            break
        prev = e["entry_hash"]

    chat_ok = None
    if chat_text is not None and chain and chain[0]["kind"] == "chat_export":
        chat_ok = sha(chat_text.encode()) == chain[0]["content_hash"]

    return {
        "valid": broken_at is None and chat_ok is not False,
        "broken_at": broken_at,
        "chat_matches": chat_ok,
        "length": len(chain),
        "head": chain[-1]["entry_hash"] if chain else GENESIS,
    }


def find_by_content_hash(h: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT deal_id, seq, kind, ts FROM evidence WHERE content_hash=?", (h,)
        ).fetchall()
    return [dict(r) for r in rows]
