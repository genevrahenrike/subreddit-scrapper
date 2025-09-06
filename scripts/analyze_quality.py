#!/usr/bin/env python3
"""
Quality analyzer for subreddit keyword extraction outputs.

Reads page_*.keywords.jsonl files and reports:
- Phrase share (unigram/bigram/trigram+ distribution) in Top-K
- Source mix shares (name/description/posts/posts_composed)
- Posts thematic alignment via token overlap with theme tokens (name + top desc terms)
- Presence and ranks of posts_composed (composed/anchored) terms
- Name phrase coverage (any multi-word name-derived term present)
- Generic unigram share (STOPWORDS and optional Zipf>=threshold if wordfreq is available)
- Anchored-by-token rate (terms starting with canonical subreddit token)
- Score distribution stats for Top-K
- Top off-theme posts terms (for diagnostics)

Usage:
  python3 scripts/analyze_quality.py --input-dir output/keywords_10k_v22 --max-pages 50 --seed 42
  python3 scripts/analyze_quality.py --input-dir output/keywords_10k_v22_embed --max-pages 50 --seed 42
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
from glob import glob
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from collections import Counter

# Project imports (safe when run from repo root)
import sys
sys.path.insert(0, str(Path(".").resolve()))

# Import curated stopwords and helpers; fall back if unavailable
try:
    from src.keyword_extraction.constants import STOPWORDS as CURATED_STOPWORDS
except Exception:
    CURATED_STOPWORDS = set()

# Optional helpers for better tokenization of names
try:
    from src.keyword_extraction.subreddit_data import canonicalize_subreddit_key
except Exception:
    def canonicalize_subreddit_key(name: str, url: str) -> str:
        if name:
            m = re.search(r"r/([^/\s]+)", name, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip("/").lower()
            name2 = name.strip().strip("/").lower()
            return re.sub(r"^r/", "", name2)
        if url:
            m = re.search(r"/r/([^/\s]+)/?", url, flags=re.IGNORECASE)
            if m:
                return m.group(1).lower()
        return ""

try:
    from src.keyword_extraction.text_utils import split_camel_and_digits as _split_camel_and_digits
except Exception:
    def _split_camel_and_digits(token: str) -> List[str]:
        if not token:
            return []
        # Basic fallback split
        parts = re.sub(r"[^0-9A-Za-z]+", " ", token).strip()
        return re.split(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])|\s+", parts)

try:
    from wordfreq import zipf_frequency as _zipf_frequency  # type: ignore
    _HAS_WORDFREQ = True
except Exception:
    _HAS_WORDFREQ = False
    def _zipf_frequency(_: str, __: str) -> float:
        return float("-inf")


def list_jsonl_files(input_dir: str, pattern: str) -> List[str]:
    return sorted(glob(os.path.join(input_dir, pattern)))


def choose_files(files: List[str], max_pages: int, seed: int) -> List[str]:
    if max_pages <= 0 or max_pages >= len(files):
        return files
    rng = random.Random(seed)
    files_copy = files[:]
    rng.shuffle(files_copy)
    return sorted(files_copy[:max_pages])


def tokenize_simple(text: str) -> List[str]:
    if not text:
        return []
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^0-9\w\s]+", " ", text, flags=re.UNICODE)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text.split() if text else []


def name_theme_tokens(name: str, url: str) -> List[str]:
    """
    Build tokens from canonical subreddit key using camel/digit splits.
    """
    key = canonicalize_subreddit_key(name, url)
    toks: List[str] = []
    for part in _split_camel_and_digits(key):
        part = (part or "").strip().lower()
        if part:
            toks.append(part)
    return toks


def theme_tokens_from_record(rec: dict, top_desc_k: int = 6) -> set:
    """
    Approximate theme tokens using:
    - tokens from subreddit canonical key
    - tokens from top-K description-sourced keywords (up to k)
    """
    toks = set(name_theme_tokens(rec.get("name", ""), rec.get("url", "")))
    kws = rec.get("keywords") or []
    # Take top description terms by score order as listed (already sorted)
    count_added = 0
    for kw in kws:
        src = (kw.get("source") or "")
        if "description" in src:
            for t in tokenize_simple(kw.get("term", "")):
                toks.add(t)
            count_added += 1
            if count_added >= max(0, top_desc_k):
                break
    return toks


def is_generic_unigram(term: str, zipf_threshold: float) -> bool:
    tl = (term or "").strip().lower()
    if not tl or " " in tl:
        return False
    if tl in CURATED_STOPWORDS:
        return True
    if _HAS_WORDFREQ:
        try:
            return _zipf_frequency(tl, "en") >= zipf_threshold
        except Exception:
            return False
    return False


def _top_n(counter: Counter, n: int) -> List[Tuple[str, int]]:
    if not counter:
        return []
    return [(k, v) for k, v in counter.most_common(n)]


def analyze_files(files: List[str], zipf_threshold: float) -> Dict[str, object]:
    total_records = 0
    total_terms = 0
    ngram_counts = {"uni": 0, "bi": 0, "tri_plus": 0}
    # Per-source presence counts (count a term once per base source it includes)
    source_counts = {"name": 0, "description": 0, "posts": 0, "posts_composed": 0}
    # Posts thematic overlap
    posts_terms_total = 0
    posts_terms_overlap = 0
    # Off-theme diagnostics (posts-only)
    offtheme_terms = Counter()
    offtheme_uni = Counter()
    offtheme_bi = Counter()
    offtheme_tri = Counter()
    # Composed presence and ranks
    composed_terms_total = 0
    composed_ranks: List[int] = []
    # Name phrase coverage (proxy: any multi-word name-sourced term in Top-K)
    records_with_name_multi = 0
    # Generic unigram share
    generic_unigrams = 0
    # Anchored by token (starts with canonical key)
    anchored_token_terms = 0
    # Score stats (Top-K only)
    scores: List[float] = []

    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue

                kws: List[dict] = rec.get("keywords") or []
                if not kws:
                    continue
                total_records += 1

                # Build theme tokens (name + top desc)
                theme = theme_tokens_from_record(rec, top_desc_k=6)
                canon = canonicalize_subreddit_key(rec.get("name", ""), rec.get("url", ""))

                # Per-record flags
                has_name_multi = False

                for idx, kw in enumerate(kws):
                    term = kw.get("term", "") or ""
                    src = (kw.get("source") or "")
                    score_val = float(kw.get("score") or 0.0)
                    n_words = len(tokenize_simple(term))
                    total_terms += 1
                    scores.append(score_val)

                    # n-gram distribution
                    if n_words == 1:
                        ngram_counts["uni"] += 1
                    elif n_words == 2:
                        ngram_counts["bi"] += 1
                    else:
                        ngram_counts["tri_plus"] += 1

                    # source mix (increment for each base source present)
                    parts = set(src.split("+"))
                    for base in ("name", "description", "posts", "posts_composed"):
                        if base in parts:
                            source_counts[base] += 1

                    # name multi-word presence proxy
                    if ("name" in parts) and (n_words >= 2):
                        has_name_multi = True

                    # posts thematic overlap (for posts-only; composed handled separately)
                    if ("posts" in parts) and ("posts_composed" not in parts):
                        posts_terms_total += 1
                        term_toks = set(tokenize_simple(term))
                        if term_toks & theme:
                            posts_terms_overlap += 1
                        else:
                            offtheme_terms[term] += 1
                            if n_words == 1:
                                offtheme_uni[term] += 1
                            elif n_words == 2:
                                offtheme_bi[term] += 1
                            else:
                                offtheme_tri[term] += 1

                    if "posts_composed" in parts:
                        composed_terms_total += 1
                        composed_ranks.append(idx + 1)

                    # generic unigram
                    if n_words == 1 and is_generic_unigram(term, zipf_threshold):
                        generic_unigrams += 1

                    # anchored by canonical token
                    if canon and term.lower().startswith(canon + " "):
                        anchored_token_terms += 1

                if has_name_multi:
                    records_with_name_multi += 1

    # Aggregations
    def share(x: int, y: int) -> float:
        return (float(x) / float(y)) if y else 0.0

    ngram_shares = {
        "unigram_share": share(ngram_counts["uni"], total_terms),
        "bigram_share": share(ngram_counts["bi"], total_terms),
        "trigramplus_share": share(ngram_counts["tri_plus"], total_terms),
        "phrase_share": share(ngram_counts["bi"] + ngram_counts["tri_plus"], total_terms),
    }
    source_shares = {k: share(v, total_terms) for k, v in source_counts.items()}
    posts_offtheme_rate = share(posts_terms_total - posts_terms_overlap, posts_terms_total)
    composed_presence_rate = share(1 if composed_terms_total > 0 else 0, 1)  # corpus-level flag (for symmetry)
    name_multi_presence_rate = share(records_with_name_multi, total_records)
    generic_unigram_share = share(generic_unigrams, total_terms)
    anchored_token_share = share(anchored_token_terms, total_terms)

    # Score quantiles (guard small counts)
    score_stats = {}
    if scores:
        s_sorted = sorted(scores)
        def pct(p: float) -> float:
            if not s_sorted:
                return 0.0
            k = max(0, min(len(s_sorted) - 1, int(round(p * (len(s_sorted) - 1)))))
            return float(s_sorted[k])
        mean_val = statistics.fmean(scores)
        stdev_val = statistics.pstdev(scores) if len(scores) > 1 else 0.0
        score_stats = {
            "count": len(scores),
            "mean": mean_val,
            "stdev": stdev_val,
            "p50": pct(0.50),
            "p75": pct(0.75),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "min": s_sorted[0],
            "max": s_sorted[-1],
        }

    # Composed ranks summary
    comp_rank_stats = {}
    if composed_ranks:
        comp_rank_stats = {
            "count": len(composed_ranks),
            "mean": statistics.fmean(composed_ranks),
            "min": min(composed_ranks),
            "max": max(composed_ranks),
            "p50": float(sorted(composed_ranks)[len(composed_ranks)//2]),
        }

    # Top off-theme posts terms (helps tune stoplists/generic pruning/theme alignment)
    offtheme_summary = {
        "posts_terms_total": posts_terms_total,
        "posts_terms_offtheme": posts_terms_total - posts_terms_overlap,
        "top_terms": _top_n(offtheme_terms, 40),
        "top_unigrams": _top_n(offtheme_uni, 30),
        "top_bigrams": _top_n(offtheme_bi, 30),
        "top_trigrams": _top_n(offtheme_tri, 30),
    }

    summary = {
        "files": len(files),
        "records": total_records,
        "terms_total": total_terms,
        "ngram_shares": ngram_shares,
        "source_shares": source_shares,
        "posts_terms_total": posts_terms_total,
        "posts_offtheme_rate": posts_offtheme_rate,
        "composed_terms_total": composed_terms_total,
        "composed_rank_stats": comp_rank_stats,
        "name_multi_presence_rate": name_multi_presence_rate,
        "generic_unigram_share": generic_unigram_share,
        "anchored_token_share": anchored_token_share,
        "score_stats": score_stats,
        "offtheme_posts_terms": offtheme_summary,
        "notes": {
            "zipf_used": _HAS_WORDFREQ,
            "zipf_threshold": zipf_threshold,
            "curated_stopwords_size": len(CURATED_STOPWORDS),
        }
    }
    return summary


def main():
    ap = argparse.ArgumentParser(description="Analyze quality metrics for keyword outputs")
    ap.add_argument("--input-dir", required=True, help="Directory containing page_*.keywords.jsonl files")
    ap.add_argument("--pattern", default="page_*.keywords.jsonl", help="Filename glob pattern")
    ap.add_argument("--max-pages", type=int, default=50, help="Max number of files to sample (0 = all)")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    ap.add_argument("--zipf-threshold", type=float, default=5.0, help="Zipf threshold for generic unigram check (if wordfreq available)")
    args = ap.parse_args()

    files = list_jsonl_files(args.input_dir, args.pattern)
    if not files:
        print(json.dumps({"error": f"No files matched in {args.input_dir}/{args.pattern}"}))
        return
    sel = choose_files(files, args.max_pages, args.seed)
    summary = analyze_files(sel, args.zipf_threshold)
    summary["scanned_files"] = sel
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()