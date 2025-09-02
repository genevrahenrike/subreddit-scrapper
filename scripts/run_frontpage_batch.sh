#!/usr/bin/env bash
set -euo pipefail

# Run ranked batch subreddit frontpage scraping with Playwright.
# - Sets up .venv and installs deps if missing
# - Respects PROXY_SERVER
# - Defaults: start=0, limit=0 (all), chunk-size=50, order=rank
# - Low, tunable parallelism via CONCURRENCY (safe 1-3, default 2) with INITIAL_JITTER_S stagger
# - Pass extra args to batch_scrape_subreddits.py
#
# Usage:
#   ./scripts/run_frontpage_batch.sh
#   START=100 LIMIT=500 ./scripts/run_frontpage_batch.sh
#   ORDER=alpha OVERWRITE=1 ./scripts/run_frontpage_batch.sh --chunk-size 25
#   PROXY_SERVER="http://user:pass@host:port" ./scripts/run_frontpage_batch.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT_DIR"

START="${START:-0}"
LIMIT="${LIMIT:-0}"
CHUNK="${CHUNK:-50}"
ORDER="${ORDER:-rank}"
OVERWRITE_FLAG="${OVERWRITE:-0}"
CONCURRENCY="${CONCURRENCY:-2}"
INITIAL_JITTER_S="${INITIAL_JITTER_S:-2.0}"

if [[ ! -d .venv ]]; then
  echo "[setup] Creating venv and installing dependencies..."
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -U pip
  pip install -r requirements.txt
  python -m playwright install chromium
else
  source .venv/bin/activate
fi

CMD=("python" "batch_scrape_subreddits.py" "--start" "$START" "--limit" "$LIMIT" "--chunk-size" "$CHUNK" "--order" "$ORDER" "--concurrency" "$CONCURRENCY" "--initial-jitter-s" "$INITIAL_JITTER_S")
if [[ "$OVERWRITE_FLAG" == "1" || "$OVERWRITE_FLAG" == "true" ]]; then
  CMD+=("--overwrite")
fi

echo "[run] ${CMD[*]} $*"
"${CMD[@]}" "$@"
