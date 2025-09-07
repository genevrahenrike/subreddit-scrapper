#!/usr/bin/env bash
set -euo pipefail

# Overnight runner to:
# 1) Re-run pass-2 for the existing 100k with core/extended emission
# 2) Embedding-only rerank (GPU MPS by default)
# 3) Incrementally extend to next 50k (set NEW_PAGE_GLOB), with core/extended emission
# 4) Embedding-only rerank over combined outputs (resumes; reranks only new pages)

# Edit these if needed
INPUT_GLOB='output/pages/page_*.json'
FRONTPAGE_GLOB='output/subreddits/*/frontpage.json'

OUT_DIR_BASE='output/keywords_10k_v24_k100_coreext'
OUT_DIR_EMBED='output/keywords_10k_v24_k100_coreext_embed'

CACHE_DIR='output/cache'
LOG_DIR='output/logs'
DESC_DF_CACHE="$CACHE_DIR/desc_df_v24.json"
POSTS_DF_CACHE="$CACHE_DIR/posts_df_v24.json"

# Set this to ONLY the new page files for the next 50k (e.g., 'output/pages/page_1000_to_1250.json' or a glob)
NEW_PAGE_GLOB="${NEW_PAGE_GLOB:-}"

mkdir -p "$OUT_DIR_BASE" "$OUT_DIR_EMBED" "$CACHE_DIR" "$LOG_DIR"

# Disable optional LLM theme summaries
export LLM_SUMMARY=0

# Default embedding device/batch (MPS on Apple Silicon); override by exporting EMBED_DEVICE/EMBED_BATCH_SIZE
export EMBED_DEVICE="${EMBED_DEVICE:-mps}"
export PYTORCH_ENABLE_MPS_FALLBACK=1
export EMBED_BATCH_SIZE="${EMBED_BATCH_SIZE:-64}"

echo "==== $(date) | Step 1: Baseline pass with core/extended for first 100k ===="
time python3 -m src.keyword_extraction \
  --input-glob "$INPUT_GLOB" \
  --frontpage-glob "$FRONTPAGE_GLOB" \
  --require-frontpage \
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
  2>&1 | tee -a "$LOG_DIR/keywords_coreext_step1_baseline.log"

echo "==== $(date) | Step 2: Embedding-only rerank for first 100k (composed-only pool) ===="
time python3 -m src.keyword_extraction \
  --embed-only-input-dir "$OUT_DIR_BASE" \
  --output-dir "$OUT_DIR_EMBED" \
  --resume \
  --embed-rerank \
  --embed-model 'BAAI/bge-small-en-v1.5' \
  --embed-alpha 0.35 \
  --embed-k-terms 120 \
  --embed-candidate-pool posts_composed \
  --posts-theme-top-desc-k 6 \
  2>&1 | tee -a "$LOG_DIR/keywords_coreext_step2_embed.log"

if [[ -n "$NEW_PAGE_GLOB" ]]; then
  echo "==== $(date) | Step 3: Incremental baseline for next 50k (NEW_PAGE_GLOB=$NEW_PAGE_GLOB) ===="
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

  echo "==== $(date) | Step 4: Embedding-only rerank for new pages (resumes) ===="
  time python3 -m src.keyword_extraction \
    --embed-only-input-dir "$OUT_DIR_BASE" \
    --output-dir "$OUT_DIR_EMBED" \
    --resume \
    --embed-rerank \
    --embed-model 'BAAI/bge-small-en-v1.5' \
    --embed-alpha 0.35 \
    --embed-k-terms 120 \
    --embed-candidate-pool posts_composed \
    --posts-theme-top-desc-k 6 \
    2>&1 | tee -a "$LOG_DIR/keywords_coreext_step4_embed_incremental.log"
else
  echo "==== $(date) | Step 3/4 skipped: NEW_PAGE_GLOB is empty. Set NEW_PAGE_GLOB to a glob of only the new page files to enable incremental 50k. ===="
fi

echo "==== $(date) | All steps completed. ===="