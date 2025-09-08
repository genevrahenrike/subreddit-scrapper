#!/usr/bin/env bash
set -euo pipefail

# Enhanced batch community ranking scraper with parallel processing
# 
# Features:
# - Intelligent work distribution and load balancing
# - Multi-browser engine support for enhanced stealth
# - Bandwidth optimization and connectivity monitoring
# - Gradual worker ramp-up to prevent request spikes
# - Historical tracking and archiving
#
# Usage:
#   ./scripts/run_community_ranking_batch.sh
#   START_PAGE=1 END_PAGE=1000 WORKERS=4 ./scripts/run_community_ranking_batch.sh
#   PROXY_SERVER="http://user:pass@host:port" MULTI_ENGINE=1 ./scripts/run_community_ranking_batch.sh
#   WORKERS=6 CHUNK_SIZE=10 RAMP_UP_S=5.0 ./scripts/run_community_ranking_batch.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT_DIR"

# Environment variable defaults
START_PAGE="${START_PAGE:-1}"
END_PAGE="${END_PAGE:-1000}"
WORKERS="${WORKERS:-2}"
MAX_WORKERS="${MAX_WORKERS:-8}"
CHUNK_SIZE="${CHUNK_SIZE:-5}"
WORKER_CHUNK_SIZE="${WORKER_CHUNK_SIZE:-25}"
BROWSER_ENGINE="${BROWSER_ENGINE:-chromium}"
MULTI_ENGINE="${MULTI_ENGINE:-0}"
DISABLE_IMAGES="${DISABLE_IMAGES:-1}"
NO_ARCHIVE="${NO_ARCHIVE:-0}"
VISIBLE="${VISIBLE:-0}"
INITIAL_JITTER_S="${INITIAL_JITTER_S:-1.0}"
RAMP_UP_S="${RAMP_UP_S:-3.0}"

# Parse command line arguments to override environment variables
PARSED_START_PAGE="$START_PAGE"
PARSED_END_PAGE="$END_PAGE"
declare -a EXTRA_ARGS=()

for arg in "$@"; do
  case $arg in
    --start-page=*)
      PARSED_START_PAGE="${arg#*=}"
      ;;
    --end-page=*)
      PARSED_END_PAGE="${arg#*=}"
      ;;
    *)
      EXTRA_ARGS+=("$arg")
      ;;
  esac
done

# Setup virtual environment if needed
if [[ ! -d .venv ]]; then
  echo "[setup] Creating venv and installing dependencies..."
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -U pip
  pip install -r requirements.txt
  
  # Install browser engines based on configuration
  if [[ "$MULTI_ENGINE" == "1" || "$MULTI_ENGINE" == "true" ]]; then
    echo "[setup] Installing all browser engines for multi-engine support..."
    python -m playwright install chromium webkit firefox
  else
    echo "[setup] Installing primary browser engine: $BROWSER_ENGINE"
    python -m playwright install "$BROWSER_ENGINE"
  fi
else
  source .venv/bin/activate
fi

# Build command
CMD=(
  "python" "batch_discovery_scraper.py"
  "--start-page" "$PARSED_START_PAGE"
  "--end-page" "$PARSED_END_PAGE"
  "--workers" "$WORKERS"
  "--max-workers" "$MAX_WORKERS"
  "--chunk-size" "$CHUNK_SIZE"
  "--worker-chunk-size" "$WORKER_CHUNK_SIZE"
  "--browser-engine" "$BROWSER_ENGINE"
  "--initial-jitter" "$INITIAL_JITTER_S"
  "--ramp-up" "$RAMP_UP_S"
)

# Add optional flags
if [[ "$MULTI_ENGINE" == "1" || "$MULTI_ENGINE" == "true" ]]; then
  CMD+=("--multi-engine")
fi

if [[ "$DISABLE_IMAGES" == "0" || "$DISABLE_IMAGES" == "false" ]]; then
  CMD+=("--enable-images")
else
  CMD+=("--disable-images")
fi

if [[ "$NO_ARCHIVE" == "1" || "$NO_ARCHIVE" == "true" ]]; then
  CMD+=("--no-archive")
fi

if [[ "$VISIBLE" == "1" || "$VISIBLE" == "true" ]]; then
  CMD+=("--visible")
fi

# Add proxy if set
if [[ -n "${PROXY_SERVER:-}" ]]; then
  CMD+=("--proxy" "$PROXY_SERVER")
fi

# Calculate total pages for display
TOTAL_PAGES=$((PARSED_END_PAGE - PARSED_START_PAGE + 1))

echo "🚀 Enhanced Community Ranking Batch Scraper"
echo "============================================="
echo "Page range: $PARSED_START_PAGE to $PARSED_END_PAGE ($TOTAL_PAGES pages)"
echo "Workers: $WORKERS (max: $MAX_WORKERS)"
echo "Chunk size: $CHUNK_SIZE pages (worker chunks: $WORKER_CHUNK_SIZE)"
echo "Browser: $BROWSER_ENGINE (multi-engine: $MULTI_ENGINE)"
echo "Features: images=$([ "$DISABLE_IMAGES" == "1" ] && echo "blocked" || echo "enabled"), proxy=${PROXY_SERVER:-"none"}"
echo "Timing: ramp-up=${RAMP_UP_S}s, jitter=${INITIAL_JITTER_S}s"
echo ""
echo "Command: ${CMD[*]} ${EXTRA_ARGS[*]-}"
echo ""

# Run the batch scraper
if [ ${#EXTRA_ARGS[@]} -gt 0 ]; then
  "${CMD[@]}" "${EXTRA_ARGS[@]}"
else
  "${CMD[@]}"
fi

echo ""
echo "✅ Batch scraping completed!"
echo "📊 Check output/pages/ for scraped data"
echo "📈 Run trend analysis: python3 analyze_discovery_trends.py --auto-compare"
