from conftest import SAMPLE, add_customer, make_client, make_ticket


def test_full_flow(dealer):
    c = dealer
    d = c.post("/api/deals", data={"title": "Wedding cards", "chat_text": SAMPLE}).json()
    assert len(d["messages"]) == 16
    t = d["terms"]
    assert t["price"]["value"] == "₹54,000"
    assert t["price"]["gst"] == "excluded"
    assert "25" in t["delivery"]["value"]
    assert any(s["field"] == "price" for s in t["superseded"])
    assert d["verification"]["valid"]

    d = c.put(f"/api/deals/{d['id']}/terms", json={
        "scope": "600 wedding cards", "price": t["price"]["value"],
        "delivery": t["delivery"]["value"], "payment_terms": t["payment_terms"]["value"]}).json()
    d = c.post(f"/api/deals/{d['id']}/agreement", json={"tone": "friendly"}).json()
    assert "600 wedding cards" in d["agreement"]
    s = c.post(f"/api/deals/{d['id']}/send").json()
    token = s["confirm_url"].rsplit("/", 1)[1]

    other = make_client("customer")           # magic link needs no account at all
    other.cookies.clear()
    otp = other.post(f"/api/c/{token}/otp", json={"phone": "9999999999"}).json()["demo_otp"]
    bad = other.post(f"/api/c/{token}/respond", json={"name": "Suresh", "otp": "000000x", "action": "agree"})
    assert bad.status_code == 400
    ok = other.post(f"/api/c/{token}/respond", json={"name": "Suresh", "otp": otp, "action": "agree"}).json()
    assert ok["status"] == "confirmed"

    d = c.get(f"/api/deals/{d['id']}").json()
    assert d["verification"]["valid"] and d["status"] == "confirmed"
    assert [e["kind"] for e in d["chain"]][-1] == "counterparty_confirmed"

    h = c.post("/api/verify-file", files={"file": ("chat.txt", SAMPLE.encode())}).json()
    assert h["ok"]

    c.post(f"/api/deals/{d['id']}/demo-tamper")
    d = c.get(f"/api/deals/{d['id']}").json()
    assert not d["verification"]["valid"] and d["verification"]["broken_at"] == 2
