#!/usr/bin/env bash
set -euo pipefail

# Run ranked batch subreddit frontpage scraping with Playwright.
# - Sets up .venv and installs deps if missing
# - Respects PROXY_SERVER
# - Defaults: start=0, limit=0 (all), chunk-size=50, order=rank
# - Low, tunable parallelism via CONCURRENCY (safe 1-3, default 2) with INITIAL_JITTER_S stagger
# - Higher concurrency supported (up to 12 by default) with proper worker isolation
# - Gradual worker ramp-up via RAMP_UP_S to prevent request spikes (default 2s for faster startup)
# - Pass extra args to batch_scrape_subreddits.py
#
# Usage:
#   ./scripts/run_frontpage_batch.sh
#   START=100 LIMIT=500 ./scripts/run_frontpage_batch.sh
#   ORDER=alpha OVERWRITE=1 ./scripts/run_frontpage_batch.sh --chunk-size 25
#   PROXY_SERVER="http://user:pass@host:port" RAMP_UP_S=15 ./scripts/run_frontpage_batch.sh
#   CONCURRENCY=12 ./scripts/run_frontpage_batch.sh --start=80000 --limit=10000 --multi-profile --persistent-session

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT_DIR"

# Parse command line arguments to override environment variables
PARSED_START="${START:-0}"
PARSED_LIMIT="${LIMIT:-0}"
CHUNK="${CHUNK:-50}"
ORDER="${ORDER:-rank}"
OVERWRITE_FLAG="${OVERWRITE:-0}"
CONCURRENCY="${CONCURRENCY:-2}"
INITIAL_JITTER_S="${INITIAL_JITTER_S:-0.75}"
RAMP_UP_S="${RAMP_UP_S:-2.0}"
PER_ITEM_SLEEP_MIN="${PER_ITEM_SLEEP_MIN:-0.15}"
PER_ITEM_SLEEP_MAX="${PER_ITEM_SLEEP_MAX:-0.45}"
MIN_POSTS="${MIN_POSTS:-}"
SCROLL_WAIT_MS="${SCROLL_WAIT_MS:-}"
MAX_PAGE_SECONDS="${MAX_PAGE_SECONDS:-}"
INCLUDE_PROMOTED="${INCLUDE_PROMOTED:-}"

# Parse arguments to extract start/limit values if provided
EXTRA_ARGS=()
for arg in "$@"; do
  case $arg in
    --start=*)
      PARSED_START="${arg#*=}"
      ;;
    --limit=*)
      PARSED_LIMIT="${arg#*=}"
      ;;
    *)
      EXTRA_ARGS+=("$arg")
      ;;
  esac
done

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

CMD=("python" "batch_scrape_subreddits.py" "--start" "$PARSED_START" "--limit" "$PARSED_LIMIT" "--chunk-size" "$CHUNK" "--order" "$ORDER" "--concurrency" "$CONCURRENCY" "--initial-jitter-s" "$INITIAL_JITTER_S" "--ramp-up-s" "$RAMP_UP_S" "--per-item-sleep-min" "$PER_ITEM_SLEEP_MIN" "--per-item-sleep-max" "$PER_ITEM_SLEEP_MAX")
if [[ "$OVERWRITE_FLAG" == "1" || "$OVERWRITE_FLAG" == "true" ]]; then
  CMD+=("--overwrite")
fi

# Optionally forward throughput/behavior overrides
if [[ -n "$MIN_POSTS" ]]; then
  CMD+=("--min-posts" "$MIN_POSTS")
fi
if [[ -n "$SCROLL_WAIT_MS" ]]; then
  CMD+=("--scroll-wait-ms" "$SCROLL_WAIT_MS")
fi
if [[ -n "$MAX_PAGE_SECONDS" ]]; then
  CMD+=("--max-page-seconds" "$MAX_PAGE_SECONDS")
fi
# Normalize INCLUDE_PROMOTED in a bash-3 compatible way (macOS default bash is 3.2)
_lower="$(printf '%s' "$INCLUDE_PROMOTED" | tr '[:upper:]' '[:lower:]')"
case "$_lower" in
  1|true|yes)
    CMD+=("--include-promoted")
    ;;
  0|false|no)
    CMD+=("--exclude-promoted")
    ;;
esac
unset _lower

echo "[run] ${CMD[*]} ${EXTRA_ARGS[*]}"
"${CMD[@]}" "${EXTRA_ARGS[@]}"
