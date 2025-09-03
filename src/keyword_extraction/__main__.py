#!/usr/bin/env python3
"""
Keyword extraction for subreddit pages.

- Reads one or many output/pages/page_*.json files (page-sized, ~250 subs each)
- Produces per-subreddit keyword lists with relevance weights (JSONL), keeping a clear mapping
- Lightweight: pure Python, no external dependencies required

Usage examples:
  python3 -m src.keyword_extraction --input-file output/pages/page_60.json
  python3 -m src.keyword_extraction --input-glob "output/pages/page_*.json" --topk 25
  python3 -m src.keyword_extraction --input-file output/pages/page_60.json --output-dir output/keywords

Output:
  For each input file path/to/page_N.json, writes:
    output/keywords/page_N.keywords.jsonl
  Each line is a JSON object with:
    {
      "community_id": "...",
      "name": "r/SomeSub",
      "url": "/r/SomeSub/",
      "rank": 1234,
      "subscribers_count": 12345,
      "keywords": [
        { "term": "crossdressing support", "weight": 0.173, "score": 12.4, "source": "both" },
        { "term": "gluten free baking", "weight": 0.158, "score": 11.3, "source": "description" },
        ...
      ]
    }

Design notes:
- Name extraction: robust splitting (delimiters, camel/pascal, digits), plus heuristic segmentation for common suffixes/prefixes and acronyms expansion.
- Description extraction: 1–3-gram TF-IDF built across the selected input files (one or many). Stopwords remove filler words.
- Posts extraction: n-gram TF-IDF from frontpage post titles (and optionally content preview), with engagement and recency weighting; phrase preference; optional anchored variants for generic terms.
- Scoring: Combine description TF-IDF, name-derived scores, and posts-derived scores; then normalize per-subreddit so weights sum to 1.0.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from glob import glob
from typing import Dict, List, Optional, Set

from . import config
from .composition import (
    _compose_rank_seeds_with_embed,
    compose_theme_anchored_from_posts,
    recase_anchored_display,
    _normalize_anchor_phrase_from_title
)
from .description_processing import extract_desc_terms
from .embedding import _build_theme_text, embed_rerank_terms
from .file_utils import _build_frontpage_index, ensure_dir, out_path_for_input
from .name_processing import extract_name_full_phrase
from .posts_processing import (
    apply_anchored_variants_for_generic_posts_terms,
    build_posts_docfreq,
    compute_posts_tfidf_for_frontpage,
)
from .scoring import (
    build_docfreq,
    compute_tfidf_per_doc,
    merge_sources,
    normalize_weights,
    score_name_terms,
)
from .subreddit_data import (
    canonicalize_subreddit_key,
    iter_subreddits_from_file,
    subreddit_display_key,
    subreddit_folder_from_name,
)
from .text_utils import tokens_to_ngrams


def process_inputs(
    input_paths: List[str],
    output_dir: str,
    topk: int,
    max_ngram: int,
    name_weight: float,
    desc_weight: float,
    min_df_bigram: int,
    min_df_trigram: int,
    # Posts integration (optional)
    frontpage_glob: Optional[str] = None,
    posts_weight: float = config.DEFAULT_POSTS_WEIGHT,
    posts_composed_weight: Optional[float] = None,
    posts_halflife_days: float = config.DEFAULT_POSTS_HALFLIFE_DAYS,
    posts_generic_df_ratio: float = config.DEFAULT_POSTS_GENERIC_DF_RATIO,
    posts_ensure_k: int = config.DEFAULT_ENSURE_PHRASES_K,
    posts_stopwords_extra_path: Optional[str] = None,
    posts_anchor_generics: bool = True,
    posts_phrase_boost_bigram: float = config.DEFAULT_POSTS_PHRASE_BOOST_BIGRAM,
    posts_phrase_boost_trigram: float = config.DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM,
    posts_drop_generic_unigrams: bool = False,
    posts_phrase_stoplist_path: Optional[str] = None,
    posts_replace_generic_with_anchored: bool = False,
    posts_theme_penalty: float = 0.65,
    posts_theme_top_desc_k: int = 6,
    # Composed anchored variants (optional)
    compose_anchor_posts: bool = config.DEFAULT_COMPOSE_ANCHOR_POSTS,
    compose_anchor_multiplier: float = config.DEFAULT_COMPOSE_ANCHOR_MULTIPLIER,
    compose_anchor_top_m: int = config.DEFAULT_COMPOSE_ANCHOR_TOP_M,
    compose_anchor_include_unigrams: bool = config.DEFAULT_COMPOSE_ANCHOR_INCLUDE_UNIGRAMS,
    compose_anchor_max_final_words: int = config.DEFAULT_COMPOSE_ANCHOR_MAX_FINAL_WORDS,
    compose_anchor_use_title: bool = config.DEFAULT_COMPOSE_ANCHOR_USE_TITLE,
    compose_subjects_path: Optional[str] = None,
    compose_subjects_bonus: float = config.DEFAULT_COMPOSE_SUBJECTS_BONUS,
    # Embedding rerank (optional)
    embed_rerank: bool = config.DEFAULT_EMBED_RERANK,
    embed_model: str = config.DEFAULT_EMBED_MODEL,
    embed_alpha: float = config.DEFAULT_EMBED_ALPHA,
    embed_k_terms: int = config.DEFAULT_EMBED_K_TERMS,
    # New controls
    desc_idf_power: float = config.DEFAULT_DESC_IDF_POWER,
    posts_idf_power: float = config.DEFAULT_POSTS_IDF_POWER,
    posts_engagement_alpha: float = config.DEFAULT_POSTS_ENGAGEMENT_ALPHA,
    compose_seed_source: str = "hybrid",
    embed_candidate_pool: str = config.DEFAULT_EMBED_CANDIDATE_POOL,
    compose_seed_embed: bool = config.DEFAULT_COMPOSE_SEED_EMBED,
    compose_seed_embed_alpha: float = config.DEFAULT_COMPOSE_SEED_EMBED_ALPHA,
    # New: composed scoring behavior
    compose_anchor_score_mode: str = config.DEFAULT_COMPOSE_ANCHOR_SCORE_MODE,
    compose_anchor_alpha: float = config.DEFAULT_COMPOSE_ANCHOR_ALPHA,
    compose_anchor_floor: float = config.DEFAULT_COMPOSE_ANCHOR_FLOOR,
    compose_anchor_cap: float = config.DEFAULT_COMPOSE_ANCHOR_CAP,
    compose_anchor_max_per_sub: int = config.DEFAULT_COMPOSE_ANCHOR_MAX_PER_SUB,
    compose_anchor_min_base_score: float = config.DEFAULT_COMPOSE_ANCHOR_MIN_BASE_SCORE,
    compose_anchor_max_ratio: float = config.DEFAULT_COMPOSE_ANCHOR_MAX_RATIO,
) -> None:
    if not input_paths:
        print("No input files matched.", file=sys.stderr)
        return

    ensure_dir(output_dir)

    # Optional: load extra posts stopwords from file
    posts_extra_stopwords_set: Set[str] = set()
    if posts_stopwords_extra_path:
        try:
            with open(posts_stopwords_extra_path, "r", encoding="utf-8") as f:
                for line in f:
                    # allow comments and comma/space separated entries
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    for tok in re.split(r"[,\s]+", line):
                        tok = tok.strip().lower()
                        if tok and not tok.startswith("#"):
                            posts_extra_stopwords_set.add(tok)
            print(f"[posts:stopwords] loaded {len(posts_extra_stopwords_set)} extra posts stopwords from {posts_stopwords_extra_path}", file=sys.stderr)
        except Exception as e:
            print(f"[posts:stopwords] failed to load extra stopwords from {posts_stopwords_extra_path}: {e}", file=sys.stderr)

    # Optional: load posts phrase stoplist (bigrams/trigrams to exclude)
    posts_phrase_stoplist_set: Set[str] = set()
    if posts_phrase_stoplist_path:
        try:
            with open(posts_phrase_stoplist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip().lower()
                    if not line or line.startswith("#"):
                        continue
                    # normalize internal whitespace
                    line = re.sub(r"\s+", " ", line)
                    posts_phrase_stoplist_set.add(line)
            print(f"[posts:phrases] loaded {len(posts_phrase_stoplist_set)} stoplist phrase(s) from {posts_phrase_stoplist_path}", file=sys.stderr)
        except Exception as e:
            print(f"[posts:phrases] failed to load phrase stoplist from {posts_phrase_stoplist_path}: {e}", file=sys.stderr)

    # Subject whitelist removed in v2: composition now uses local post grams (no editorial list)
    compose_subjects_set: Set[str] = set()

    # Pass 0 (optional): posts DF across frontpages
    frontpage_index: Dict[str, str] = {}
    frontpage_paths: List[str] = []
    posts_docfreq: Counter = Counter()
    posts_total_docs: int = 0
    if frontpage_glob:
        print(f"[posts:pass1] building posts docfreq over glob={frontpage_glob!r} ...", file=sys.stderr)
        frontpage_index, frontpage_paths = _build_frontpage_index(frontpage_glob)
        posts_docfreq, posts_total_docs = build_posts_docfreq(frontpage_paths, max_ngram, posts_extra_stopwords_set, posts_phrase_stoplist_set)
        print(f"[posts:pass1] total_frontpages={posts_total_docs:,}, unique_terms={len(posts_docfreq):,}", file=sys.stderr)

    # Pass 1: global docfreq across selected inputs (for description n-grams)
    print(f"[desc:pass1] building docfreq over {len(input_paths)} file(s)...", file=sys.stderr)
    docfreq, total_docs = build_docfreq(input_paths, max_ngram)
    print(f"[desc:pass1] total_docs={total_docs:,}, unique_terms={len(docfreq):,}", file=sys.stderr)

    # Cache for loaded frontpage JSONs
    frontpage_cache: Dict[str, dict] = {}

    # Pass 2: per file, compute per-subreddit scores and write JSONL
    for inp in input_paths:
        outp = out_path_for_input(output_dir, inp)
        print(f"[pass2] processing {inp} -> {outp}", file=sys.stderr)

        count_written = 0
        with open(outp, "w", encoding="utf-8") as fout:
            for sub in iter_subreddits_from_file(inp):
                # Description TF-IDF
                desc_tokens = extract_desc_terms(sub.desc_text, max_ngram)
                desc_tfidf = compute_tfidf_per_doc(
                    desc_tokens, docfreq, total_docs, max_ngram, min_df_bigram, min_df_trigram, desc_idf_power
                )

                # Ensure local multi-word phrases even if globally rare (keeps fuller phrases)
                if config.DEFAULT_ENSURE_PHRASES and config.DEFAULT_ENSURE_PHRASES_K > 0 and desc_tokens:
                    local_grams = tokens_to_ngrams(desc_tokens, max_ngram)
                    candidates = [
                        (g, tf)
                        for g, tf in local_grams.items()
                        if (g.count(" ") + 1) >= 2 and g not in desc_tfidf
                    ]
                    if candidates:
                        candidates.sort(key=lambda x: x[1], reverse=True)
                        for g, tf in candidates[:config.DEFAULT_ENSURE_PHRASES_K]:
                            n_words = g.count(" ") + 1
                            boost = config.DEFAULT_DESC_PHRASE_BOOST_BIGRAM if n_words == 2 else (
                                config.DEFAULT_DESC_PHRASE_BOOST_TRIGRAM if n_words == 3 else 1.0
                            )
                            # fallback score uses TF with a small phrase boost (no IDF)
                            desc_tfidf[g] = tf * boost

                # Name terms
                name_terms = sub.name_terms
                name_scores = score_name_terms(name_terms)
                # Full phrase from name (for casing and emphasis)
                full_lower, full_cased = extract_name_full_phrase(sub.name)
                # Ensure full phrase is present with strong weight so it surfaces prominently
                if full_lower:
                    n_words_full = full_lower.count(" ") + 1
                    if n_words_full >= 3:
                        name_scores[full_lower] += 2.5
                    elif n_words_full == 2:
                        name_scores[full_lower] += 1.5
                    else:
                        name_scores[full_lower] += 1.0

                # Precompute anchors for composition and display recasing
                display_key = subreddit_display_key(sub.name, sub.url)
                canon_key = canonicalize_subreddit_key(sub.name, sub.url)
                anchor_title_for_display = ""
                anchor_phrase_lower = ""

                # Posts TF-IDF (optional)
                posts_scores: Counter = Counter()
                composed_scores: Counter = Counter()
                if frontpage_index and posts_weight > 0.0:
                    canon = canonicalize_subreddit_key(sub.name, sub.url)
                    posts_path = frontpage_index.get(canon)

                    # Fallback path if not in index (derive from name)
                    if not posts_path:
                        folder = subreddit_folder_from_name(sub.name)
                        candidate = os.path.join("output", "subreddits", folder, "frontpage.json")
                        if os.path.exists(candidate):
                            posts_path = candidate

                    if posts_path:
                        if posts_path in frontpage_cache:
                            fp_data = frontpage_cache[posts_path]
                        else:
                            try:
                                with open(posts_path, "r", encoding="utf-8") as f:
                                    fp_data = json.load(f)
                                frontpage_cache[posts_path] = fp_data
                            except Exception:
                                fp_data = None

                        if fp_data:
                            posts_scores, posts_local_tf = compute_posts_tfidf_for_frontpage(
                                fp_data,
                                posts_docfreq,
                                posts_total_docs,
                                max_ngram,
                                min_df_bigram,
                                min_df_trigram,
                                posts_halflife_days,
                                posts_ensure_k,
                                posts_extra_stopwords_set,
                                posts_phrase_stoplist_set,
                                posts_phrase_boost_bigram,
                                posts_phrase_boost_trigram,
                                posts_drop_generic_unigrams,
                                posts_generic_df_ratio,
                                idf_power=posts_idf_power,
                                engagement_alpha=posts_engagement_alpha,
                            )

                            # Anchored variants for generics
                            if posts_anchor_generics:
                                anchor_tokens = [t for t in name_terms if t] or []
                                anchor = ""
                                # choose primary anchor token: prefer whole subreddit token if present in terms
                                if anchor_tokens:
                                    # pick the longest token that is a single word (avoid bigrams)
                                    single_tokens = [t for t in anchor_tokens if " " not in t]
                                    if single_tokens:
                                        anchor = max(single_tokens, key=len)
                                if not anchor:
                                    anchor = canon  # fallback to canonical key
                                if anchor:
                                    posts_scores = apply_anchored_variants_for_generic_posts_terms(
                                        posts_scores,
                                        posts_docfreq,
                                        posts_total_docs,
                                        anchor,
                                        posts_generic_df_ratio,
                                        replace_original_generic=posts_replace_generic_with_anchored,
                                    )
    
                                # Compose theme-anchored variants from top seed phrases
                                composed_scores = Counter()
                                if compose_anchor_posts and (posts_scores or posts_local_tf):
                                    title_str = ""
                                    if compose_anchor_use_title:
                                        try:
                                            title_str = ((fp_data.get("meta") or {}).get("title") or "").strip()
                                        except Exception:
                                            title_str = ""
                                    if title_str:
                                        anchor_title_for_display = title_str
                                        anchor_phrase_lower = _normalize_anchor_phrase_from_title(title_str)

                                    # Build seed base according to requested source
                                    if compose_seed_source == "posts_local_tf":
                                        seed_base = posts_local_tf
                                    elif compose_seed_source == "posts_tfidf":
                                        seed_base = posts_scores
                                    else:
                                        # hybrid: prefer TF-IDF where available, otherwise fallback to local TF
                                        seed_base = Counter(posts_scores)
                                        for g, tf in posts_local_tf.items():
                                            if g not in seed_base:
                                                seed_base[g] = float(tf)

                                    # Optional embedding-based seed rerank to prefer semantically on-theme phrases (e.g., oil change)
                                    seed_scored = seed_base
                                    try:
                                        theme_text_comp = _build_theme_text(full_lower, desc_tfidf, posts_theme_top_desc_k)
                                    except Exception:
                                        theme_text_comp = ""
                                    if compose_seed_embed and theme_text_comp:
                                        seed_scored = _compose_rank_seeds_with_embed(seed_base, theme_text_comp, embed_model, compose_seed_embed_alpha)

                                    composed_from_top = compose_theme_anchored_from_posts(
                                        seed_scored,
                                        posts_scores,
                                        anchor_phrase_lower or "",
                                        canon_key or "",
                                        compose_anchor_top_m,
                                        compose_anchor_include_unigrams,
                                        compose_anchor_max_final_words,
                                        compose_anchor_multiplier,
                                        compose_anchor_score_mode,
                                        compose_anchor_alpha,
                                        compose_anchor_floor,
                                        compose_anchor_cap,
                                        compose_anchor_max_per_sub,
                                        compose_anchor_min_base_score,
                                        compose_anchor_max_ratio,
                                        posts_docfreq,
                                        posts_total_docs,
                                        posts_idf_power,
                                    )
                                    composed_scores = Counter()
                                    composed_scores.update(composed_from_top)
                                else:
                                    composed_scores = Counter()
    
                    # Theme alignment penalty for posts-only terms with no overlap to subreddit theme
                if posts_scores:
                    theme_tokens: Set[str] = set()
                    # tokens from name terms
                    for nt in name_terms:
                        for tok in nt.split():
                            if tok:
                                theme_tokens.add(tok)
                    # top-K description terms
                    if desc_tfidf:
                        for g, _ in sorted(desc_tfidf.items(), key=lambda x: x[1], reverse=True)[:max(0, posts_theme_top_desc_k)]:
                            for tok in g.split():
                                if tok:
                                    theme_tokens.add(tok)
                    if theme_tokens:
                        for term in list(posts_scores.keys()):
                            term_tokens = set(term.split())
                            if not (term_tokens & theme_tokens):
                                posts_scores[term] *= max(0.0, min(1.0, posts_theme_penalty))

                # Merge scores
                merged = merge_sources([
                    (desc_tfidf, desc_weight, "description"),
                    (name_scores, name_weight, "name"),
                    (posts_scores, posts_weight, "posts"),
                    (composed_scores, (posts_composed_weight if posts_composed_weight is not None else posts_weight), "posts_composed"),
                ])

                # Embedding-based rerank (optional): theme = whole name phrase + top description terms
                if embed_rerank:
                    theme_text = _build_theme_text(full_lower, desc_tfidf, posts_theme_top_desc_k)
                    merged = embed_rerank_terms(
                        merged,
                        theme_text=theme_text,
                        model_name=embed_model,
                        alpha=embed_alpha,
                        k_terms=embed_k_terms,
                        candidate_pool=embed_candidate_pool,
                    )

                ranked = normalize_weights(merged)
                top = ranked[:topk]
                # Ensure the whole subreddit name phrase is present in Top-K if available
                if full_lower and (" " in full_lower):
                    terms_in_top = {t for (t, _, _, _) in top}
                    if full_lower not in terms_in_top and full_lower in merged:
                        total_score = sum(v for v, _ in merged.values()) or 1.0
                        sc, src = merged[full_lower]
                        ensured = (full_lower, sc / total_score, sc, src)
                        if len(top) < topk:
                            top.append(ensured)
                        else:
                            top[-1] = ensured
                        # Keep ordering by raw score
                        top.sort(key=lambda x: x[2], reverse=True)

                rec = {
                    "community_id": sub.community_id,
                    "name": sub.name,
                    "url": sub.url,
                    "rank": sub.rank,
                    "subscribers_count": sub.subscribers_count,
                    "keywords": [
                        {
                            "term": (
                                full_cased
                                if (t == full_lower and src != "description" and " " in t)
                                else recase_anchored_display(t, canon_key, display_key, anchor_phrase_lower, anchor_title_for_display)
                            ),
                            "weight": round(w, 6),
                            "score": round(s, 6),
                            "source": src,
                        }
                        for (t, w, s, src) in top
                    ],
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                count_written += 1

        print(f"[done] wrote {count_written} records to {outp}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Extract subreddit keywords with TF-IDF from descriptions, names, and optional frontpage posts.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input-file", type=str, help="Path to one page JSON file")
    g.add_argument("--input-glob", type=str, help="Glob for many page JSON files, e.g., 'output/pages/page_*.json'")
    ap.add_argument("--output-dir", type=str, default=config.DEFAULT_OUTPUT_DIR, help="Directory for output JSONL files")
    ap.add_argument("--topk", type=int, default=config.DEFAULT_TOPK, help="Top-K keywords per subreddit")
    ap.add_argument("--max-ngram", type=int, default=config.DEFAULT_MAX_NGRAM, help="Max n-gram length for TF-IDF")
    ap.add_argument("--name-weight", type=float, default=config.DEFAULT_NAME_WEIGHT, help="Weight multiplier for name-derived terms")
    ap.add_argument("--desc-weight", type=float, default=config.DEFAULT_DESC_WEIGHT, help="Weight multiplier for description TF-IDF")
    ap.add_argument("--min-df-bigram", type=int, default=2, help="Minimum document frequency to keep bigrams")
    ap.add_argument("--min-df-trigram", type=int, default=2, help="Minimum document frequency to keep trigrams")

    # Posts integration CLI
    ap.add_argument("--frontpage-glob", type=str, default=None, help="Glob for frontpage JSON files, e.g., 'output/subreddits/*/frontpage.json'")
    ap.add_argument("--posts-weight", type=float, default=config.DEFAULT_POSTS_WEIGHT, help="Weight multiplier for posts-derived scores (applied in merge)")
    ap.add_argument("--posts-composed-weight", type=float, default=None, help="Weight multiplier for composed posts terms; if omitted, defaults to --posts-weight")
    ap.add_argument("--posts-halflife-days", type=float, default=config.DEFAULT_POSTS_HALFLIFE_DAYS, help="Recency halflife in days for posts weighting")
    ap.add_argument("--posts-generic-df-ratio", type=float, default=config.DEFAULT_POSTS_GENERIC_DF_RATIO, help="DF ratio threshold for considering a posts term 'generic'")
    ap.add_argument("--posts-ensure-k", type=int, default=config.DEFAULT_ENSURE_PHRASES_K, help="Ensure up to K local bigrams/trigrams per frontpage even if pruned by global DF")
    ap.add_argument("--posts-stopwords-extra", type=str, default=None, help="Path to newline-delimited file of extra stopwords to apply only to posts tokenization")
    ap.add_argument("--posts-phrase-boost-bigram", type=float, default=config.DEFAULT_POSTS_PHRASE_BOOST_BIGRAM, help="Phrase boost for bigrams in posts TF-IDF")
    ap.add_argument("--posts-phrase-boost-trigram", type=float, default=config.DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM, help="Phrase boost for trigrams in posts TF-IDF")
    ap.add_argument("--posts-drop-generic-unigrams", action="store_true", help="Drop unigram posts terms whose global DF ratio >= --posts-generic-df-ratio")
    ap.add_argument("--posts-theme-penalty", type=float, default=0.65, help="Multiplier to apply to posts terms with zero overlap to subreddit theme tokens (name + top description terms)")
    ap.add_argument("--posts-theme-top-desc-k", type=int, default=6, help="How many top description terms to include when forming the theme token set")

    # New scoring controls
    ap.add_argument("--desc-idf-power", type=float, default=config.DEFAULT_DESC_IDF_POWER, help="Raise description IDF to this power (0..1 dampens DF influence)")
    ap.add_argument("--posts-idf-power", type=float, default=config.DEFAULT_POSTS_IDF_POWER, help="Raise posts IDF to this power (0..1 dampens DF influence)")
    ap.add_argument("--posts-engagement-alpha", type=float, default=config.DEFAULT_POSTS_ENGAGEMENT_ALPHA, help="Blend factor for engagement in posts TF (0=ignore engagement, 1=fully weight)")

    # Embedding rerank
    ap.add_argument("--embed-rerank", action="store_true", help="Enable embedding-based reranking of terms for semantic alignment to subreddit theme")
    ap.add_argument("--embed-model", type=str, default=config.DEFAULT_EMBED_MODEL, help="SentenceTransformers model id (e.g., 'BAAI/bge-small-en-v1.5' or 'BAAI/bge-m3')")
    ap.add_argument("--embed-alpha", type=float, default=config.DEFAULT_EMBED_ALPHA, help="Blend factor for embedding similarity contribution")
    ap.add_argument("--embed-k-terms", type=int, default=config.DEFAULT_EMBED_K_TERMS, help="Rerank top-K terms by embeddings")
    ap.add_argument("--embed-candidate-pool", type=str, default=config.DEFAULT_EMBED_CANDIDATE_POOL, choices=["union", "posts", "posts_composed", "desc", "non_name"], help="Subset of terms eligible for reranking")

    ap.add_argument("--posts-phrase-stoplist", type=str, default=None, help="Path to newline-delimited file of phrases (bigrams/trigrams) to exclude from posts tokenization/DF")
    ap.add_argument("--posts-replace-generic-with-anchored", action="store_true", help="When anchoring generic uni/bi-grams, drop the original unanchored term")
    ap.add_argument("--no-posts-anchor-generics", action="store_true", help="Disable adding anchored variants for generic posts terms")

    # Composed anchored variants
    ap.add_argument("--no-compose-anchor-posts", action="store_true", help="Disable composing theme-anchored variants from top posts phrases")
    ap.add_argument("--compose-anchor-multiplier", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_MULTIPLIER, help="Score multiplier applied to composed variants relative to source post phrase")
    ap.add_argument("--compose-anchor-top-m", type=int, default=config.DEFAULT_COMPOSE_ANCHOR_TOP_M, help="Consider top-M posts phrases (by score) for composing anchored variants")
    ap.add_argument("--compose-anchor-include-unigrams", action="store_true", help="Allow composing anchored variants from unigram posts terms")
    ap.add_argument("--compose-anchor-max-final-words", type=int, default=config.DEFAULT_COMPOSE_ANCHOR_MAX_FINAL_WORDS, help="Maximum words allowed in the final composed term")
    ap.add_argument("--no-compose-anchor-use-title", action="store_true", help="Do not use frontpage meta.title for anchor phrase; only use subreddit token")
    ap.add_argument("--compose-seed-source", type=str, default="hybrid", choices=["posts_tfidf", "posts_local_tf", "hybrid"], help="Seed source for composition (TF-IDF, local TF, or hybrid)")
    ap.add_argument("--compose-seed-embed", action="store_true", help="Use embedding similarity to rerank local seeds for composition")
    ap.add_argument("--compose-seed-embed-alpha", type=float, default=config.DEFAULT_COMPOSE_SEED_EMBED_ALPHA, help="Blend for seed rerank: 0=count-only, 1=embedding-only")
    ap.add_argument("--compose-anchor-score-mode", type=str, default=config.DEFAULT_COMPOSE_ANCHOR_SCORE_MODE, choices=["fraction","idf_blend"], help="Scoring mode for composed variants")
    ap.add_argument("--compose-anchor-alpha", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_ALPHA, help="Alpha for IDF blend (0..1)")
    ap.add_argument("--compose-anchor-floor", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_FLOOR, help="Floor for composed factor to avoid suppression (>=1.0)")
    ap.add_argument("--compose-anchor-cap", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_CAP, help="Cap for composed factor to prevent runaway boosts")
    ap.add_argument("--compose-anchor-max-per-sub", type=int, default=config.DEFAULT_COMPOSE_ANCHOR_MAX_PER_SUB, help="Maximum number of composed terms to generate per subreddit (0=disable cap)")
    ap.add_argument("--compose-anchor-min-base-score", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_MIN_BASE_SCORE, help="Minimum TF-IDF score of seed required to compose")
    ap.add_argument("--compose-anchor-max-ratio", type=float, default=config.DEFAULT_COMPOSE_ANCHOR_MAX_RATIO, help="Maximum composed/base score ratio before rerank (0=disabled)")
    # Deprecated editorial whitelist (ignored in v2, kept for CLI compatibility)
    ap.add_argument("--compose-subjects-path", type=str, default=None, help="Deprecated: subject whitelist is ignored")
    ap.add_argument("--compose-subjects-bonus", type=float, default=config.DEFAULT_COMPOSE_SUBJECTS_BONUS, help="Deprecated: unused")

    args = ap.parse_args()

    if args.input_file:
        inputs = [args.input_file]
    else:
        inputs = sorted(glob(args.input_glob))

    # Guard against huge memory by processing only selected files; each page file is small.
    process_inputs(
        input_paths=inputs,
        output_dir=args.output_dir,
        topk=args.topk,
        max_ngram=args.max_ngram,
        name_weight=args.name_weight,
        desc_weight=args.desc_weight,
        min_df_bigram=args.min_df_bigram,
        min_df_trigram=args.min_df_trigram,
        frontpage_glob=args.frontpage_glob,
        posts_weight=args.posts_weight,
        posts_composed_weight=args.posts_composed_weight,
        posts_halflife_days=args.posts_halflife_days,
        posts_generic_df_ratio=args.posts_generic_df_ratio,
        posts_ensure_k=args.posts_ensure_k,
        posts_stopwords_extra_path=args.posts_stopwords_extra,
        posts_anchor_generics=(not args.no_posts_anchor_generics),
        posts_phrase_boost_bigram=args.posts_phrase_boost_bigram,
        posts_phrase_boost_trigram=args.posts_phrase_boost_trigram,
        posts_drop_generic_unigrams=args.posts_drop_generic_unigrams,
        posts_theme_penalty=args.posts_theme_penalty,
        posts_theme_top_desc_k=args.posts_theme_top_desc_k,
        compose_anchor_posts=(not args.no_compose_anchor_posts),
        compose_anchor_multiplier=args.compose_anchor_multiplier,
        compose_anchor_top_m=args.compose_anchor_top_m,
        compose_anchor_include_unigrams=args.compose_anchor_include_unigrams,
        compose_anchor_max_final_words=args.compose_anchor_max_final_words,
        compose_anchor_use_title=(not args.no_compose_anchor_use_title),
        compose_subjects_path=args.compose_subjects_path,
        compose_subjects_bonus=args.compose_subjects_bonus,
        embed_rerank=args.embed_rerank,
        embed_model=args.embed_model,
        embed_alpha=args.embed_alpha,
        embed_k_terms=args.embed_k_terms,
        # new
        desc_idf_power=args.desc_idf_power,
        posts_idf_power=args.posts_idf_power,
        posts_engagement_alpha=args.posts_engagement_alpha,
        compose_seed_source=args.compose_seed_source,
        compose_seed_embed=args.compose_seed_embed,
        compose_seed_embed_alpha=args.compose_seed_embed_alpha,
        embed_candidate_pool=args.embed_candidate_pool,
        compose_anchor_score_mode=args.compose_anchor_score_mode,
        compose_anchor_alpha=args.compose_anchor_alpha,
        compose_anchor_floor=args.compose_anchor_floor,
        compose_anchor_cap=args.compose_anchor_cap,
        compose_anchor_max_per_sub=args.compose_anchor_max_per_sub,
        compose_anchor_min_base_score=args.compose_anchor_min_base_score,
        compose_anchor_max_ratio=args.compose_anchor_max_ratio,
    )


if __name__ == "__main__":
    main()