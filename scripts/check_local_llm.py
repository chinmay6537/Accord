"""Run the sample chat through the local model and compare it with what we know is right.

    LLM_PROVIDER=local python scripts/check_local_llm.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.extract import _guard, extract_local, extract_rules  # noqa: E402
from app.parser import parse_chat  # noqa: E402

msgs = parse_chat((Path(__file__).resolve().parent.parent / "samples" / "wedding_cards_hinglish.txt").read_text(encoding="utf-8"))
rules = extract_rules(msgs)
t0 = time.time()
try:
    raw = extract_local(msgs)
except Exception as e:
    print("FAILED: could not reach the local model:", repr(e))
    print("Is Ollama running? Try:  ollama serve   and   ollama list  (should show accord-reader)")
    sys.exit(1)
secs = time.time() - t0
checked = _guard(dict(raw), rules, msgs)
print(f"Model answered in {secs:.0f}s using {raw['engine']}\n")
for k in ("price", "scope", "delivery", "payment_terms"):
    print(f"{k:14} model: {raw[k]['value']!r:50} final: {checked[k]['value']!r}")
print("\nSummary:", checked["summary"])
print("\nCorrections made by the safety check:", checked.get("engine_note", "none, the model got it right"))
ok = checked["price"]["value"] == "₹54,000"
print("\nPASS" if ok else "\nCHECK: price is not 54,000")
sys.exit(0 if ok else 1)
