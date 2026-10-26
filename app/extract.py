"""Turns parsed chat messages into structured contract terms.

Three engines, same output shape:
  1. Claude (ANTHROPIC_API_KEY)                    best quality, handles Hinglish / Kannada
  2. Local model (LOCAL_LLM_URL, e.g. a friend's laptop running Ollama through scripts/llm_gateway.py)
  3. Rules                                          works offline, never fails, also used to double-check the models

Which one runs is set by LLM_PROVIDER = auto (default) | claude | local | rules.
Whatever a model answers is checked against the chat before it is shown (see _guard): a price that is not in the
chat, or an older price when a later one was clearly accepted, is corrected, so a small model cannot quietly
put the wrong number in an agreement.
"""
import json
import os
import re

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

SYSTEM = """You extract contract terms from informal business evidence (English, Hindi, Kannada, Hinglish).
Each line is "[id] date time sender (source): text". The source is chat, voice note, call note, document or
screenshot. Voice-note and screenshot text are machine transcripts and may contain errors: if a key number or
date looks doubtful, flag it under "ambiguities" instead of trusting it.
Return ONLY JSON, no markdown, in exactly this shape:
{
 "summary": "",
 "parties": [{"name": "", "role": "", "source_ids": []}],
 "scope": {"value": "", "source_ids": []},
 "price": {"value": "", "gst": "included|excluded|not_mentioned", "source_ids": []},
 "delivery": {"value": "", "source_ids": []},
 "payment_terms": {"value": "", "source_ids": []},
 "ambiguities": [{"field": "", "issue": "", "evidence_ids": [], "nudge": ""}],
 "missing": [{"field": "", "why": "", "nudge": ""}],
 "superseded": [{"field": "", "old": "", "new": "", "reason": "", "source_ids": []}]
}
Rules:
- Never invent values. Leave value as "" if the chat does not say.
- PRICE: use the latest price that the OTHER side clearly accepted ("theek hai", "done", "ok", "chalo", "pakka").
  A quote nobody accepted does not replace an accepted price: keep the accepted one and add an ambiguity.
  A price belongs to a quantity. If the quantity changed (500 cards became 600 cards), the price for the new
  quantity replaces the old one, and "reason" says so. Never mix a price with a quantity it was not agreed for.
- Amounts for advance, balance or "sent"/"paid" are payment_terms, never the price.
- If a term was revised, use the LATEST accepted value and list the old one under "superseded".
- source_ids are the [id] numbers of the messages that support the value.
- Flag vague phrases (next week, around 50k, usual terms, jaldi) under "ambiguities".
- Always check for: advance amount, GST, cancellation/refund, late delivery, defects/warranty, dispute handling.
  Put anything not discussed under "missing".
- "nudge" is a short, friendly message the business owner can send to the other party on WhatsApp to
  settle that point. Warm, casual, never legalistic. Match the chat's language style.
- "summary" is 2 to 4 plain sentences for a busy shopkeeper: who agreed what, the final price and what it is for,
  delivery, payment, and what changed along the way and why. Use only facts from the chat."""

# ---------------------------------------------------------------- rules engine

MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
SPECIFIC_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?({MONTHS})[a-z]*\b|\b\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?\b",
    re.I,
)
DELIVERY_WORDS = re.compile(r"deliver|ready|dispatch|deadline|complete|mil jayega|milega|tak|by\b|before", re.I)
NUM = re.compile(r"(₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)\s*(k|lakhs?|lac)?(?![\w])", re.I)
GST_EXCL = re.compile(r"gst\s*(alag|extra|separate|additional)|\+\s*gst|plus gst|excluding gst|gst nahi", re.I)
GST_INCL = re.compile(r"(inclusive|including|incl\.?|with)\s*(of\s*)?gst|gst\s*(included|inclusive|shamil)|all[- ]in", re.I)

UNITS = r"cards?|pcs|pc|pieces?|units?|nos|kg|sets?|boxes|box|copies|items?|bags?|banners?|sheets?"
QTY = re.compile(rf"(\d{{1,6}})\s*({UNITS})\b|\b({UNITS})\s*(\d{{1,6}})\b", re.I)
UNIT_AFTER = re.compile(rf"^\s*({UNITS})\b", re.I)

