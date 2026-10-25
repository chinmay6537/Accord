import io, zipfile
from conftest import SAMPLE, make_ticket


def new_case(c):
    return make_ticket(c)


def post_items(c, cid, **kw):
    r = c.post(f"/api/cases/{cid}/items", **kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_empty_case_is_not_ready(dealer):
    c = dealer
    cid = new_case(c)
    r = c.get(f"/api/cases/{cid}/items").json()
    assert r["items"] == [] and not r["readiness"]["can_analyze"]
    assert c.post(f"/api/cases/{cid}/analyze", json={}).status_code == 400


def test_chat_file_and_note_merge_by_time(dealer):
    c = dealer
    cid = new_case(c)
    r = post_items(c, cid, files=[("files", ("chat.txt", SAMPLE.encode(), "text/plain"))])
    assert r["items"][0]["kind"] == "chat" and r["items"][0]["message_count"] == 16
    # a call note made AFTER the chat that changes the price
    r = post_items(c, cid, data={"kind": "note", "label": "Phone call", "speaker": "Suresh",
                              "occurred_at": "2026-10-14T18:00",
                              "text": "Final price is 52,000 rupees, delivery 25 Oct stays."})
    assert [i["kind"] for i in r["items"]] == ["chat", "note"]
    d = c.post(f"/api/cases/{cid}/analyze", json={"title": "Cards"}).json()
    assert d["title"] == "Cards" and d["messages"][-1]["kind"] == "note"      # sorted to the end by date
    assert d["messages"][-1]["sender"] == "Suresh"
    assert [p["name"] for p in d["terms"]["parties"]] == ["Suresh", "Ravi"]
    assert d["verification"]["valid"]


def test_voice_note_needs_text_then_typed_then_ignored_when_removed(dealer):
    c = dealer
    cid = new_case(c)
    post_items(c, cid, files=[("files", ("chat.txt", SAMPLE.encode(), "text/plain"))])
    r = post_items(c, cid, files=[("files", ("PTT-1.opus", b"OggS-not-real-audio", "audio/ogg"))])
    voice = [i for i in r["items"] if i["kind"] == "voice"][0]
    assert voice["text_status"] == "needs_text" and voice["editable"]
    assert any("no text yet" in w for w in r["readiness"]["warnings"])

    r = c.put(f"/api/cases/{cid}/items/{voice['id']}",
              json={"text": "Bhai delivery 24 Oct kar dunga", "speaker": "Suresh", "occurred_at": "2026-10-20T10:00"}).json()
    voice = [i for i in r["items"] if i["id"] == voice["id"]][0]
    assert voice["text_status"] == "typed" and voice["speaker"] == "Suresh"

    d = c.post(f"/api/cases/{cid}/analyze", json={}).json()
    assert d["terms"]["delivery"]["value"]          # voice text was part of the analysis
    assert any(m["kind"] == "voice" for m in d["messages"])
    kinds = [e["kind"] for e in d["chain"]]
    assert "evidence_edited" in kinds and d["verification"]["valid"]


def test_remove_keeps_trail_and_file(dealer):
    c = dealer
    cid = new_case(c)
    r = post_items(c, cid, files=[("files", ("a.txt", SAMPLE.encode(), "text/plain"))])
    iid = r["items"][0]["id"]
    r = c.delete(f"/api/cases/{cid}/items/{iid}").json()
    assert r["items"] == [] and not r["readiness"]["can_analyze"]
    chain = c.get(f"/api/deals/{cid}").json()["chain"]
    assert [e["kind"] for e in chain] == ["evidence_added", "evidence_removed"]
    assert c.get(f"/api/deals/{cid}").json()["verification"]["valid"]
    assert c.get(f"/api/cases/{cid}/items/{iid}/file").status_code == 200   # original still stored


def test_whatsapp_zip_unpacks_into_items(dealer):
    c = dealer
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("WhatsApp Chat with Suresh.txt", SAMPLE)
        z.writestr("PTT-20261013-WA0001.opus", b"fake-opus")
        z.writestr("IMG-20261013-WA0002.jpg", b"\xff\xd8fake")
        z.writestr("__MACOSX/junk", b"x")
    r = post_items(c, new_case(c), files=[("files", ("export.zip", buf.getvalue(), "application/zip"))])
    assert sorted(i["kind"] for i in r["items"]) == ["chat", "image", "voice"]


def test_stored_file_tamper_is_caught(dealer):
    c = dealer
    cid = new_case(c)
    post_items(c, cid, files=[("files", ("chat.txt", SAMPLE.encode(), "text/plain"))])
    c.post(f"/api/cases/{cid}/analyze", json={})
    assert c.get(f"/api/deals/{cid}").json()["verification"]["valid"]
    from app.main import _items
    open(_items(cid)[0]["path"], "ab").write(b"\nRavi: I agreed to pay 1 rupee")
    v = c.get(f"/api/deals/{cid}").json()["verification"]
    assert not v["valid"] and v["bad_files"]


def test_sent_deal_is_locked_and_bad_input_rejected(dealer):
    c = dealer
    cid = new_case(c)
    assert c.post(f"/api/cases/{cid}/items", data={}).status_code == 400
    post_items(c, cid, files=[("files", ("chat.txt", SAMPLE.encode(), "text/plain"))])
    c.post(f"/api/cases/{cid}/analyze", json={})
    c.post(f"/api/deals/{cid}/agreement", json={"tone": "friendly"})
    c.post(f"/api/deals/{cid}/send")
    r = c.post(f"/api/cases/{cid}/items", data={"kind": "note", "text": "late addition"})
    assert r.status_code == 409


def test_verify_file_matches_raw_upload(dealer):
    c = dealer
    cid = new_case(c)
    post_items(c, cid, files=[("files", ("chat.txt", SAMPLE.encode(), "text/plain"))])
    ok = c.post("/api/verify-file", files={"file": ("x.txt", SAMPLE.encode())}).json()
    assert ok["ok"] and any(m["meta"]["name"] == "chat.txt" for m in ok["matches"])
    assert not c.post("/api/verify-file", files={"file": ("x.txt", b"changed")}).json()["ok"]
