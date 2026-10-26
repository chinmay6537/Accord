"""PDF export: a one-page-ish agreement, and an evidence report with the terms, their sources and the proof trail.

Black and white on purpose (same look as the app). Fonts are bundled so the rupee sign prints everywhere.
`report_pdf(..., audience="customer")` leaves out anything a customer is not allowed to see in the app:
only the messages cited behind terms, never the rest of the chat or dealer-only history."""
from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

from . import db, evidence, proof
from .common import get_deal

FONTS = Path(__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Sans", str(FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONTS / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONTS / "DejaVuSansMono.ttf")))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")

INK = colors.black
SOFT = colors.Color(0.93, 0.93, 0.93)
W, H = A4
MARGIN = 18 * mm

S = {
    "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=22, leading=26, spaceAfter=4),
    "h": ParagraphStyle("h", fontName="Sans-Bold", fontSize=12.5, leading=16, spaceBefore=14, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Sans", fontSize=10, leading=14.5, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Sans", fontSize=8.5, leading=11.5),
    "muted": ParagraphStyle("muted", fontName="Sans", fontSize=9, leading=12.5, textColor=colors.Color(.25, .25, .25)),
    "mono": ParagraphStyle("mono", fontName="Mono", fontSize=6.8, leading=8.6),
    "th": ParagraphStyle("th", fontName="Sans-Bold", fontSize=8.5, leading=11, textColor=colors.white),
    "agr": ParagraphStyle("agr", fontName="Sans", fontSize=10, leading=14, spaceAfter=2),
    "agr_h": ParagraphStyle("agr_h", fontName="Sans-Bold", fontSize=10.5, leading=15, spaceBefore=6, spaceAfter=1),
    "agr_li": ParagraphStyle("agr_li", fontName="Sans", fontSize=10, leading=14, leftIndent=12, spaceAfter=1),
}

KIND = {
    "evidence_added": "Evidence added", "evidence_edited": "Evidence edited", "evidence_removed": "Evidence removed",
    "terms_extracted": "Terms read from the evidence", "terms_confirmed": "Terms checked by the dealer",
    "agreement_generated": "Agreement written", "owner_approved": "Sent for confirmation",
    "comment_added": "Comment on the agreement", "counterparty_confirmed": "Customer approved",
    "counterparty_requested_change": "Customer asked for a change",
}
CUSTOMER_KINDS = ("evidence_added", "terms_extracted", "terms_confirmed", "agreement_generated", "owner_approved",
                  "comment_added", "counterparty_confirmed", "counterparty_requested_change")
FIELDS = [("scope", "What was agreed"), ("price", "Price"), ("delivery", "Delivery"), ("payment_terms", "Payment")]
LABEL = dict(FIELDS)
STATUS = {"collecting": "Collecting evidence", "draft": "Draft", "sent": "Waiting for the customer",
          "confirmed": "Confirmed by both sides", "change_requested": "Customer asked for changes"}


def _t(text) -> str:
    """Plain text -> safe Paragraph markup."""
    return escape(str(text if text is not None else "")).replace("\n", "<br/>")


def _p(text, style="body") -> Paragraph:
    return Paragraph(_t(text), S[style])


def _when(ts) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return str(ts or "-")


def _hash(h) -> Paragraph:
    h = h or ""
    return Paragraph(f"{h[:32]}<br/>{h[32:]}", S["mono"])


class _Numbered(rl_canvas.Canvas):
    """Canvas that knows the total page count, for 'Page 2 of 5'."""
    label, footer = "", ""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._decorate(total)
            super().showPage()
        super().save()

    def _decorate(self, total):
        self.setStrokeColor(INK); self.setFillColor(INK)
        self.setLineWidth(2.5); self.line(MARGIN, H - 13 * mm, W - MARGIN, H - 13 * mm)
        self.setFont("Sans-Bold", 13); self.drawString(MARGIN, H - 10.2 * mm, "ACCORD")
        self.setFont("Sans-Bold", 8.5); self.drawRightString(W - MARGIN, H - 10 * mm, self.label.upper())
        self.setLineWidth(1); self.line(MARGIN, 13 * mm, W - MARGIN, 13 * mm)
        self.setFont("Sans", 7.2)
        self.drawString(MARGIN, 8.5 * mm, self.footer[:120])
        self.drawRightString(W - MARGIN, 8.5 * mm, f"Page {self._pageNumber} of {total}")
        self.setFont("Sans", 6.8); self.drawString(MARGIN, 5 * mm, "Not legal advice. A record of what the parties agreed. Check stamp duty and validity for your state.")


def _build(story, label, footer) -> bytes:
    buf = BytesIO()

    def canvasmaker(*a, **k):
        c = _Numbered(*a, **k); c.label, c.footer = label, footer
        return c

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm, bottomMargin=20 * mm,
                          title=label, author="Accord")
    frame = Frame(MARGIN, 20 * mm, W - 2 * MARGIN, H - 42 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])
    doc.build(story, canvasmaker=canvasmaker)
    return buf.getvalue()


