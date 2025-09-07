#!/usr/bin/env bash
set -euo pipefail

# Runner: Incremental baseline only (Step 3)
# - Extends DF caches and processes ONLY the new pages (NEW_PAGE_GLOB must be set)
# - Emits core/extended lists (name+desc vs posts+posts_composed)
# - Keeps content preview per current setup
# - Uses frontpage-backed subset (--require-frontpage) and reuses caches
# Usage:
#   # Option A: pass glob as positional arg
#   ./scripts/run_keywords_overnight_coreext_150k.sh 'output/pages/page_XXXX_to_YYYY.json'
#   # Option B: via env var
#   export NEW_PAGE_GLOB='output/pages/page_XXXX_to_YYYY.json'
#   ./scripts/run_keywords_overnight_coreext_150k.sh
#   # Option C: by page range (inclusive), auto-select from output/pages/page_*.json
#   START_PAGE=1001 END_PAGE=1250 ./scripts/run_keywords_overnight_coreext_150k.sh
#   # You can also set PAGES_DIR if your pages live elsewhere (default: output/pages)
#   # Optional: set REPAIR_BAD_OUTPUTS=1 (default) to remove stale/empty page_*.keywords.jsonl before processing
#   #           This unblocks pages that previously created near-empty or zero-byte outputs.

# Edit these if needed
FRONTPAGE_GLOB='output/subreddits/*/frontpage.json'
OUT_DIR_BASE='output/keywords_10k_v24_k100_coreext'

CACHE_DIR='output/cache'
LOG_DIR='output/logs'
DESC_DF_CACHE="$CACHE_DIR/desc_df_v24.json"
POSTS_DF_CACHE="$CACHE_DIR/posts_df_v24.json"

# NEW_PAGE_GLOB: accept positional arg or env var
ARG_GLOB="${1:-}"
NEW_PAGE_GLOB="${ARG_GLOB:-${NEW_PAGE_GLOB:-}}"

# Optional page-range selection from existing chunked pages (output/pages/page_*.json).
# When both START_PAGE and END_PAGE are set, we build a subset directory of symlinks and
# set NEW_PAGE_GLOB to point to that subset. Avoid overlapping previously-processed pages
# when using --extend-df-caches to prevent description DF double-counting.
START_PAGE="${START_PAGE:-}"
END_PAGE="${END_PAGE:-}"
PAGES_DIR="${PAGES_DIR:-output/pages}"
SUBSET_ROOT="${SUBSET_ROOT:-output/pages_subset}"

if [[ -n "$START_PAGE" && -n "$END_PAGE" ]]; then
  if [[ ! -d "$PAGES_DIR" ]]; then
    echo "ERROR: PAGES_DIR '$PAGES_DIR' does not exist." >&2
    exit 1
  fi
  ts="$(date +%Y%m%d_%H%M%S)"
  SUBSET_DIR="${SUBSET_ROOT}/${START_PAGE}_${END_PAGE}_${ts}"
  mkdir -p "$SUBSET_DIR"
  # Resolve absolute path for symlink targets
  ABS_PAGES_DIR="$(cd "$PAGES_DIR" && pwd)"
  selected=0
  for ((i=START_PAGE; i<=END_PAGE; i++)); do
    src="${ABS_PAGES_DIR}/page_${i}.json"
    if [[ -f "$src" ]]; then
      ln -s "$src" "$SUBSET_DIR/page_${i}.json" 2>/dev/null || cp -n "$src" "$SUBSET_DIR/page_${i}.json"
      selected=$((selected+1))
    fi
  done
  if [[ "$selected" -eq 0 ]]; then
    echo "ERROR: No page_*.json found in range ${START_PAGE}..${END_PAGE} under $PAGES_DIR" >&2
    exit 1
  fi
  NEW_PAGE_GLOB="$SUBSET_DIR/*.json"
  echo "[subset] Built subset dir: $SUBSET_DIR (files=$selected)"
fi

