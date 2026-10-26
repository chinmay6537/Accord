"""PDF downloads: they work, respect who may see what, and a customer's copy leaves out the uncited chat."""
from io import BytesIO

from pypdf import PdfReader

from conftest import add_customer, make_client, make_ticket
from test_accounts import invite_token, prepare_sent_ticket


def text_of(pdf_bytes: bytes) -> str:
    assert pdf_bytes.startswith(b"%PDF")
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf_bytes)).pages)


def linked_customer(dealer, cid):
    cust = make_client("customer")
    assert cust.post(f"/api/join/{invite_token(dealer, cid)}").status_code == 200
    return cust


def test_dealer_pdfs(dealer):
    tid, _ = prepare_sent_ticket(dealer)
    agr = dealer.get(f"/api/deals/{tid}/agreement.pdf")
    assert agr.status_code == 200 and agr.headers["content-type"] == "application/pdf"
    assert "54,000" in text_of(agr.content) and "ACCORD" in text_of(agr.content)
    rep = text_of(dealer.get(f"/api/deals/{tid}/report.pdf").content)
    assert "INTACT" in rep and "Step-by-step trail" in rep
    assert "Haan next week tak kar dunga" in rep          # the dealer's report has the whole chat


def test_customer_report_only_has_cited_messages(dealer):
    tid, cid = prepare_sent_ticket(dealer)
    cust = linked_customer(dealer, cid)
    assert cust.get(f"/api/my/tickets/{tid}/agreement.pdf").status_code == 200
    rep = text_of(cust.get(f"/api/my/tickets/{tid}/report.pdf").content)
    assert "Chalo 54,000 final" in rep                    # cited behind the price
    assert "Haan next week tak kar dunga" not in rep      # not cited, so not shown


def test_pdf_access_rules(dealer):
    tid, cid = prepare_sent_ticket(dealer)
    other_dealer = make_client("dealer", business_name="Other")
    stranger = make_client("customer")
    cust = linked_customer(dealer, cid)
    anon = make_client("customer"); anon.cookies.clear()
    assert other_dealer.get(f"/api/deals/{tid}/report.pdf").status_code == 404
    assert other_dealer.get(f"/api/deals/{tid}/agreement.pdf").status_code == 404
    assert stranger.get(f"/api/my/tickets/{tid}/report.pdf").status_code == 404
    assert stranger.get(f"/api/my/tickets/{tid}/agreement.pdf").status_code == 404
    assert cust.get(f"/api/deals/{tid}/report.pdf").status_code == 403      # customers never get the dealer's copy
    assert anon.get(f"/api/deals/{tid}/report.pdf").status_code == 401


def test_agreement_pdf_needs_an_agreement_and_link_download(dealer):
    tid = make_ticket(dealer)
    assert dealer.get(f"/api/deals/{tid}/agreement.pdf").status_code == 400
    sent, _ = prepare_sent_ticket(dealer)
    token = dealer.get(f"/api/deals/{sent}").json()["token"]
    r = make_client("customer").get(f"/api/c/{token}/agreement.pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