def _table(rows, widths, header=True, zebra=False) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 1, INK), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), INK))
    if zebra:
        st += [("BACKGROUND", (0, i), (-1, i), SOFT) for i in range(2 if header else 1, len(rows), 2)]
    t.setStyle(TableStyle(st))
    return t


def _heading(text):
    return [Paragraph(_t(text), S["h"]), HRFlowable(width="100%", thickness=2, color=INK, spaceAfter=6)]


def _context(deal_id: str) -> dict:
    d = get_deal(deal_id)
    with db.conn() as c:
        dealer = c.execute("SELECT name, business_name FROM users WHERE id=?", (d.get("dealer_id"),)).fetchone()
        cust = c.execute("SELECT name FROM customers WHERE id=?", (d.get("customer_id"),)).fetchone() if d.get("customer_id") else None
    chain = evidence.get_chain(deal_id)
    return {"deal": d, "terms": d["terms"] or {}, "chain": chain, "ver": proof.verification(deal_id),
            "dealer": dict(dealer) if dealer else {}, "customer": cust["name"] if cust else ""}


def _parties_line(x) -> str:
    names = [p["name"] for p in x["terms"].get("parties", [])]
    biz = x["dealer"].get("business_name") or x["dealer"].get("name") or ""
    return " and ".join(names) if names else f"{biz} and {x['customer']}".strip(" and")


def _footer(x) -> str:
    head = x["chain"][-1]["entry_hash"][:16] if x["chain"] else "none"
    return f"{x['deal']['title'][:48]}  |  ID {x['deal']['id']}  |  trail fingerprint {head}..."


def agreement_pdf(deal_id: str) -> bytes:
    x = _context(deal_id)
    d = x["deal"]
    if not d["agreement"]:
        raise ValueError("No agreement yet")
    story = [_p(d["title"], "title"),
             _p(f"Between {_parties_line(x)}", "muted"),
             _p(f"Status: {STATUS.get(d['status'], d['status'])}", "muted"), Spacer(1, 8),
             HRFlowable(width="100%", thickness=2, color=INK, spaceAfter=10)]
    for i, line in enumerate(d["agreement"].splitlines()):
        t = line.strip()
        if not t:
            story.append(Spacer(1, 3))
        elif t.startswith("- "):
            story.append(Paragraph("&bull;&nbsp;&nbsp;" + _t(t[2:]), S["agr_li"]))
        elif i == 0 or t.isupper() or (t[0].isdigit() and t[1:3] == ". "):
            story.append(Paragraph(_t(t), S["agr_h"]))      # title, caps headings and "1. Heading" lines
        else:
            story.append(Paragraph(_t(t), S["agr"]))

    done = [e for e in x["chain"] if e["kind"] in ("counterparty_confirmed", "counterparty_requested_change")]
    box = []
    if done:
        e = done[-1]
        who = e["meta"].get("name") or "The customer"
        verb = "approved this agreement" if e["kind"] == "counterparty_confirmed" else "asked for a change"
        box = [[Paragraph(f"<b>{_t(who)} {verb}</b><br/>{_t(_when(e['ts']))}", S["body"])],
               [Paragraph("Receipt<br/>" + f"{e['entry_hash'][:32]}<br/>{e['entry_hash'][32:]}", S["mono"])]]
    else:
        box = [[Paragraph("<b>Not confirmed yet</b><br/>This copy was exported before the customer approved it.", S["body"])]]
    t = Table(box, colWidths=[W - 2 * MARGIN]); t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 2, INK), ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                                                                      ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [Spacer(1, 16), KeepTogether([t])]
    return _build(story, "Agreement", _footer(x))


