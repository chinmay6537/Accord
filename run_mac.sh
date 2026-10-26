#!/bin/bash
# Start Accord with the local AI. Run:  bash run_mac.sh      (add --fresh to wipe the data and reseed demo accounts)
cd "$(dirname "$0")"
source .venv/bin/activate
pgrep -x ollama >/dev/null || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
sleep 2
if [ "$1" = "--fresh" ]; then rm -rf data; fi
export LLM_PROVIDER=local
unset ANTHROPIC_API_KEY LOCAL_LLM_URL
python scripts/seed_demo.py
echo "Warming up the model (first time takes ~20 seconds)..."
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"accord-reader","prompt":"hi","stream":false,"keep_alive":"30m"}' >/dev/null || echo "(Ollama not answering: Accord will use the built-in reader)"
echo "Open http://127.0.0.1:8000"
exec python -m uvicorn app.main:app --port 8000