# what an amount is about, judged from the few words right next to it (not the whole message)
RATE = re.compile(r"^\s*(per\b|each\b|/\s*\w|ka rate|rate\b|apiece)", re.I)
RATE_BEFORE = re.compile(r"\brate\b|\bper (card|pc|piece|unit|kg)", re.I)
ADV = re.compile(r"advance|token|deposit|booking|bhej\w*|\bsent\b|\bpaid\b|gpay|upi|phonepe|paytm|transferred?", re.I)
BAL = re.compile(r"baaki|baki|balance|remaining|pending|delivery pe|delivery par|on delivery", re.I)
NEG_AFTER = re.compile(r"^\W*(pe|par|tak)?\s*(nahi|nahin|nhi|not\b|no\b)", re.I)
NEG_BEFORE = re.compile(r"\b(not|nahi|nahin|nhi|no)\s*$", re.I)
ACCEPT = re.compile(r"\b(ok|okay|theek|thik|done|deal|chalo|pakka|confirm\w*|agreed?|fine|haan|han|yes|sure|manzoor|sahi|perfect)\b", re.I)
REJECT = re.compile(r"zyada|jyada|kam kar|reduce|discount|too (much|high|costly)|mehnga|expensive|nahi|nahin|nhi|\bnot\b|\bno\b|hmm|sochta|let me (check|think)|baad mein", re.I)

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


def _inr(v: float) -> str:
    return "₹" + f"{int(round(v)):,}"


def _amounts(text: str) -> list[dict]:
    """Every money amount in a message, each tagged by what it is about: price, advance, balance or rate.
    The tag comes from the words right beside the number, so "54,000 final, advance 10k" is read correctly."""
    out = []
    for m in NUM.finditer(text):
        marker, num, suf = m.groups()
        try:
            val = float(num.replace(",", ""))
        except ValueError:
            continue
        val *= 1000 if suf and suf.lower() == "k" else 100000 if suf else 1
        rest = text[m.end():]
        if UNIT_AFTER.match(rest):
            continue                                              # "500 cards" is a quantity, not money
        if val >= 10_000_000 or (1990 <= val <= 2100 and not marker):
            continue                                              # phone numbers, years
        after = re.split(r"[.,;!?\n]|\d", rest, maxsplit=1)[0][:26]
        before = re.split(r"[.,;!?\n]", text[:m.start()])[-1][-26:]
        is_rate = bool(RATE.match(after) or RATE_BEFORE.search(before))
        if not (marker or suf or val >= 1000 or is_rate):
            continue
        if is_rate:
            kind = "rate"
        elif BAL.search(after) or BAL.search(before):
            kind = "balance"
        elif ADV.search(after) or ADV.search(before):
            kind = "advance"
        else:
            kind = "price"
        out.append({"amt": val, "kind": kind, "negated": bool(NEG_AFTER.match(after) or NEG_BEFORE.search(before))})
    return out


def _quantities(msgs: list[dict]) -> list[dict]:
    """The order quantity over time: the first message that states one, then any later change ("cards 600 chahiye")."""
    out = []
    for m in msgs:
        q = QTY.search(m["text"])
        if not q:
            continue
        num = q.group(1) or q.group(4)
        unit = (q.group(2) or q.group(3)).lower()
        if not out or (num != out[-1]["num"] and re.search(r"change|chahiye|need|want|instead|badal|ab ", m["text"], re.I)):
            out.append({"id": m["id"], "num": num, "unit": unit})
    return out


def _qty_at(quantities: list[dict], msg_id: int):
    cur = None
    for q in quantities:
        if q["id"] <= msg_id:
            cur = q
    return cur