def report_pdf(deal_id: str, audience: str = "dealer") -> bytes:
    x = _context(deal_id)
    d, terms, ver = x["deal"], x["terms"], x["ver"]
    msgs = {m["id"]: m for m in (d["messages"] or [])}
    me_dealer = audience == "dealer"
    cited = set()
    for k, _ in FIELDS:
        cited.update((terms.get(k) or {}).get("source_ids", []))
    for s in terms.get("superseded", []):
        cited.update(s.get("source_ids", []))
    full = (W - 2 * MARGIN)

    story = [_p("Evidence report", "title"), _p(d["title"], "h"),
             _p(f"Between {_parties_line(x)}", "muted"), _p(f"Exported {_when(datetime.now(timezone.utc).isoformat(timespec='seconds'))}", "muted"), Spacer(1, 8)]

    ok = ver["valid"]
    summary = [[Paragraph("<b>Status</b>", S["body"]), _p(STATUS.get(d["status"], d["status"]))],
               [Paragraph("<b>Trail check</b>", S["body"]), _p("INTACT. Every step and every stored file still matches its fingerprint." if ok
                                                           else f"BROKEN. Something was changed after it was recorded (entry {ver.get('broken_at') or 'file'}).")],
               [Paragraph("<b>Entries</b>", S["body"]), _p(f"{len(x['chain'])} steps recorded")],
               [Paragraph("<b>Latest fingerprint</b>", S["body"]), _hash(x["chain"][-1]["entry_hash"] if x["chain"] else "")]]
    t = _table(summary, [38 * mm, full - 38 * mm], header=False)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 1), SOFT if ok else colors.Color(.85, .85, .85)), ("BOX", (0, 0), (-1, -1), 2, INK)]))
    story += [t]

    # terms
    story += _heading("What was agreed")
    rows = [[Paragraph(h, S["th"]) for h in ("Term", "Value", "Source messages")]]
    for k, lab in FIELDS:
        tm = terms.get(k) or {}
        val = (tm.get("value") or "").strip() or "Not agreed in the evidence"
        if k == "price" and tm.get("gst"):
            val += {"included": " (GST included)", "excluded": " (GST extra)"}.get(tm["gst"], "")
        if tm.get("edited"):
            val += f"\nEdited by the dealer. The evidence itself said: {tm.get('extracted_value') or 'nothing'}"
        rows.append([_p(lab), _p(val), _p(", ".join(f"#{i}" for i in tm.get("source_ids", [])) or "-")])
    story.append(_table(rows, [34 * mm, full - 34 * mm - 36 * mm, 36 * mm]))

    sup = terms.get("superseded", [])
    if sup:
        story += _heading("What changed along the way")
        story.append(_table([[Paragraph(h, S["th"]) for h in ("Term", "Was", "Became", "Messages")]] +
                            [[_p(LABEL.get(s["field"], s["field"])), _p(s["old"]), _p(s["new"] + (" (" + s["reason"] + ")" if s.get("reason") else "")), _p(", ".join(f"#{i}" for i in s.get("source_ids", [])))] for s in sup],
                            [32 * mm, (full - 32 * mm - 28 * mm) / 2, (full - 32 * mm - 28 * mm) / 2, 28 * mm]))

    open_pts = [(m["field"], m["why"]) for m in terms.get("missing", [])] + [(a["field"].replace("_", " ").title(), a["issue"]) for a in terms.get("ambiguities", [])]
    if open_pts:
        story += _heading("Not settled yet")
        story.append(_table([[Paragraph(h, S["th"]) for h in ("Point", "Why it matters")]] + [[_p(a), _p(b)] for a, b in open_pts], [50 * mm, full - 50 * mm]))

    # evidence on file
    its = proof.items(deal_id)
    if its:
        story += _heading("Evidence on file")
        rows = [[Paragraph(h, S["th"]) for h in ("Item", "Type", "Added", "SHA-256 fingerprint")]]
        for i in its:
            rows.append([_p(i.get("label") or i["name"]), _p(i["kind"]), _p(_when(i["added"])), _hash(i["sha256"])])
        story.append(_table(rows, [48 * mm, 20 * mm, 34 * mm, full - 102 * mm]))

    # the messages
    ids = sorted(msgs) if me_dealer else sorted(i for i in cited if i in msgs)
    if ids:
        story += _heading("The messages" if me_dealer else "The messages behind each term")
        shown = ids[:400]
        rows = [[Paragraph(h, S["th"]) for h in ("#", "When", "Who", "Message")]]
        for i in shown:
            m = msgs[i]
            rows.append([_p(i, "small"), _p(f"{m.get('date', '')} {m.get('time', '')}".strip(), "small"), _p(m.get("sender", ""), "small"), _p(m.get("text", ""), "small")])
        story.append(_table(rows, [10 * mm, 28 * mm, 26 * mm, full - 64 * mm], zebra=True))
        if len(ids) > len(shown):
            story.append(_p(f"{len(ids) - len(shown)} more messages are in the full evidence bundle.", "muted"))

    # trail
    trail = [e for e in x["chain"] if me_dealer or e["kind"] in CUSTOMER_KINDS]
    story += _heading("Step-by-step trail")
    rows = [[Paragraph(h, S["th"]) for h in ("#", "What happened", "When", "Entry fingerprint")]]
    for e in trail:
        what = KIND.get(e["kind"], e["kind"])
        who = e["meta"].get("name")
        note = e["meta"].get("note")
        label = what + (f" by {who}" if who else "") + (f"\nNote: {note}" if note else "")
        rows.append([_p(e["seq"], "small"), _p(label, "small"), _p(_when(e["ts"]), "small"), _hash(e["entry_hash"])])
    story.append(_table(rows, [9 * mm, 62 * mm, 33 * mm, full - 104 * mm]))

    story += [Spacer(1, 12), KeepTogether(_heading("How to check this") + [
        _p("Each step above stores the SHA-256 of what happened and the fingerprint of the step before it. If any earlier step were changed, "
           "every fingerprint after it would stop matching. Uploading the original chat file in Accord shows whether its fingerprint is in a trail.", "muted")])]
    return _build(story, "Evidence report", _footer(x))
