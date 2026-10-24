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

## The evidence page (step 1)

Everything the deal rests on goes in here, and each item is fingerprinted (SHA-256) the moment it lands.

| You add | What happens |
|---|---|
| WhatsApp `.txt` export or pasted chat | Parsed into numbered, time-stamped messages |
| WhatsApp `.zip` ("with media") | Unpacked: chat, voice notes and photos become separate items |
| Voice note (.opus, .mp3, .m4a ...) | Whisper transcript if `OPENAI_API_KEY` is set (marked "machine text, check it"); otherwise you type what it says |
| Screenshot (.png, .jpg) | Claude reads the text if `ANTHROPIC_API_KEY` is set; otherwise you type it |
| PDF / Word / text file | Text is read; a scanned PDF asks you to type it |
| Typed note (call, in person) | Stored as evidence with who said it and when |

Items from different sources are merged into one timeline by their dates, so a later voice note or call
can correctly override a price in the chat. A checklist tells you what's missing before you press
**Read the evidence**. Removing an item stops it being used but keeps the original and logs the removal.
Re-hashing every stored file on each page load means a swapped or edited file turns the proof red.

Voice-note transcription and screenshot reading need API keys and were not run against the live services here.

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
tests/      API tests for the whole flow and the evidence page (pytest)
```

Run the test: `python -m pytest -q tests`

## Not built yet

- Local (offline) speech-to-text
- Real SMS/WhatsApp OTP (set `DEMO_MODE=0` and plug a provider into `party_otp`)
- State-wise stamp duty estimator and Section 63 BSA certificate draft
- PDF export of the agreement and evidence bundle
- Hindi / Kannada agreement output

## Disclaimer

Not legal advice. The agreement supports a clear record; enforceability and stamp duty depend on your state.