def _price_events(msgs, quantities):
    """Every price that was put on the table, plus advances, balances and unit rates."""
    events, advances, balances, rates = [], [], [], []
    for m in msgs:
        picks = [a for a in _amounts(m["text"])]
        for a in picks:
            if a["kind"] == "advance":
                advances.append((m["id"], a["amt"]))
            elif a["kind"] == "balance":
                balances.append((m["id"], a["amt"]))
        cand = [a for a in picks if a["kind"] in ("price", "rate") and not a["negated"]]
        if not cand:
            continue
        a = cand[-1]
        q = _qty_at(quantities, m["id"])
        ev = {"id": m["id"], "sender": m["sender"], "amt": a["amt"], "qty": q, "text": m["text"], "derived": ""}
        if a["kind"] == "rate":
            if not q:
                rates.append(m["id"])
                continue
            ev["derived"] = f"{_inr(a['amt'])} per {q['unit'].rstrip('s')} x {q['num']}"
            ev["amt"] = a["amt"] * int(q["num"])
        events.append(ev)
    return events, advances, balances, rates


def _confirmed(events, msgs):
    """Mark which prices the other side clearly accepted. A price is accepted when
    (a) a message with an accepting word repeats it ("Theek hai 46,500 done"), or
    (b) the other person replies with an accepting word and no different number, and no complaint about the price."""
    by_id = {m["id"]: m for m in msgs}
    order = [m["id"] for m in msgs]
    for ev in events:
        ev["confirmed"] = False
    for i, ev in enumerate(events):
        t = ev["text"]
        if ACCEPT.search(t):
            for prev in reversed(events[:i]):
                if prev["sender"] != ev["sender"] and prev["amt"] == ev["amt"]:
                    prev["confirmed"] = ev["confirmed"] = True
                    break
        pos = order.index(ev["id"])
        for mid in order[pos + 1: pos + 5]:
            m = by_id[mid]
            if m["sender"] == ev["sender"]:
                continue
            others = [a for a in _amounts(m["text"]) if a["kind"] == "price" and not a["negated"]]
            if others and any(a["amt"] != ev["amt"] for a in others):
                break                                              # they answered with a different number
            if ACCEPT.search(m["text"]) and not REJECT.search(m["text"]):
                ev["confirmed"] = True
                break
    return events


def _sentence_list(items):
    items = [i for i in items if i]
    return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + items[-1] if items else ""


def _summary(parties, scope, price, delivery, payment, history, notes, missing):
    names = " and ".join(p["name"] for p in parties[:2])
    parts = []
    if price["value"]:
        what = f" {scope['value']}" if scope["value"] else " the order"
        gst = {"excluded": ", plus GST", "included": ", GST included"}.get(price["gst"], "")
        parts.append(f"{names + ' agreed on' if names else 'Agreed:'}{what} for {price['value']}{gst}.")
    elif scope["value"]:
        parts.append(f"{names + ' discussed' if names else 'Discussed:'} {scope['value']}, but no price was agreed.")
    parts.extend(history)
    if delivery["value"]:
        parts.append(f"Delivery: {delivery['value']}.")
    if payment["value"]:
        parts.append(payment["value"][0].upper() + payment["value"][1:] + ".")
    parts.extend(notes)
    if missing:
        parts.append("Still to settle: " + _sentence_list([m["field"].lower() for m in missing[:4]]) + ".")
    return " ".join(parts)


