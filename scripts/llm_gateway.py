"""Run this on the laptop that hosts the model (needs Ollama running).

    pip install fastapi uvicorn httpx
    set GATEWAY_TOKEN=some-long-secret        (Windows)   |   export GATEWAY_TOKEN=some-long-secret
    python scripts/llm_gateway.py

Then expose port 9100 (see LOCAL_LLM.md), and give Accord the URL + token.
Only requests carrying the token are answered, and nothing is stored.
"""
import os

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
TOKEN = os.getenv("GATEWAY_TOKEN", "")

app = FastAPI(title="Accord LLM gateway")


class Req(BaseModel):
    system: str
    user: str
    json: bool = True


def _auth(h: str | None):
    if not TOKEN or h != f"Bearer {TOKEN}":
        raise HTTPException(401, "bad token")


@app.get("/health")
def health(authorization: str | None = Header(None)):
    _auth(authorization)
    return {"ok": True, "model": MODEL}


@app.post("/generate")
def generate(r: Req, authorization: str | None = Header(None)):
    _auth(authorization)
    body = {"model": MODEL, "stream": False, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": r.system}, {"role": "user", "content": r.user}]}
    if r.json:
        body["format"] = "json"
    try:
        o = httpx.post(OLLAMA + "/api/chat", json=body, timeout=300)
        o.raise_for_status()
    except Exception as e:
        raise HTTPException(502, f"Ollama not reachable: {e}")
    return {"text": o.json()["message"]["content"], "model": MODEL}


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set GATEWAY_TOKEN first (any long random string).")
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("GATEWAY_PORT", "9100")))
