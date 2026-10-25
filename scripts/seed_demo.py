"""Create a ready-made demo so you can log in as BOTH sides without clicking through setup.

    python scripts/seed_demo.py

Makes (once; safe to run again):
    dealer   demo.dealer@handshake.test    password: demo12345
    customer demo.customer@handshake.test  password: demo12345
and one ticket the dealer already sent to the customer, built from the sample chat.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PW = "demo12345"
DEALER, CUSTOMER = "demo.dealer@handshake.test", "demo.customer@handshake.test"
chat = (Path(__file__).resolve().parent.parent / "samples" / "wedding_cards_hinglish.txt").read_text(encoding="utf-8")

dealer = TestClient(app)
r = dealer.post("/api/auth/signup", json={"name": "Ravi Kumar", "email": DEALER, "password": PW, "role": "dealer",
                                          "business_name": "Ravi Printers", "phone": "9000011111"})
if r.status_code == 409:
    print("Demo accounts already exist. Log in with the details below.")
else:
    r.raise_for_status()
    cust = dealer.post("/api/customers", json={"name": "Suresh Gowda", "phone": "9876543210"}).json()
    invite = dealer.get(f"/api/customers/{cust['id']}").json()["invite_path"].split("/")[-1]
    tid = dealer.post("/api/tickets", json={"title": "Wedding cards for Suresh", "customer_id": cust["id"],
                                            "description": "600 wedding cards, 4-colour print with gold foil"}).json()["id"]
    dealer.post(f"/api/cases/{tid}/items", data={"kind": "chat", "text": chat}).raise_for_status()
    dealer.post(f"/api/cases/{tid}/analyze", json={}).raise_for_status()
    dealer.post(f"/api/deals/{tid}/agreement", json={"tone": "friendly"}).raise_for_status()
    dealer.post(f"/api/deals/{tid}/send").raise_for_status()
    TestClient(app).post("/api/auth/signup", json={"name": "Suresh Gowda", "email": CUSTOMER, "password": PW,
                                                   "role": "customer", "invite_token": invite}).raise_for_status()
    print("Created the demo dealer, customer and one sent ticket.")

print(f"\n  Dealer    {DEALER}   /  {PW}\n  Customer  {CUSTOMER}  /  {PW}\n")