def extract_rules(msgs: list[dict]) -> dict:
    full = "\n".join(m["text"].lower() for m in msgs)
    senders = list(dict.fromkeys(m["sender"] for m in msgs if m.get("party", True)))
    parties = [{"name": s, "role": "Party", "source_ids": [m["id"] for m in msgs if m["sender"] == s][:1]}
               for s in senders]

    quantities = _quantities(msgs)
    events, advances, balances, rate_gaps = _price_events(msgs, quantities)
    events = _confirmed(events, msgs)

    # ---- price: the latest price the other side clearly accepted. A later quote nobody accepted does not replace it.
    price = {"value": "", "gst": "not_mentioned", "source_ids": []}
    superseded, history, price_notes, price_flags = [], [], [], []
    final = None
    if events:
        accepted = [e for e in events if e["confirmed"]]
        final = accepted[-1] if accepted else events[-1]
        price["value"] = _inr(final["amt"])
        price["source_ids"] = [final["id"]]
        if final["derived"]:
            price_notes.append(f"The price is worked out from {final['derived']}.")
        upto = [e for e in events if e["id"] <= final["id"]]
        distinct = []
        for e in upto:
            if not distinct or distinct[-1]["amt"] != e["amt"]:
                distinct.append(e)
        for old, new in zip(distinct, distinct[1:]):
            row = {"field": "price", "old": _inr(old["amt"]), "new": _inr(new["amt"]), "source_ids": [old["id"], new["id"]]}
            if old["qty"] and new["qty"] and old["qty"]["num"] != new["qty"]["num"]:
                row["reason"] = f"The order changed from {old['qty']['num']} to {new['qty']['num']} {new['qty']['unit']}."
            superseded.append(row)
        if len(distinct) > 1:
            last_change = superseded[-1]
            history.append(f"The price changed {len(superseded)} time{'s' if len(superseded) > 1 else ''} along the way.")
            if last_change.get("reason"):
                prev_qty = distinct[-2]["qty"]
                history.append(f"{last_change['old']} was for {prev_qty['num']} {prev_qty['unit']}; "
                               f"when the order became {final['qty']['num']} {final['qty']['unit']}, the price became {last_change['new']}.")
        later = [e for e in events if e["id"] > final["id"] and e["amt"] != final["amt"]]
        if later and accepted:
            l = later[-1]
            price_flags.append({"field": "price", "issue": f"{_inr(l['amt'])} was mentioned after {_inr(final['amt'])} was agreed, but nobody clearly accepted it.",
                                "evidence_ids": [l["id"]], "nudge": f"Quick check: is the price still {_inr(final['amt'])}, or did we move to {_inr(l['amt'])}?"})
            price_notes.append(f"{_inr(l['amt'])} was mentioned later but not accepted, so {_inr(final['amt'])} stands.")
        elif not accepted and len({e['amt'] for e in events}) > 1:
            price_flags.append({"field": "price", "issue": "Prices were discussed but none was clearly accepted.",
                                "evidence_ids": [final["id"]], "nudge": NUDGES["price"]})
        if quantities and final["qty"] and quantities[-1]["num"] != final["qty"]["num"]:
            q0, q1 = final["qty"], quantities[-1]
            price_flags.append({"field": "price", "issue": f"{_inr(final['amt'])} was agreed for {q0['num']} {q0['unit']}, but the order is now {q1['num']} {q1['unit']}.",
                                "evidence_ids": [final["id"], q1["id"]], "nudge": f"Is {_inr(final['amt'])} still right now that it is {q1['num']} {q1['unit']}?"})
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
    parts, pay_ids, pay_flags = [], [], []
    if advances:
        distinct_adv = list(dict.fromkeys(a for _, a in advances))
        parts.append(f"Advance {_inr(advances[-1][1])}")
        pay_ids.append(advances[-1][0])
        if len(distinct_adv) > 1:
            pay_flags.append({"field": "payment_terms", "issue": "Different advance amounts were mentioned: " + _sentence_list([_inr(a) for a in distinct_adv]) + ".",
                              "evidence_ids": [i for i, _ in advances], "nudge": "Can we confirm the exact advance amount, so there's no confusion?"})
    for m in msgs:
        if re.search(r"baaki|balance|remaining|on delivery|delivery pe|delivery par", m["text"], re.I):
            if balances:
                parts.append(f"balance {_inr(balances[-1][1])}" + (" on delivery" if re.search(r"delivery pe|delivery par|on delivery", m["text"], re.I) else ""))
            elif re.search(r"delivery pe|delivery par|on delivery", m["text"], re.I):
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
    scope = {"value": "", "source_ids": []}
    qty_changed = False
    for m in msgs:
        if QTY.search(m["text"]):
            text = re.sub(r"[,.]?\s*(₹|rs\.?|inr)\s*[\d,]+\s*(k|lakh)?\s*(total|only|final)?", "", m["text"], flags=re.I)
            scope = {"value": _snip(text.strip(" ,."), 160), "source_ids": [m["id"]]}
            break
    if scope["value"] and quantities:
        first = quantities[0]
        for q in quantities[1:]:
            superseded.append({"field": "scope", "old": f"{first['num']} {first['unit']}", "new": f"{q['num']} {q['unit']}",
                               "source_ids": [first["id"], q["id"]]})
            scope["value"] = re.sub(rf"\b{first['num']}\b", q["num"], scope["value"], count=1)
            scope["source_ids"].append(q["id"])
            first = q
        for m in msgs:
            if m["id"] > scope["source_ids"][0] and re.search(r"\bchange\b|badal|instead", m["text"], re.I) and len(quantities) == 1:
                qty_changed = True

    # ---- ambiguities (dropped if a later message settles the same field)
    ambiguities, seen = list(price_flags) + list(pay_flags), set()
    for m in msgs:
        for pat, field in VAGUE:
            hit = re.search(pat, m["text"], re.I)
            if not hit or (field, hit.group(0).lower()) in seen:
                continue
            settled = (
                (field == "delivery" and specific and specific[0] > m["id"])
                or (field == "payment_terms" and advances and advances[-1][0] > m["id"])
                or (field == "price" and events and events[-1]["id"] > m["id"])
            )
            if settled:
                continue
            seen.add((field, hit.group(0).lower()))
            ambiguities.append({"field": field, "issue": f"“{hit.group(0)}” is vague.",
                                "evidence_ids": [m["id"]], "nudge": NUDGES[field]})
    if rate_gaps:
        ambiguities.append({"field": "price", "issue": "A price per piece was given but the quantity is not clear.",
                            "evidence_ids": rate_gaps[:2], "nudge": NUDGES["scope"]})
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

    return {"engine": "rules", "summary": _summary(parties, scope, price, delivery, payment, history, price_notes, missing),
            "parties": parties, "scope": scope, "price": price,
            "delivery": delivery, "payment_terms": payment, "ambiguities": ambiguities,
            "missing": missing, "superseded": superseded}


