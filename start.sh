#!/bin/sh
# Start Accord the way a host expects: listen on $PORT, trust the proxy's HTTPS headers,
# and (optionally) create the demo accounts first so a fresh deploy is ready to show.
set -e
if [ "${SEED_DEMO:-0}" = "1" ]; then
  python scripts/seed_demo.py
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