mkdir -p "$OUT_DIR_BASE" "$CACHE_DIR" "$LOG_DIR"

# Disable optional LLM theme summaries
export LLM_SUMMARY=0

if [[ -z "$NEW_PAGE_GLOB" ]]; then
  echo "ERROR: No input pages specified." >&2
  echo "Use one of:" >&2
  echo "  - Positional glob: ./scripts/run_keywords_overnight_coreext_150k.sh 'output/pages/page_1000_to_1250.json'" >&2
  echo "  - Env glob: export NEW_PAGE_GLOB='output/pages/page_1000_to_1250.json' && ./scripts/run_keywords_overnight_coreext_150k.sh" >&2
  echo "  - Page range: START_PAGE=1001 END_PAGE=1250 ./scripts/run_keywords_overnight_coreext_150k.sh" >&2
  exit 1
fi

# Optional repair of stale outputs that are zero-byte or contain no JSON
REPAIR_BAD_OUTPUTS="${REPAIR_BAD_OUTPUTS:-1}"
if [[ "$REPAIR_BAD_OUTPUTS" == "1" ]]; then
  repaired=0
  for src in $NEW_PAGE_GLOB; do
    bn="$(basename "$src")"
    page="${bn%.*}"
    outp="$OUT_DIR_BASE/${page}.keywords.jsonl"
    if [[ -e "$outp" ]]; then
      # Remove if zero bytes OR no '{' found (likely empty placeholder)
      if [[ ! -s "$outp" ]] || ! grep -q "{" "$outp" 2>/dev/null; then
        echo "[repair] removing stale output: $outp"
        rm -f "$outp" || true
        repaired=$((repaired+1))
      fi
    fi
  done
  if [[ "$repaired" -gt 0 ]]; then
    echo "[repair] removed $repaired stale output file(s) prior to processing"
  fi
fi

echo "==== $(date) | Incremental baseline for next pages (NEW_PAGE_GLOB=$NEW_PAGE_GLOB) ===="
time python3 -m src.keyword_extraction \
  --input-glob "$NEW_PAGE_GLOB" \
  --frontpage-glob "$FRONTPAGE_GLOB" \
  --require-frontpage \
  --extend-df-caches \
  --output-dir "$OUT_DIR_BASE" \
  --resume \
  --desc-df-cache "$DESC_DF_CACHE" \
  --posts-df-cache "$POSTS_DF_CACHE" \
  --topk 100 \
  --core-topk 100 \
  --extended-topk 100 \
  --emit-core-extended \
  --name-weight 3.0 \
  --desc-weight 1.0 \
  --posts-weight 1.5 \
  --posts-composed-weight 1.5 \
  --min-df-bigram 2 \
  --min-df-trigram 2 \
  --posts-ensure-k 10 \
  --posts-generic-df-ratio 0.10 \
  --posts-drop-generic-unigrams \
  --posts-phrase-boost-bigram 1.35 \
  --posts-phrase-boost-trigram 1.7 \
  --desc-idf-power 0.8 \
  --posts-idf-power 0.4 \
  --posts-engagement-alpha 0.0 \
  --compose-seed-source posts_local_tf \
  --compose-anchor-top-m 200 \
  --compose-anchor-score-mode idf_blend \
  --compose-anchor-alpha 0.7 \
  --compose-anchor-floor 1.0 \
  --compose-anchor-cap 2.0 \
  --compose-anchor-max-per-sub 8 \
  --compose-anchor-min-base-score 3.0 \
  --compose-anchor-max-ratio 2.0 \
  --posts-skip-promoted \
  --posts-drop-nonlatin \
  --posts-max-nonascii-ratio 0.50 \
  --no-compose-allow-token-with-phrase \
  --clean-collapse-adj-dups \
  --clean-dedupe-near \
  --drop-nonlatin \
  --max-nonascii-ratio 0.50 \
  --include-content-preview \
  2>&1 | tee -a "$LOG_DIR/keywords_coreext_step3_incremental.log"

echo "==== $(date) | Completed incremental baseline. ===="