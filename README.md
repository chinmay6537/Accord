# Handshake

Turn a WhatsApp deal into a clear agreement both sides confirm, with a tamper-evident evidence trail.

**Flow:** paste chat → terms found (with citations) → gaps flagged with ready-to-send friendly messages →
plain-language agreement → other party confirms by link + OTP → hash-chained proof anyone can verify.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000 and press **Use sample chat**.

No API key? It still works: a built-in rules engine reads the sample chat. To switch to Claude (much better
on messy Hinglish/Kannada), set the key before starting the server:

```bash
export ANTHROPIC_API_KEY=your-key          # Windows PowerShell: $env:ANTHROPIC_API_KEY="your-key"
```

Other settings are listed in `.env.example` (`CLAUDE_MODEL`, `DEMO_MODE`, `DB_PATH`).

## Demo script (2 minutes)

1. Load the sample chat. Show the price changing 4 times; the app picks the latest and shows the history.
2. Click a `#12` chip to show the exact message each term came from.
3. Show the red gaps (cancellation, warranty...). Tap **Send on WhatsApp** on one.
4. Make the agreement, flip Friendly / Formal, click **Send for confirmation**.
5. Click **Open as other party**, get the demo OTP, confirm.
6. Open **Proof**. Hit **Simulate tampering**. The stamp turns red and the broken link is highlighted.

## How the proof works

Every event is one log entry holding the SHA-256 of its content and the hash of the entry before it.
Edit anything in the past and every later hash stops matching. `/api/verify-file` also lets anyone upload
the original chat file and check its fingerprint against the trail.

To make it stronger than "trust our database": send the latest fingerprint to both parties at each step,
and/or anchor it with OpenTimestamps.

## Layout

```
app/        FastAPI backend (parser, extract, agreement, evidence chain, endpoints)
static/     index.html, confirm.html, app.js, style.css (no build step)
samples/    Hinglish sample chat
tests/      end-to-end API test (pytest)
```

Run the test: `python -m pytest -q tests`

## Not built yet

- Voice notes (Whisper) and screenshot OCR
- Real SMS/WhatsApp OTP (set `DEMO_MODE=0` and plug a provider into `party_otp`)
- State-wise stamp duty estimator and Section 63 BSA certificate draft
- PDF export of the agreement and evidence bundle
- Hindi / Kannada agreement output

## Disclaimer

Not legal advice. The agreement supports a clear record; enforceability and stamp duty depend on your state.
