#!/usr/bin/env bash
set -euo pipefail

INPUT_GLOB='output/pages/page_*.json'
FRONTPAGE_GLOB='output/subreddits/*/frontpage.json'
OUT_DIR_BASE='output/keywords_10k_v22'
OUT_DIR_EMBED='output/keywords_10k_v22_embed'
CACHE_DIR='output/cache'
LOG_DIR='output/logs'
DESC_DF_CACHE="$CACHE_DIR/desc_df_10k_v22.json"
POSTS_DF_CACHE="$CACHE_DIR/posts_df_10k_v22.json"

mkdir -p "$OUT_DIR_BASE" "$OUT_DIR_EMBED" "$CACHE_DIR" "$LOG_DIR"

export LLM_SUMMARY=0

echo "==== Baseline pass (no embeddings) ===="
time python3 -m src.keyword_extraction \
  --input-glob "$INPUT_GLOB" \
  --frontpage-glob "$FRONTPAGE_GLOB" \
  --require-frontpage \
  --output-dir "$OUT_DIR_BASE" \
  --resume \
  --desc-df-cache "$DESC_DF_CACHE" \
  --posts-df-cache "$POSTS_DF_CACHE" \
  --topk 40 \
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
  --clean-collapse-adj-dups \
  --clean-dedupe-near \
  --drop-nonlatin \
  --max-nonascii-ratio 0.50 \
  --include-content-preview \
  2>&1 | tee -a "$LOG_DIR/keywords_baseline.log"

echo "==== Embedding rerank pass (GPU MPS) ===="
export EMBED_DEVICE=mps
export PYTORCH_ENABLE_MPS_FALLBACK=1
time python3 -m src.keyword_extraction \
  --input-glob "$INPUT_GLOB" \
  --frontpage-glob "$FRONTPAGE_GLOB" \
  --require-frontpage \
  --output-dir "$OUT_DIR_EMBED" \
  --resume \
  --desc-df-cache "$DESC_DF_CACHE" \
  --posts-df-cache "$POSTS_DF_CACHE" \
  --topk 40 \
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
  --clean-collapse-adj-dups \
  --clean-dedupe-near \
  --drop-nonlatin \
  --max-nonascii-ratio 0.50 \
  --include-content-preview \
  --embed-rerank \
  --embed-model 'BAAI/bge-small-en-v1.5' \
  --embed-alpha 0.35 \
  --embed-k-terms 120 \
  --embed-candidate-pool posts_composed \
  2>&1 | tee -a "$LOG_DIR/keywords_embed.log"

echo "All done."