# ---------------------------------------------------------------- model engines (Claude, local)

SRC = {"chat": "chat", "voice": "voice note", "image": "screenshot", "document": "document", "note": "call note", "file": "file"}


def _chat_text(msgs: list[dict]) -> str:
    return "\n".join(f"[{m['id']}] {m['date']} {m['time']} {m['sender']} ({SRC.get(m.get('kind', 'chat'), 'chat')}): {m['text']}"
                     for m in msgs)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = raw[raw.find("{"): raw.rfind("}") + 1]
    return json.loads(raw)


def _complete(data: dict, engine: str) -> dict:
    data["engine"] = engine
    for k, default in (("parties", []), ("ambiguities", []), ("missing", []), ("superseded", []), ("summary", "")):
        if not isinstance(data.get(k), type(default)):
            data[k] = default
    for k in ("scope", "price", "delivery", "payment_terms"):
        if not isinstance(data.get(k), dict):
            data[k] = {"value": "", "source_ids": []}
        data[k].setdefault("value", "")
        data[k].setdefault("source_ids", [])
    data["price"].setdefault("gst", "not_mentioned")
    return data


def extract_claude(msgs: list[dict]) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    r = client.messages.create(model=MODEL, max_tokens=2500, system=SYSTEM,
                               messages=[{"role": "user", "content": _chat_text(msgs)}])
    return _complete(_parse_json(r.content[0].text), "claude")


