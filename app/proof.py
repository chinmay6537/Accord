"""Evidence items and the integrity check, shared by the dealer workflow and the customer review page."""
from pathlib import Path

from . import db, evidence


def items(deal_id: str, include_removed: bool = False) -> list[dict]:
    q = "SELECT * FROM items WHERE deal_id=?" + ("" if include_removed else " AND removed=0") + " ORDER BY id"
    with db.conn() as c:
        rows = c.execute(q, (deal_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["removed"] = bool(d["removed"])
        out.append(d)
    return out


def verification(deal_id: str) -> dict:
    """Chain check plus a re-hash of every stored file against what the chain recorded."""
    v = evidence.verify(deal_id)
    expected = {e["meta"].get("item_id"): e["content_hash"]
                for e in evidence.get_chain(deal_id) if e["kind"] == "evidence_added"}
    bad = []
    for it in items(deal_id, include_removed=True):
        p = Path(it["path"]) if it["path"] else None
        ok = bool(p and p.is_file() and evidence.sha(p.read_bytes()) == it["sha256"] == expected.get(it["id"]))
        if not ok:
            bad.append(it["id"])
    v["bad_files"] = bad
    v["valid"] = v["valid"] and not bad
    return v
