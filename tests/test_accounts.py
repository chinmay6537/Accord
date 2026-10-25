from fastapi.testclient import TestClient

from app.main import app
from conftest import SAMPLE, add_customer, make_client, make_ticket


def invite_token(dealer, cid):
    return dealer.get(f"/api/customers/{cid}").json()["invite_path"].rsplit("/", 1)[1]


def prepare_sent_ticket(dealer, cid=None):
    """A ticket taken all the way to 'sent', so the customer can see it."""
    cid = cid or add_customer(dealer)["id"]
    tid = make_ticket(dealer, cid)
    dealer.post(f"/api/cases/{tid}/items", data={"kind": "chat", "text": SAMPLE})
    dealer.post(f"/api/cases/{tid}/analyze", json={})
    dealer.post(f"/api/deals/{tid}/agreement", json={"tone": "friendly"})
    assert dealer.post(f"/api/deals/{tid}/send").status_code == 200
    return tid, cid


# ------------------------------------------------------------------ accounts

def test_signup_login_logout_and_roles():
    c = TestClient(app)
    assert c.get("/api/auth/me").status_code == 401
    bad = {"name": "A", "email": "not-an-email", "password": "password123", "role": "dealer"}
    assert c.post("/api/auth/signup", json=bad).status_code == 400
    assert c.post("/api/auth/signup", json={**bad, "email": "a@x.com", "password": "short"}).status_code == 400
    assert c.post("/api/auth/signup", json={**bad, "email": "a@x.com", "role": "admin"}).status_code == 400
    r = c.post("/api/auth/signup", json={**bad, "email": "roles@x.com"})
    assert r.status_code == 200 and r.json()["home"] == "/dealer"
    assert c.get("/api/auth/me").json()["role"] == "dealer"
    assert c.post("/api/auth/signup", json={**bad, "email": "ROLES@x.com"}).status_code == 409   # same email
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "roles@x.com", "password": "wrongwrong"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "roles@x.com", "password": "password123"}).status_code == 200


def test_pages_redirect_by_login_and_role(dealer, customer):
    anon = TestClient(app, follow_redirects=False)
    assert anon.get("/dealer").headers["location"] == "/login"
    assert anon.get("/").status_code == 200                                  # landing page for visitors
    assert dealer.get("/dealer", follow_redirects=False).status_code == 200
    assert dealer.get("/customer", follow_redirects=False).headers["location"] == "/dealer"
    assert customer.get("/dealer", follow_redirects=False).headers["location"] == "/customer"
    assert dealer.get("/", follow_redirects=False).headers["location"] == "/dealer"


def test_api_needs_the_right_role(dealer, customer):
    anon = TestClient(app)
    assert anon.get("/api/tickets").status_code == 401
    assert customer.get("/api/tickets").status_code == 403
    assert customer.post("/api/customers", json={"name": "x"}).status_code == 403
    assert dealer.get("/api/my/tickets").status_code == 403


# ------------------------------------------------------------------ dealer data

def test_dealers_cannot_see_each_others_data():
    a, b = make_client("dealer"), make_client("dealer")
    cid = add_customer(a)["id"]
    tid = make_ticket(a, cid)
    for url in (f"/api/tickets/{tid}", f"/api/deals/{tid}", f"/api/cases/{tid}/items", f"/api/customers/{cid}"):
        assert b.get(url).status_code == 404, url
    assert b.post(f"/api/cases/{tid}/items", data={"kind": "note", "text": "hi"}).status_code == 404
    assert b.post(f"/api/tickets", json={"title": "t", "customer_id": cid, "description": "d"}).status_code == 404
    assert b.get("/api/tickets").json() == [] and b.get("/api/customers").json() == []


def test_segments_customers_and_ticket_filters(dealer):
    seg = dealer.post("/api/segments", json={"name": "Wedding printers"}).json()[0]
    assert dealer.post("/api/segments", json={"name": "Wedding printers"}).status_code == 409
    c1 = add_customer(dealer, name="Ravi", segment_id=seg["id"])
    c2 = add_customer(dealer, name="Anita", phone="9000000001")
    assert c1["segment_name"] == "Wedding printers"
    t1, t2 = make_ticket(dealer, c1["id"], title="Cards"), make_ticket(dealer, c2["id"], title="Banners")
    assert [t["id"] for t in dealer.get(f"/api/tickets?segment_id={seg['id']}").json()] == [t1]
    assert [t["id"] for t in dealer.get(f"/api/tickets?customer_id={c2['id']}").json()] == [t2]
    assert [t["id"] for t in dealer.get("/api/tickets?q=banner").json()] == [t2]
    assert len(dealer.get("/api/tickets?status=collecting").json()) == 2
    assert dealer.get("/api/tickets?status=nonsense").status_code == 400
    assert [c["name"] for c in dealer.get("/api/customers?q=anit").json()] == ["Anita"]
    assert dealer.delete(f"/api/customers/{c1['id']}").status_code == 409          # has a ticket
    dealer.delete(f"/api/segments/{seg['id']}")
    assert dealer.get(f"/api/customers/{c1['id']}").json()["segment_id"] is None   # customer survives


