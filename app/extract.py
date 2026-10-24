"""Turns parsed chat messages into structured contract terms.

Two engines, same output shape:
  1. Claude (if ANTHROPIC_API_KEY is set)  -> best quality, handles Hinglish/Kannada
  2. Rules (fallback)                      -> works offline so the demo never dies
"""
import json
import os
import re

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

SYSTEM = """You extract contract terms from informal business chats (English, Hindi, Kannada, Hinglish).
Return ONLY JSON, no markdown, in exactly this shape:
{
 "parties": [{"name": "", "role": "", "source_ids": []}],
 "scope": {"value": "", "source_ids": []},
 "price": {"value": "", "gst": "included|excluded|not_mentioned", "source_ids": []},
 "delivery": {"value": "", "source_ids": []},
 "payment_terms": {"value": "", "source_ids": []},
 "ambiguities": [{"field": "", "issue": "", "evidence_ids": [], "nudge": ""}],
 "missing": [{"field": "", "why": "", "nudge": ""}],
 "superseded": [{"field": "", "old": "", "new": "", "source_ids": []}]
}
Rules:
- Never invent values. Leave value as "" if the chat does not say.
- If a term was revised, use the LATEST value and list the old one under "superseded".
- source_ids are the [id] numbers of the messages that support the value.
- Flag vague phrases (next week, around 50k, usual terms, jaldi) under "ambiguities".
- Always check for: advance amount, GST, cancellation/refund, late delivery, defects/warranty, dispute handling.
  Put anything not discussed under "missing".
- "nudge" is a short, friendly message the business owner can send to the other party on WhatsApp to
  settle that point. Warm, casual, never legalistic. Match the chat's language style."""

# ---------------------------------------------------------------- rules engine

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
SPECIFIC_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?({MONTHS})[a-z]*\b|\b\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?\b",
    re.I,
)
DELIVERY_WORDS = re.compile(r"deliver|ready|dispatch|deadline|complete|mil jayega|milega|tak|by\b|before", re.I)
PAYMENT_SENT = re.compile(r"advance|token|deposit|booking|gpay|upi|phonepe|paytm|sent|paid|transfer|bhej", re.I)
NUM = re.compile(r"(₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)\s*(k|lakhs?|lac)?(?![\w])", re.I)
GST_EXCL = re.compile(r"gst\s*(alag|extra|separate|additional)|\+\s*gst|plus gst|excluding gst|gst nahi", re.I)
GST_INCL = re.compile(r"(inclusive|including|incl\.?|with)\s*(of\s*)?gst|gst\s*(included|inclusive|shamil)|all[- ]in", re.I)

VAGUE = [
    (r"next week|this week|jaldi|asap|\bsoon\b|kuch din|few days|end of (the )?month|agle hafte", "delivery"),
    (r"\busual\b|as always|same as last time|pehle jaise|baad mein|\blater\b", "payment_terms"),
    (r"\baround\b|\bapprox|\babout \d|thoda", "price"),
]

CHECKS = [
    ("advance", r"advance|token|deposit|booking", "Advance amount",
     "Without an advance amount, there is no proof the deal is serious.",
     "Quick one: how much advance should I send, and by when?"),
    ("gst", r"gst|tax", "GST",
     "Price may change by 18% depending on whether GST is included.",
     "Just checking: is the price with GST or without GST?"),
    ("cancellation", r"cancel|refund|return|wapas", "Cancellation or refund",
     "Unclear what happens if either side backs out.",
     "If either of us has to cancel, what should we do about the advance?"),
    ("late_delivery", r"\blate\b|delay|penalt|ontime|on time|\bder\b", "Late delivery",
     "No agreed consequence if the deadline is missed.",
     "If delivery gets late by a few days, what's fair for both of us?"),
    ("warranty", r"warrant|guarantee|defect|damage|replace|kharab", "Defects or warranty",
     "Unclear who fixes problems after delivery.",
     "If anything comes damaged or faulty, we replace or fix it. Sounds fair?"),
    ("dispute", r"dispute|court|arbitrat|mediat|lawyer", "If we disagree",
     "No agreed way to settle a disagreement.",
     "If we ever disagree, let's sit and talk first. Okay with that?"),
]

NUDGES = {
    "delivery": "Can we fix an exact delivery date so we are both on the same page?",
    "payment_terms": "Let's note the exact advance and balance, so there's no confusion later.",
    "price": "Just to be sure, can you confirm the final price in a single number?",
    "scope": "Quick recap: can you confirm the final quantity and what is included?",
}