# A tiny worked example. Small models follow an example far better than a long rulebook, and this one teaches the
# two things they get wrong most: a price belongs to a quantity, and an advance is not the price.
EXAMPLE_IN = """[1] 01/01/2026 10:00 Asha (chat): 100 mugs, Rs 5,000 total
[2] 01/01/2026 10:05 Bilal (chat): Ok done
[3] 02/01/2026 09:00 Asha (chat): Make it 200 mugs. Price?
[4] 02/01/2026 09:10 Bilal (chat): 200 will be 9,000
[5] 02/01/2026 09:12 Asha (chat): Chalo 9,000 final. Delivery by 20 Jan
[6] 02/01/2026 09:20 Asha (chat): Sending 2,000 advance on UPI"""
EXAMPLE_OUT = {
    "summary": "Asha and Bilal agreed on 200 mugs for ₹9,000. The price changed once: ₹5,000 was for 100 mugs; when the order became 200 mugs, the price became ₹9,000. Delivery by 20 Jan. Advance ₹2,000 via UPI.",
    "parties": [{"name": "Asha", "role": "Buyer", "source_ids": [1]}, {"name": "Bilal", "role": "Seller", "source_ids": [2]}],
    "scope": {"value": "200 mugs", "source_ids": [1, 3]},
    "price": {"value": "₹9,000", "gst": "not_mentioned", "source_ids": [5]},
    "delivery": {"value": "20 Jan", "source_ids": [5]},
    "payment_terms": {"value": "Advance ₹2,000 via UPI", "source_ids": [6]},
    "ambiguities": [],
    "missing": [{"field": "GST", "why": "Price may change by 18% depending on GST.", "nudge": "Quick check: is 9,000 with GST or without?"}],
    "superseded": [{"field": "price", "old": "₹5,000", "new": "₹9,000", "reason": "The order changed from 100 to 200 mugs.", "source_ids": [1, 5]}],
}

# Ollama can force the answer into this exact shape, so a small model cannot return broken JSON.
_ids = {"type": "array", "items": {"type": "integer"}}
_val = {"type": "object", "properties": {"value": {"type": "string"}, "source_ids": _ids}, "required": ["value", "source_ids"]}
SCHEMA = {"type": "object", "required": ["summary", "parties", "scope", "price", "delivery", "payment_terms", "ambiguities", "missing", "superseded"],
          "properties": {
              "summary": {"type": "string"},
              "parties": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "source_ids": _ids}}},
              "scope": _val, "delivery": _val, "payment_terms": _val,
              "price": {"type": "object", "properties": {"value": {"type": "string"}, "gst": {"type": "string", "enum": ["included", "excluded", "not_mentioned"]}, "source_ids": _ids}, "required": ["value", "gst", "source_ids"]},
              "ambiguities": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "issue": {"type": "string"}, "evidence_ids": _ids, "nudge": {"type": "string"}}}},
              "missing": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "why": {"type": "string"}, "nudge": {"type": "string"}}}},
              "superseded": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "reason": {"type": "string"}, "source_ids": _ids}}},
          }}

DEFAULT_OLLAMA = "http://127.0.0.1:11434"


def local_configured() -> bool:
    """True when a local model is set up: an explicit URL, or LLM_PROVIDER=local (then Ollama on this same Mac)."""
    return bool(os.getenv("LOCAL_LLM_URL")) or os.getenv("LLM_PROVIDER", "").lower() == "local"


def extract_local(msgs: list[dict]) -> dict:
    """Ask a local model. With no LOCAL_LLM_URL it talks to Ollama on this same machine (the normal setup on a Mac).
    With LOCAL_LLM_URL + LOCAL_LLM_KIND=gateway it talks to scripts/llm_gateway.py on another laptop instead."""
    import httpx

    url = os.getenv("LOCAL_LLM_URL", "").rstrip("/")
    kind = os.getenv("LOCAL_LLM_KIND", "gateway" if url else "ollama")
    base = url or DEFAULT_OLLAMA
    timeout = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))
    headers = {"ngrok-skip-browser-warning": "1"}
    if os.getenv("LOCAL_LLM_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["LOCAL_LLM_TOKEN"]
    user = _chat_text(msgs)
    if kind == "ollama":
        model = os.getenv("LOCAL_LLM_MODEL", "accord-reader")
        r = httpx.post(base + "/api/chat", timeout=timeout, json={
            "model": model, "stream": False, "format": SCHEMA, "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 1800},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": EXAMPLE_IN},
                         {"role": "assistant", "content": json.dumps(EXAMPLE_OUT, ensure_ascii=False)},
                         {"role": "user", "content": user}]})
        r.raise_for_status()
        text, name = r.json()["message"]["content"], model
    else:
        r = httpx.post(base + "/generate", timeout=timeout, headers=headers, json={"system": SYSTEM, "user": user, "json": True})
        r.raise_for_status()
        out = r.json()
        text, name = out["text"], out.get("model", "local")
    return _complete(_parse_json(text), f"local:{name}")


