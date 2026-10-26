"""PDF downloads. Same access rules as the rest of the app:
dealers get their own tickets, customers get requests sent to them (cited messages only),
and the private confirmation link can download the agreement it shows."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from . import db, pdf
from .auth import need_customer, need_dealer
from .common import dealer_deal
from .routes_customer import _mine

router = APIRouter(tags=["export"])


def _pdf(data: bytes, name: str) -> Response:
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _agreement(deal_id: str) -> Response:
    try:
        return _pdf(pdf.agreement_pdf(deal_id), f"accord-agreement-{deal_id}.pdf")
    except ValueError:
        raise HTTPException(400, "Generate the agreement first")


@router.get("/api/deals/{deal_id}/agreement.pdf")
def dealer_agreement(deal_id: str, user: dict = Depends(need_dealer)):
    dealer_deal(deal_id, user)
    return _agreement(deal_id)


@router.get("/api/deals/{deal_id}/report.pdf")
def dealer_report(deal_id: str, user: dict = Depends(need_dealer)):
    dealer_deal(deal_id, user)
    return _pdf(pdf.report_pdf(deal_id, "dealer"), f"accord-report-{deal_id}.pdf")


@router.get("/api/my/tickets/{deal_id}/agreement.pdf")
def customer_agreement(deal_id: str, user: dict = Depends(need_customer)):
    _mine(deal_id, user)
    return _agreement(deal_id)


@router.get("/api/my/tickets/{deal_id}/report.pdf")
def customer_report(deal_id: str, user: dict = Depends(need_customer)):
    _mine(deal_id, user)
    return _pdf(pdf.report_pdf(deal_id, "customer"), f"accord-report-{deal_id}.pdf")


@router.get("/api/c/{token}/agreement.pdf")
def link_agreement(token: str):
    with db.conn() as c:
        r = c.execute("SELECT id, status FROM deals WHERE token=?", (token,)).fetchone()
    if not r or r["status"] in ("draft", "collecting"):
        raise HTTPException(404, "This agreement is not ready yet")
    return _agreement(r["id"])
