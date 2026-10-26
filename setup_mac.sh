#!/bin/bash
# One-time setup for Mac (Apple Silicon). Run:  bash setup_mac.sh
set -e
cd "$(dirname "$0")"
echo "1/4  Python packages"
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
echo "2/4  Ollama (the local AI runtime)"
if ! command -v ollama >/dev/null; then
  if command -v brew >/dev/null; then brew install ollama
  else echo "Install Ollama from https://ollama.com/download, open it once, then run this script again."; exit 1; fi
fi
pgrep -x ollama >/dev/null || (nohup ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
echo "3/4  Downloading the model (about 4.7 GB, one time)"
ollama pull qwen2.5:7b
ollama create accord-reader -f Modelfile
echo "4/4  Checking it reads the sample chat correctly"
LLM_PROVIDER=local python scripts/check_local_llm.py
echo
echo "Done. Start Accord with:  bash run_mac.sh"