def _numbers(text: str) -> set[float]:
    return {a["amt"] for a in _amounts(text)} | {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]{2,}", text or "") if x.replace(",", "").isdigit()}


def _guard(data: dict, rules: dict, msgs: list[dict]) -> dict:
    """Never show a model's answer unchecked. Fix ids that do not exist, and fix a price that is not in the chat or
    that disagrees with a later price the other side clearly accepted. Every correction is reported in engine_note."""
    ids = {m["id"] for m in msgs}
    notes = []

    def clean(v):
        return [i for i in v if i in ids] if isinstance(v, list) else []

    for k in ("scope", "price", "delivery", "payment_terms"):
        data[k]["source_ids"] = clean(data[k].get("source_ids"))
    for p in data["parties"]:
        p["source_ids"] = clean(p.get("source_ids"))
    for a in data["ambiguities"]:
        a["evidence_ids"] = clean(a.get("evidence_ids"))
    for s in data["superseded"]:
        s["source_ids"] = clean(s.get("source_ids"))

    in_chat = set()
    for m in msgs:
        in_chat |= _numbers(m["text"])
    in_chat |= {float(re.sub(r"[^\d.]", "", rules["price"]["value"]) or 0)}
    said = _numbers(data["price"]["value"])
    if data["price"]["value"] and (not said or not (said & in_chat)):
        data["price"].update({k: rules["price"][k] for k in ("value", "source_ids")})
        notes.append("The price the model gave is not in the chat, so the chat's own price was used.")
    elif rules["price"]["value"] and data["price"]["value"]:
        want = float(re.sub(r"[^\d.]", "", rules["price"]["value"]) or 0)
        if said and want not in said and any(rules["superseded"]) is not None:
            # the rules found a price the other side clearly accepted: a model must not pick a different one
            accepted_ids = rules["price"]["source_ids"]
            if accepted_ids and (not data["price"]["source_ids"] or max(data["price"]["source_ids"]) <= max(accepted_ids) or want in in_chat):
                data["price"].update({k: rules["price"][k] for k in ("value", "source_ids")})
                notes.append(f"The model picked a different price; the accepted price {rules['price']['value']} was used instead.")
    if not data["price"]["value"] and rules["price"]["value"]:
        data["price"].update({k: rules["price"][k] for k in ("value", "source_ids")})
    if data["price"].get("gst") not in ("included", "excluded", "not_mentioned"):
        data["price"]["gst"] = rules["price"]["gst"]
    for f in ("delivery", "payment_terms", "scope"):
        if not data[f]["value"] and rules[f]["value"]:
            data[f].update({k: rules[f][k] for k in ("value", "source_ids")})
            notes.append(f"The model left {f.replace('_', ' ')} empty; the built-in reader filled it in.")
    if not data["summary"].strip() or notes:
        data["summary"] = rules["summary"]
    seen = {(a["field"], a["issue"]) for a in data["ambiguities"]}
    for a in rules["ambiguities"]:
        if a["field"] == "price" and (a["field"], a["issue"]) not in seen:
            data["ambiguities"].append(a)
    if not data["superseded"]:
        data["superseded"] = rules["superseded"]
    if notes:
        data["engine_note"] = " ".join(notes)
    return data


def extract_terms(msgs: list[dict]) -> dict:
    """Pick the engine (LLM_PROVIDER=auto|claude|local|rules), check its answer, and never fail:
    if a model is unreachable the built-in rules answer instead and the page says so."""
    rules = extract_rules(msgs)
    provider = os.getenv("LLM_PROVIDER", "auto").lower()
    order = []
    if provider in ("auto", "claude") and os.getenv("ANTHROPIC_API_KEY"):
        order.append(("Claude", extract_claude))
    if provider in ("auto", "local") and local_configured():
        order.append(("The local model", extract_local))
    errors = []
    for name, fn in order:
        try:
            return _guard(fn(msgs), rules, msgs)
        except Exception as e:  # never kill the demo
            print(f"{name} extraction failed, trying next:", repr(e))
            errors.append(f"{name} could not be reached")
    if errors:
        rules["engine_note"] = "; ".join(errors) + ", so the built-in reader was used."
    return rules