def test_new_ticket_validation_and_fields(dealer):
    cid = add_customer(dealer)["id"]
    ok = {"title": "T", "customer_id": cid, "description": "D"}
    assert dealer.post("/api/tickets", json={**ok, "title": "  "}).status_code == 400
    assert dealer.post("/api/tickets", json={**ok, "description": ""}).status_code == 400
    assert dealer.post("/api/tickets", json={**ok, "deal_type": "magic"}).status_code == 400
    assert dealer.post("/api/tickets", json={**ok, "due_date": "31/12/2026"}).status_code == 400
    assert dealer.post("/api/tickets", json={**ok, "est_value": 1000, "advance": 2000}).status_code == 400
    r = dealer.post("/api/tickets", json={**ok, "deal_type": "repair", "est_value": 54000, "advance": 20000,
                                          "due_date": "2026-10-25", "gst": "extra", "priority": "urgent",
                                          "channel": "mixed", "notes": "only talk to Ravi"}).json()
    assert r["status"] == "collecting" and r["customer"]["name"] == "Suresh" and r["advance"] == 20000
    ov = dealer.get("/api/dealer/overview").json()
    assert ov["counts"]["collecting"] == 1 and ov["customers"] == 1


def test_sent_ticket_details_are_locked(dealer):
    tid, cid = prepare_sent_ticket(dealer)
    r = dealer.put(f"/api/tickets/{tid}", json={"title": "x", "customer_id": cid, "description": "y"})
    assert r.status_code == 409


# ------------------------------------------------------------------ customer portal

def test_customer_sees_only_sent_tickets_for_their_own_record(dealer):
    cust, other = make_client("customer"), make_client("customer")
    cid = add_customer(dealer)["id"]
    assert cust.post(f"/api/join/{invite_token(dealer, cid)}").status_code == 200
    draft = make_ticket(dealer, cid, title="Still a draft")
    assert cust.get("/api/my/tickets").json() == []               # not sent yet
    sent, _ = prepare_sent_ticket(dealer, cid)
    mine = cust.get("/api/my/tickets").json()
    assert [t["id"] for t in mine] == [sent] and mine[0]["dealer_business"] == "Test Traders"
    assert other.get("/api/my/tickets").json() == []
    assert other.get(f"/api/my/tickets/{sent}").status_code == 404
    assert cust.get(f"/api/my/tickets/{draft}").status_code == 404
    detail = cust.get(f"/api/my/tickets/{sent}").json()
    assert "agreement" in detail and "notes" not in detail         # internal notes never reach the customer


def test_signup_through_invite_link_connects_the_account(dealer):
    cid = add_customer(dealer)["id"]
    tok = invite_token(dealer, cid)
    anon = TestClient(app)
    info = anon.get(f"/api/join/{tok}").json()
    assert info["customer_name"] == "Suresh" and info["business_name"] == "Test Traders"
    r = anon.post("/api/auth/signup", json={"name": "Suresh K", "email": "suresh.k@example.com", "password": "password123",
                                            "role": "customer", "invite_token": tok})
    assert r.status_code == 200
    assert dealer.get(f"/api/customers/{cid}").json()["has_account"] is True
    assert anon.get(f"/api/join/{tok}").status_code == 404                     # one use only
    assert TestClient(app).post("/api/auth/signup", json={"name": "B", "email": "b2@example.com", "password": "password123",
                                                          "role": "customer", "invite_token": tok}).status_code == 409


def test_bad_invites_are_rejected(dealer):
    anon = TestClient(app)
    base = {"name": "X", "email": "x1@example.com", "password": "password123"}
    assert anon.post("/api/auth/signup", json={**base, "role": "customer", "invite_token": "nope"}).status_code == 400
    tok = invite_token(dealer, add_customer(dealer)["id"])
    assert anon.post("/api/auth/signup", json={**base, "role": "dealer", "invite_token": tok}).status_code == 400
    assert dealer.post(f"/api/join/{tok}").status_code == 403                  # dealers can't claim
    assert anon.get("/api/auth/me").status_code == 401                         # failed signups leave no session


