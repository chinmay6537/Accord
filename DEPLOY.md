# Deploying Accord

Accord is one Python process (FastAPI) with a SQLite file. Any host that can run a Docker container works.
This repo already has the files hosts need: `Dockerfile`, `start.sh`, `render.yaml`, `.dockerignore`.

## Before you start

1. Push the project to GitHub (see "Push to GitHub" below).
2. Decide on the demo setting:
   - `SEED_DEMO=1` creates the demo dealer and customer every time the app starts, so your link always has
     something to show. Log in with `demo.dealer@accord.test` / `demo.customer@accord.test`, password `demo12345`.
   - `DEMO_MODE=1` shows confirmation codes on screen (needed unless you connect an SMS provider).
3. Optional keys: `ANTHROPIC_API_KEY` (much better reading of messy chats) and `OPENAI_API_KEY` (voice notes).

## Option A: Render (easiest, free)

1. Go to <https://render.com> and sign in with GitHub.
2. **New +** then **Blueprint**, pick your repo. Render reads `render.yaml`.
3. When asked, paste `ANTHROPIC_API_KEY` (and `OPENAI_API_KEY` if you have one). Leave the rest.
4. Press **Apply**. The first build takes a few minutes.
5. Open the `https://accord-xxxx.onrender.com` link Render shows. Check `/healthz` returns `{"ok":true}`.

Free plan caveats (important for a demo):
- The app **sleeps after about 15 minutes** without visitors. The next visit takes 30 to 60 seconds to wake it. Open the link yourself a minute before presenting.
- The disk is **wiped on every restart and deploy**. Accounts and tickets you create are lost. That is why `SEED_DEMO=1` is on: the demo accounts come back each time.
- To keep data, use a paid instance and uncomment the `disk:` block in `render.yaml` (mounted at `/app/data`).

## Option B: Railway

1. <https://railway.app> then **New Project** then **Deploy from GitHub repo**. It detects the `Dockerfile`.
2. In **Variables** add `SEED_DEMO=1`, `DEMO_MODE=1` and your API keys.
3. **Settings** then **Networking** then **Generate Domain**.
4. To keep data: add a **Volume** mounted at `/app/data`.

## Option C: Fly.io

```bash
fly launch --no-deploy          # accept the Dockerfile, pick a region (e.g. Mumbai: bom)
fly volumes create accord_data --size 1
# in fly.toml add:  [mounts] source = "accord_data"  destination = "/app/data"
fly secrets set ANTHROPIC_API_KEY=... SEED_DEMO=1 DEMO_MODE=1
fly deploy
```

## Run it yourself in Docker

```bash
docker build -t accord .
docker run -p 8000:8000 -e SEED_DEMO=1 -v accord-data:/app/data accord
```

## Push to GitHub

```bash
cd accord
git init
git add .
git commit -m "Accord: from chat to commitment"
git branch -M main
git remote add origin https://github.com/<your-username>/accord.git
git push -u origin main
```

`.gitignore` already keeps `.env`, `.venv` and `data/` out of the repo. Never commit API keys.

## After it is live: quick checklist

- [ ] `/healthz` answers
- [ ] Landing page demo works
- [ ] Log in as the demo dealer, open the ticket, download the PDF report
- [ ] Log in as the demo customer in a private window, check the terms, approve
- [ ] Sign up works with a new email (cookies need HTTPS, which hosts provide)

## Going beyond a demo

- Set `DEMO_MODE=0` and connect an SMS or WhatsApp provider in `party_otp` (`app/main.py`), otherwise the code is never delivered.
- Use a persistent disk or move SQLite to Postgres if you expect real users.
- Run one instance only: login throttling and the demo rate limit are kept in memory.
- Add email verification and password reset before inviting the public.
