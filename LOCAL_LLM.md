# Local AI on your Mac (M4, 16 GB)

Accord reads chats with a model running on your own Mac through Ollama. Nothing leaves your laptop, no API key,
no internet needed after the one-time download. If the model ever fails, the built-in reader answers instead.

## Setup (once, about 10 minutes)
```
cd accord-clean
bash setup_mac.sh
```
It installs the Python packages and Ollama, downloads `qwen2.5:7b` (4.7 GB), builds the `accord-reader` model
from `Modelfile`, and tests it on the sample chat. You should see `PASS` and a price of ₹54,000.

## Every time you present
```
bash run_mac.sh            # normal start
bash run_mac.sh --fresh    # wipe data first, then recreate the demo dealer and customer
```
Open http://127.0.0.1:8000. A deal's terms card says "Read by the local model (accord-reader)".
Demo logins: demo.dealer@accord.test and demo.customer@accord.test, password demo12345.

## How it is tuned (no training needed)
Fine-tuning a model on a 16 GB Mac is slow and would not beat these three things, which are already built in:
1. **Fixed settings** (`Modelfile`): temperature 0, 8k context, same behaviour every time.
2. **A worked example and a strict JSON schema** are sent with every request, so the small model cannot return
   broken output and learns the two tricky rules: a price belongs to a quantity, and an advance is not the price.
3. **A safety check against the chat** (`_guard` in `app/extract.py`): a price that is not in the chat, or an old
   price when a later one was accepted, is corrected and the page says so.

## Speed and memory
- First request after starting: ~20 s while the model loads. `run_mac.sh` warms it up for you. Then 5 to 20 s per read.
- Uses about 6 GB of RAM while loaded, so keep heavy apps closed. Model stays loaded for 30 minutes.
- Too slow? `ollama pull qwen2.5:3b`, then `export LOCAL_LLM_MODEL=qwen2.5:3b` before `run_mac.sh`.

## Troubleshooting
- `ollama list` should show `accord-reader`. If not, run `ollama create accord-reader -f Modelfile`.
- `curl http://127.0.0.1:11434` should say "Ollama is running". If not, run `ollama serve` in another Terminal.
- Terms card says "built-in rules ... could not be reached": Ollama is not running or the model is still loading.

## Optional: a model on another laptop
Run `scripts/llm_gateway.py` there with a tunnel, then set `LOCAL_LLM_URL` and `LOCAL_LLM_TOKEN` on this side
(`LLM_PROVIDER=local`). The landing-page demo never uses the model.