def test_matching_email_or_phone_does_NOT_link_accounts(dealer):
    """Regression: contact details are unverified, so they must never grant access to a dealer's tickets."""
    cid = add_customer(dealer, email="victim@example.com", phone="9876543210")["id"]
    tid, _ = prepare_sent_ticket(dealer, cid)
    attacker = TestClient(app)
    attacker.post("/api/auth/signup", json={"name": "Eve", "email": "victim@example.com", "password": "password123",
                                            "role": "customer", "phone": "98765 43210"})
    assert attacker.get("/api/my/tickets").json() == []
    assert attacker.get(f"/api/my/tickets/{tid}").status_code == 404
    assert dealer.get(f"/api/customers/{cid}").json()["has_account"] is False


FIELDS = ["scope", "price", "delivery", "payment_terms"]


def joined_customer(dealer):
    cust = make_client("customer")
    cid = add_customer(dealer)["id"]
    cust.post(f"/api/join/{invite_token(dealer, cid)}")
    tid, _ = prepare_sent_ticket(dealer, cid)
    return cust, tid


def check_all(cust, tid, result="match"):
    for f in FIELDS:
        assert cust.put(f"/api/my/tickets/{tid}/checks/{f}", json={"result": result, "note": f"{f} note"}).status_code == 200


def test_customer_review_shows_every_term_with_its_references(dealer):
    cust, tid = joined_customer(dealer)
    r = cust.get(f"/api/my/tickets/{tid}").json()
    assert r["dealer_business"] == "Test Traders" and r["dealer_email"].endswith("@example.com")
    by = {t["key"]: t for t in r["terms"]}
    assert by["price"]["value"] == "₹54,000" and by["price"]["gst"] == "excluded"
    assert any("54,000" in ref["text"] for ref in by["price"]["refs"])            # the message behind the price
    assert by["delivery"]["refs"] and by["scope"]["refs"] and by["payment_terms"]["refs"]
    assert [(h["old"], h["new"]) for h in by["price"]["history"]][-1] == ("₹46,500", "₹54,000")   # how it changed
    assert {o["field"] for o in r["open_points"]} >= {"Cancellation or refund", "Defects or warranty"}
    assert r["evidence"] and "sha256" in r["evidence"][0]
    assert r["proof"]["valid"] and r["proof"]["entries"] >= 4
    assert {"agreement", "trail", "checks"} <= set(r)
    assert "notes" not in r and "token" not in r                                  # nothing private leaks


def test_review_flags_terms_the_dealer_edited_after_reading_the_evidence(dealer):
    cid = add_customer(dealer)["id"]
    cust = make_client("customer")
    cust.post(f"/api/join/{invite_token(dealer, cid)}")
    tid = make_ticket(dealer, cid)
    dealer.post(f"/api/cases/{tid}/items", data={"kind": "chat", "text": SAMPLE})
    t = dealer.post(f"/api/cases/{tid}/analyze", json={}).json()["terms"]
    dealer.put(f"/api/deals/{tid}/terms", json={"scope": t["scope"]["value"], "price": "₹40,000",
                                                "delivery": t["delivery"]["value"], "payment_terms": t["payment_terms"]["value"]})
    dealer.post(f"/api/deals/{tid}/agreement", json={"tone": "friendly"})
    dealer.post(f"/api/deals/{tid}/send")
    price = {x["key"]: x for x in cust.get(f"/api/my/tickets/{tid}").json()["terms"]}["price"]
    assert price["value"] == "₹40,000" and price["edited"] and price["extracted_value"] == "₹54,000"
    other = {x["key"]: x for x in cust.get(f"/api/my/tickets/{tid}").json()["terms"]}["delivery"]
    assert not other["edited"]


def test_customer_cannot_create_anything_only_review(dealer):
    cust, tid = joined_customer(dealer)
    assert cust.post("/api/tickets", json={"title": "x", "customer_id": 1, "description": "y"}).status_code == 403
    assert cust.post("/api/customers", json={"name": "x"}).status_code == 403
    assert cust.put(f"/api/tickets/{tid}", json={"title": "x", "customer_id": 1, "description": "y"}).status_code == 403
    assert cust.post(f"/api/cases/{tid}/items", data={"kind": "note", "text": "forged"}).status_code == 403


def test_cannot_approve_until_every_term_is_checked_as_matching(dealer):
    cust, tid = joined_customer(dealer)
    r = cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "agree"})
    assert r.status_code == 400 and "Price" in r.json()["detail"]
    for f in FIELDS[:-1]:
        cust.put(f"/api/my/tickets/{tid}/checks/{f}", json={"result": "match"})
    assert cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "agree"}).status_code == 400   # one left
    cust.put(f"/api/my/tickets/{tid}/checks/payment_terms", json={"result": "mismatch", "note": "I paid 25k not 20k"})
    assert cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "agree"}).status_code == 400   # mismatch blocks
    cust.put(f"/api/my/tickets/{tid}/checks/payment_terms", json={"result": "match"})
    r = cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "agree"}).json()
    assert r["status"] == "confirmed" and r["receipt"]
    assert cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "agree"}).status_code == 409   # only once
    assert cust.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "mismatch"}).status_code == 409   # locked now
    d = dealer.get(f"/api/deals/{tid}").json()
    last = d["chain"][-1]
    assert d["status"] == "confirmed" and last["kind"] == "counterparty_confirmed" and last["meta"]["via"] == "account"
    assert last["meta"]["checks"] == {f: "match" for f in FIELDS}               # the proof that they verified each term
    assert d["verification"]["valid"]


