"""Builds a short plain-language agreement from confirmed terms. No LLM needed, so it is
deterministic and the hash of the text is stable."""
from datetime import date

TBD = "to be agreed"

GST_TEXT = {
    "included": "GST is included in the price.",
    "excluded": "GST will be charged extra, on top of the price.",
    "not_mentioned": "GST: " + TBD + ".",
}

VOICE = {
    "friendly": {
        "title": "Our simple agreement",
        "intro": "This is a short written record of what we already agreed on chat, so we both remember it the same way.",
        "scope": "What we agreed",
        "price": "Price",
        "delivery": "Delivery",
        "payment": "Payment",
        "open": "Still to settle between us",
        "closing": "If anything above looks wrong, tap “Suggest a change” and we will fix it together.",
    },
    "formal": {
        "title": "Agreement of terms",
        "intro": "This document records the terms agreed between the Parties through their written communications.",
        "scope": "Scope of work or goods",
        "price": "Consideration",
        "delivery": "Time of delivery",
        "payment": "Payment terms",
        "open": "Matters not yet agreed",
        "closing": "Either Party may request a correction to the above before confirming.",
    },
}


def _v(term: dict) -> str:
    v = (term or {}).get("value", "").strip()
    return v if v else TBD


def build_agreement(title: str, terms: dict, tone: str = "friendly") -> str:
    t = VOICE.get(tone, VOICE["friendly"])
    names = [p["name"] for p in terms.get("parties", [])] or ["Party A", "Party B"]
    between = " and ".join(names[:2])
    gst = GST_TEXT.get(terms.get("price", {}).get("gst", "not_mentioned"), GST_TEXT["not_mentioned"])

    open_points = [m["field"] for m in terms.get("missing", [])] + \
                  [a["field"].replace("_", " ").title() for a in terms.get("ambiguities", [])]
    open_points = list(dict.fromkeys(open_points))

    lines = [
        t["title"].upper(),
        title,
        f"Date: {date.today().strftime('%d %b %Y')}",
        f"Between: {between}",
        "",
        t["intro"],
        "",
        "IN 10 SECONDS",
        f"- What: {_v(terms.get('scope'))}",
        f"- Price: {_v(terms.get('price'))}",
        f"- Delivery: {_v(terms.get('delivery'))}",
        f"- Payment: {_v(terms.get('payment_terms'))}",
        "",
        f"1. {t['scope']}",
        f"   {_v(terms.get('scope'))}",
        "",
        f"2. {t['price']}",
        f"   {_v(terms.get('price'))}. {gst}",
        "",
        f"3. {t['delivery']}",
        f"   {_v(terms.get('delivery'))}",
        "",
        f"4. {t['payment']}",
        f"   {_v(terms.get('payment_terms'))}",
    ]
    if open_points:
        lines += ["", f"5. {t['open']}"] + [f"   - {p}" for p in open_points]
    lines += [
        "",
        t["closing"],
        "",
        "Evidence: this record was prepared from the parties' own chat. Its fingerprint is saved in a",
        "tamper-evident log, so either side can later prove nothing was changed.",
        "",
        "Note: this document may need stamp duty as per your state's rules before it can be used in court.",
        "Please check with your state stamp office or e-stamp provider. This is not legal advice.",
    ]
    return "\n".join(lines)
