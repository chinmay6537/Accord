# Handshake

Turn a WhatsApp deal into a clear agreement both sides confirm, with a tamper-evident evidence trail.

**Flow:** paste chat → terms found (with citations) → gaps flagged with ready-to-send friendly messages →
plain-language agreement → other party confirms by link + OTP → hash-chained proof anyone can verify.

## Who is who

| Role | Lands on | Can do |
|---|---|---|
| **Dealer** | `/dealer` | Dashboard: overview, tickets (history of every request), customers, segments, new ticket. Builds the evidence and agreement at `/ticket/<id>`. |
| **Customer** | `/customer` | View-only. Sees requests dealers sent them, checks every term against the messages behind it, chats with the dealer, then approves or asks for a change. Cannot create tickets. |
| Anyone with a link | `/c/<token>` | Confirms with a phone code, no account needed (the original flow). |

A **ticket** is one deal with one customer. Flow: dealer opens *New ticket* (title, customer, description, optional
details) -> adds evidence -> reads terms -> builds the agreement -> sends. The customer sees it in their portal.

**Linking customers to accounts:** the dealer saves a customer and gets a private invite link
(`/join/<token>`, shown on the customer's page). The customer signs up through it, which connects their account to
that dealer's records. We deliberately do *not* match by email or phone, because neither is verified.

## Customer review (verify, then approve)

Open a request at `/customer`. For each term (what was agreed, price, delivery, payment) the customer sees the value,
the exact messages it came from, how it changed along the way, and a warning if the dealer edited it by hand.
They mark each term "matches my records" or "does not match" (with a note), can press **Ask the dealer about this**
to prefill the chat, and see the proof status, evidence fingerprints and step trail.
**Approve stays disabled until every agreed term is marked as matching** (also enforced on the server). If anything
does not match they use **Ask for changes**. Their checks are saved into the hash chain with the answer.
Customers only see messages cited behind a term, never the dealer's private notes or the whole evidence.

```
GET  /api/my/tickets               GET /api/my/tickets/{id}   (full review payload)
PUT  /api/my/tickets/{id}/checks/{scope|price|delivery|payment_terms}  {result: match|mismatch|clear, note}
POST /api/my/tickets/{id}/respond  {action: agree|change, note}
```

## Landing and auth pages

The landing page (`static/landing.html`) shows a free demo through `POST /api/demo` (no login, rules engine only, 8 tries a minute, nothing saved). Everything after the demo needs an account. Replace the pages freely, but keep the routes and this API:

## Auth API (used by `static/js/auth.js`)

Restyle freely, but keep the routes `/`, `/login`, `/signup`, `/join/<token>` and call:

```
POST /api/auth/signup  {name, email, password, role: "dealer"|"customer", phone?, business_name?, invite_token?}
POST /api/auth/login   {email, password}
POST /api/auth/logout
GET  /api/auth/me
GET  /api/join/<token>   -> {customer_name, dealer_name, business_name}   (for the invite banner)
```
Signup and login answer `{id, name, role, home}` and set an HttpOnly session cookie; send the browser to `home`
(`/dealer` or `/customer`). On `/join/<token>` the page should sign up with `role: "customer"` and `invite_token`.
Errors come back as `{detail: "message"}` with a 4xx status.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000, sign up as a dealer, create a ticket, and press **Use sample chat** on the evidence page.

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
app/                 Python backend (FastAPI + SQLite)
  main.py              page routes + the evidence/agreement workflow API
  routes_auth.py       signup, login, logout, me, invite lookup
  routes_demo.py       PUBLIC landing-page demo (rules engine only, rate limited, saves nothing)
  routes_dealer.py     overview, tickets, customers, segments
  routes_customer.py   customer review: terms, references, checks, approve / ask for change
  routes_thread.py     chat + comments on a ticket
  proof.py             chain + stored-file verification shared by dealer and customer
  auth.py common.py    sessions, passwords, shared helpers
  ingest.py parser.py extract.py agreement.py evidence.py db.py
static/              Frontend. Every page = one .html shell + the shared css + one page script
  css/style.css        THE design system (black and white neo-brutalism). Only stylesheet.
  js/common.js         shared helpers: esc, api, J, toast, day, when, copy (load first)
  js/thread.js         chat component used by dealer and customer pages
  landing.html   js/landing.js    public page with the free demo
  login.html     js/auth.js       log in, sign up, customer invite (/join/<token>)
  dealer.html    js/dealer.js     dealer dashboard (sidebar)
  customer.html  js/customer.js   customer portal (sidebar), verify then approve
  ticket.html    js/ticket.js     evidence -> terms -> agreement -> proof (/ticket/<id>)
  confirm.html   js/confirm.js    no-account confirmation link (/c/<token>)
samples/             Hinglish sample chat
tests/               API tests for the whole flow (pytest)
```

## Design rules (keep every new screen on these)

- **Black and white only.** No colours. Meaning comes from shape and text:
  solid black = done/confirmed, dashed grey = pending/notice, stripes = problem/needs attention.
  (The class names `tag green / yellow / red` are kept; the stylesheet turns them into those three looks.)
- Thick 3px black borders, hard offset shadows, no rounded corners, Archivo + JetBrains Mono.
- Use the existing classes (`.card`, `.btn`, `.btn.primary`, `.tag`, `.field`, `.grid2`, `.row`, `.note`, `.gate`).
  Do not add per-page stylesheets or inline colours.
- Pages without a sidebar use the `.topbar`; dashboards use the `.shell` + `.side` sidebar.

Run the test: `python -m pytest -q tests`

## Not built yet

- Local (offline) speech-to-text
- Email/phone verification, password reset
- Dealer revises the agreement after the customer asks for a change, then re-sends
- Notifications when a customer replies (chat updates by polling every 4 s)
- Real SMS/WhatsApp OTP (set `DEMO_MODE=0` and plug a provider into `party_otp`)
- State-wise stamp duty estimator and Section 63 BSA certificate draft
- PDF export of the agreement and evidence bundle
- Hindi / Kannada agreement output

## Disclaimer

Not legal advice. The agreement supports a clear record; enforceability and stamp duty depend on your state.
