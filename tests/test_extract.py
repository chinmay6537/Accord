import json
import threading

import httpx
import uvicorn
from fastapi import FastAPI

from app.extract import extract_rules, extract_terms, _guard
from app.parser import parse_chat

CHAT = open("samples/wedding_cards_hinglish.txt").read()


def msgs():
    return parse_chat(CHAT)


def test_final_price_follows_quantity_change():
    t = extract_rules(msgs())
    assert t["price"]["value"] == "₹54,000"
    assert t["scope"]["value"].startswith("600 cards")
    assert "46,500 was for 500 cards" in t["summary"]
    assert any(s.get("reason") for s in t["superseded"] if s["field"] == "price")


def test_advance_is_not_the_price():
    t = extract_rules(msgs())
    assert "20,000" in t["payment_terms"]["value"]


def test_unaccepted_later_quote_does_not_win():
    t = extract_rules(parse_chat(
        "12/10/2026, 10:00 am - A: 500 cards 40,000 total\n"
        "12/10/2026, 10:05 am - B: Theek hai 40,000 done\n"
        "12/10/2026, 10:10 am - A: Actually 45,000 lagega\n"))
    assert t["price"]["value"] == "₹40,000"
    assert any("45,000" in a["issue"] for a in t["ambiguities"])


def test_guard_fixes_made_up_price():
    rules = extract_rules(msgs())
    bad = {"engine": "local:x", "summary": "", "parties": [], "ambiguities": [], "missing": [], "superseded": [],
           "scope": {"value": "", "source_ids": [99]}, "price": {"value": "₹46,000", "gst": "?", "source_ids": [99]},
           "delivery": {"value": "", "source_ids": []}, "payment_terms": {"value": "", "source_ids": []}}
    out = _guard(bad, rules, msgs())
    assert out["price"]["value"] == "₹54,000" and out["engine_note"] and out["summary"]


def test_local_llm_end_to_end(monkeypatch):
    fake = FastAPI()
    calls = []

    @fake.post("/generate")
    def gen(body: dict):
        calls.append(body)
        return {"model": "fake", "text": json.dumps({"summary": "ok", "price": {"value": "₹46,000", "gst": "excluded", "source_ids": [5]}})}

    srv = uvicorn.Server(uvicorn.Config(fake, port=9187, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    while not srv.started:
        pass
    monkeypatch.setenv("LOCAL_LLM_URL", "http://127.0.0.1:9187")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t = extract_terms(msgs())
    srv.should_exit = True
    assert calls and t["engine"] == "local:fake"
    assert t["price"]["value"] == "₹54,000"          # model's wrong price corrected from the chat


def test_local_down_falls_back(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT", "2")
    t = extract_terms(msgs())
    assert t["engine"] == "rules" and "could not be reached" in t["engine_note"]


def test_local_ollama_on_same_machine(monkeypatch):
    fake = FastAPI()
    seen = {}

    @fake.post("/api/chat")
    def chat(body: dict):
        seen.update(body)
        return {"message": {"content": json.dumps({"summary": "", "price": {"value": "₹54,000", "gst": "excluded", "source_ids": [12]}})}}

    srv = uvicorn.Server(uvicorn.Config(fake, port=9188, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    while not srv.started:
        pass
    monkeypatch.setattr("app.extract.DEFAULT_OLLAMA", "http://127.0.0.1:9188")
    monkeypatch.delenv("LOCAL_LLM_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "local")
    t = extract_terms(msgs())
    srv.should_exit = True
    assert t["engine"] == "local:accord-reader" and t["price"]["value"] == "₹54,000"
    assert seen["format"]["type"] == "object" and len(seen["messages"]) == 4   # schema + worked example are sent