def test_mismatch_turns_into_a_change_request_with_their_notes(dealer):
    cust, tid = joined_customer(dealer)
    assert cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "change"}).status_code == 400   # nothing to say yet
    cust.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "mismatch", "note": "We agreed 52,000"})
    r = cust.post(f"/api/my/tickets/{tid}/respond", json={"action": "change", "note": "Please fix"}).json()
    assert r["status"] == "change_requested"
    last = dealer.get(f"/api/deals/{tid}").json()["chain"][-1]
    assert "Please fix" in last["meta"]["note"] and "Price: We agreed 52,000" in last["meta"]["note"]
    assert dealer.get(f"/api/tickets/{tid}").json()["status"] == "change_requested"


def test_check_endpoint_validates_and_is_private(dealer):
    cust, tid = joined_customer(dealer)
    stranger = make_client("customer")
    assert cust.put(f"/api/my/tickets/{tid}/checks/colour", json={"result": "match"}).status_code == 404
    assert cust.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "maybe"}).status_code == 400
    assert stranger.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "match"}).status_code == 404
    assert dealer.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "match"}).status_code == 403
    cust.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "match"})
    assert cust.get(f"/api/my/tickets/{tid}").json()["checks"]["price"]["result"] == "match"
    cust.put(f"/api/my/tickets/{tid}/checks/price", json={"result": "clear"})
    assert "price" not in cust.get(f"/api/my/tickets/{tid}").json()["checks"]


# ------------------------------------------------------------------ chat and comments

def test_thread_between_dealer_and_customer(dealer):
    cust, stranger, other_dealer = make_client("customer"), make_client("customer"), make_client("dealer")
    cid = add_customer(dealer)["id"]
    cust.post(f"/api/join/{invite_token(dealer, cid)}")
    early = make_ticket(dealer, cid)
    assert dealer.get(f"/api/tickets/{early}/thread").status_code == 404      # not sent yet: no thread
    tid, _ = prepare_sent_ticket(dealer, cid)

    assert cust.post(f"/api/tickets/{tid}/thread", json={"body": "Can delivery be 24th?", "kind": "comment"}).status_code == 200
    assert dealer.post(f"/api/tickets/{tid}/thread", json={"body": "Let me check.", "kind": "chat"}).status_code == 200
    assert cust.post(f"/api/tickets/{tid}/thread", json={"body": "   "}).status_code == 400
    assert cust.post(f"/api/tickets/{tid}/thread", json={"body": "x", "kind": "shout"}).status_code == 400

    seen_by_dealer = dealer.get(f"/api/tickets/{tid}/thread").json()
    assert [m["sender_role"] for m in seen_by_dealer] == ["customer", "dealer"]
    assert [m["mine"] for m in seen_by_dealer] == [False, True]
    after = cust.get(f"/api/tickets/{tid}/thread?after={seen_by_dealer[0]['id']}").json()
    assert [m["body"] for m in after] == ["Let me check."]

    assert stranger.get(f"/api/tickets/{tid}/thread").status_code == 404
    assert other_dealer.get(f"/api/tickets/{tid}/thread").status_code == 404
    assert stranger.post(f"/api/tickets/{tid}/thread", json={"body": "hi"}).status_code == 404

    chain = dealer.get(f"/api/deals/{tid}").json()["chain"]
    comments = [e for e in chain if e["kind"] == "comment_added"]
    assert len(comments) == 1 and comments[0]["meta"]["role"] == "customer"   # comments are evidence, chat is not
    assert dealer.get(f"/api/deals/{tid}").json()["verification"]["valid"]


def test_public_demo_needs_no_login_and_saves_nothing():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    chat = open("samples/wedding_cards_hinglish.txt", encoding="utf-8").read()
    r = c.post("/api/demo", json={"text": chat})
    assert r.status_code == 200
    d = r.json()
    assert any(t["label"] == "Price" and t["value"] for t in d["terms"]) and d["agreement"]
    assert c.post("/api/demo", json={"text": "hello"}).status_code == 400
    assert c.post("/api/demo", json={"text": "x" * 9000}).status_code == 400
    assert c.get("/").status_code == 200   # landing is public when logged out
