import itertools
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmp, "t.db")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp, "up")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(k, None)

import pytest
from fastapi.testclient import TestClient

from app.main import app

_n = itertools.count()
SAMPLE = open("samples/wedding_cards_hinglish.txt", encoding="utf-8").read()


def make_client(role="dealer", **extra):
    """A fresh browser (own cookie jar) signed up and logged in as a new user."""
    c = TestClient(app)
    n = next(_n)
    r = c.post("/api/auth/signup", json={"name": f"{role.title()} {n}", "email": f"{role}{n}@example.com",
                                         "password": "password123", "role": role, **extra})
    assert r.status_code == 200, r.text
    c.user = r.json()
    return c


@pytest.fixture
def dealer():
    return make_client("dealer", business_name="Test Traders")


@pytest.fixture
def customer():
    return make_client("customer", phone="98765 43210")


def add_customer(dealer, **kw):
    r = dealer.post("/api/customers", json={"name": "Suresh", "phone": "9876543210", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def make_ticket(dealer, customer_id=None, **kw):
    cid = customer_id or add_customer(dealer)["id"]
    body = {"title": "Wedding cards", "customer_id": cid, "description": "600 wedding cards, gold foil", **kw}
    r = dealer.post("/api/tickets", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]