def _snip(t: str, n: int = 110) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _amounts(text: str) -> list[float]:
    out = []
    for m in NUM.finditer(text):
        marker, num, suf = m.groups()
        try:
            val = float(num.replace(",", ""))
        except ValueError:
            continue
        mult = 1000 if suf and suf.lower() == "k" else 100000 if suf else 1
        val *= mult
        if val >= 10_000_000 or (1990 <= val <= 2100 and not marker):
            continue  # phone numbers, years
        if marker or suf or val >= 1000:
            out.append(val)
    return out


def _inr(v: float) -> str:
    return "₹" + f"{int(v):,}"


def extract_rules(msgs: list[dict]) -> dict:
    full = "\n".join(m["text"].lower() for m in msgs)
    senders = list(dict.fromkeys(m["sender"] for m in msgs))
    parties = [{"name": s, "role": "Party", "source_ids": [m["id"] for m in msgs if m["sender"] == s][:1]}
               for s in senders]

    # ---- price (latest wins), advance amounts are kept separate
    prices, advances = [], []
    for m in msgs:
        amts = _amounts(m["text"])
        if not amts:
            continue
        if PAYMENT_SENT.search(m["text"]):
            advances.append((m["id"], amts[0]))
        else:
            prices.append((m["id"], amts[-1]))
    price = {"value": "", "gst": "not_mentioned", "source_ids": []}
    superseded = []
    if prices:
        price["value"] = _inr(prices[-1][1])
        price["source_ids"] = [prices[-1][0]]
        distinct = []
        for pid, amt in prices:
            if not distinct or distinct[-1][1] != amt:
                distinct.append((pid, amt))
        for (oid, old), (nid, new) in zip(distinct, distinct[1:]):
            superseded.append({"field": "price", "old": _inr(old), "new": _inr(new), "source_ids": [oid, nid]})
    if GST_EXCL.search(full):
        price["gst"] = "excluded"
    elif GST_INCL.search(full):
        price["gst"] = "included"

    # ---- delivery
    delivery = {"value": "", "source_ids": []}
    specific = None
    vague_delivery = []
    for m in msgs:
        if not DELIVERY_WORDS.search(m["text"]):
            continue
        d = SPECIFIC_DATE.search(m["text"])
        if d:
            specific = (m["id"], d.group(0))
        elif re.search(VAGUE[0][0], m["text"], re.I):
            vague_delivery.append((m["id"], re.search(VAGUE[0][0], m["text"], re.I).group(0)))
    if specific:
        delivery = {"value": specific[1], "source_ids": [specific[0]]}
        for vid, phrase in vague_delivery:
            if vid < specific[0]:
                superseded.append({"field": "delivery", "old": phrase, "new": specific[1],
                                   "source_ids": [vid, specific[0]]})
    elif vague_delivery:
        delivery = {"value": vague_delivery[-1][1], "source_ids": [vague_delivery[-1][0]]}

    # ---- payment terms
    parts, pay_ids = [], []
    if advances:
        parts.append(f"Advance {_inr(advances[-1][1])}")
        pay_ids.append(advances[-1][0])
    for m in msgs:
        if re.search(r"baaki|balance|remaining|on delivery|delivery pe|delivery par", m["text"], re.I):
            if re.search(r"delivery pe|delivery par|on delivery", m["text"], re.I):
                parts.append("balance on delivery")
            else:
                parts.append("balance: " + _snip(m["text"], 60))
            pay_ids.append(m["id"])
            break
    mode = re.search(r"gpay|upi|phonepe|paytm|cash|cheque|neft|bank transfer", full)
    if mode:
        names = {"gpay": "GPay", "upi": "UPI", "phonepe": "PhonePe", "paytm": "Paytm", "neft": "NEFT"}
        parts.append("paid via " + names.get(mode.group(0), mode.group(0)))
    payment = {"value": "; ".join(parts), "source_ids": pay_ids}

    # ---- scope (first message describing the order; quantity revisions are followed)
    UNITS = r"cards|pcs|pieces|units|nos|kg|sets|boxes|copies|items|bags"
    QTY = re.compile(rf"(\d{{1,6}})\s*({UNITS})|({UNITS})\s*(\d{{1,6}})", re.I)
    scope = {"value": "", "source_ids": []}
    qty_changed = False
    for m in msgs:
        if QTY.search(m["text"]):
            text = re.sub(r"[,.]?\s*(₹|rs\.?|inr)\s*[\d,]+\s*(k|lakh)?\s*(total|only|final)?", "", m["text"], flags=re.I)
            scope = {"value": _snip(text.strip(" ,."), 160), "source_ids": [m["id"]]}
            break
    if scope["value"]:
        q0 = QTY.search(scope["value"])
        old_qty = q0.group(1) or q0.group(4)
        for m in msgs:
            if m["id"] <= scope["source_ids"][0] or not re.search(r"change|chahiye|need|want|instead", m["text"], re.I):
                continue
            q = QTY.search(m["text"])
            new_qty = (q.group(1) or q.group(4)) if q else None
            if new_qty and new_qty != old_qty:
                superseded.append({"field": "scope", "old": f"{old_qty} {q0.group(2) or q0.group(3)}",
                                   "new": f"{new_qty} {q.group(2) or q.group(3)}",
                                   "source_ids": [scope["source_ids"][0], m["id"]]})
                scope["value"] = scope["value"].replace(old_qty, new_qty, 1)
                scope["source_ids"].append(m["id"])
                old_qty = new_qty
            elif re.search(r"\bchange\b|badal|instead", m["text"], re.I):
                qty_changed = True

    # ---- ambiguities (dropped if a later message settles the same field)
    ambiguities, seen = [], set()
    for m in msgs:
        for pat, field in VAGUE:
            hit = re.search(pat, m["text"], re.I)
            if not hit or (field, hit.group(0).lower()) in seen:
                continue
            settled = (
                (field == "delivery" and specific and specific[0] > m["id"])
                or (field == "payment_terms" and advances and advances[-1][0] > m["id"])
                or (field == "price" and prices and prices[-1][0] > m["id"])
            )
            if settled:
                continue
            seen.add((field, hit.group(0).lower()))
            ambiguities.append({"field": field, "issue": f"“{hit.group(0)}” is vague.",
                                "evidence_ids": [m["id"]], "nudge": NUDGES[field]})
    # quantity changed mid-chat?
    if qty_changed:
        ambiguities.append({"field": "scope", "issue": "Order details seem to have changed during the chat.",
                            "evidence_ids": [scope["source_ids"][-1]] if scope["source_ids"] else [],
                            "nudge": NUDGES["scope"]})

    # ---- missing
    missing = []
    if not price["value"]:
        missing.append({"field": "Price", "why": "No clear price found.", "nudge": NUDGES["price"]})
    if not delivery["value"]:
        missing.append({"field": "Delivery date", "why": "No delivery time found.", "nudge": NUDGES["delivery"]})
    for key, pat, label, why, nudge in CHECKS:
        if key == "gst" and price["gst"] != "not_mentioned":
            continue
        if key == "advance" and advances:
            continue
        if not re.search(pat, full):
            missing.append({"field": label, "why": why, "nudge": nudge})

    uniq, seen_s = [], set()
    for x in superseded:
        key = (x["field"], x["old"], x["new"])
        if key not in seen_s:
            seen_s.add(key)
            uniq.append(x)
    superseded = uniq

    return {"engine": "rules", "parties": parties, "scope": scope, "price": price,
            "delivery": delivery, "payment_terms": payment, "ambiguities": ambiguities,
            "missing": missing, "superseded": superseded}


# ---------------------------------------------------------------- claude engine

def extract_claude(msgs: list[dict]) -> dict:
    import anthropic

    chat = "\n".join(f"[{m['id']}] {m['date']} {m['time']} {m['sender']}: {m['text']}" for m in msgs)
    client = anthropic.Anthropic()
    r = client.messages.create(model=MODEL, max_tokens=2500, system=SYSTEM,
                               messages=[{"role": "user", "content": chat}])
    raw = r.content[0].text.strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    data = json.loads(raw)
    data["engine"] = "claude"
    for k, default in (("parties", []), ("ambiguities", []), ("missing", []), ("superseded", [])):
        data.setdefault(k, default)
    for k in ("scope", "price", "delivery", "payment_terms"):
        data.setdefault(k, {"value": "", "source_ids": []})
    data["price"].setdefault("gst", "not_mentioned")
    return data


def extract_terms(msgs: list[dict]) -> dict:
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return extract_claude(msgs)
        except Exception as e:  # never kill the demo
            print("Claude extraction failed, using rules:", e)
    return extract_rules(msgs)
