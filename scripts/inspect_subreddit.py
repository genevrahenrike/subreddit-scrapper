#!/usr/bin/env python3
"""
Inspect a single subreddit across keyword outputs and its frontpage source.

Given a canonical subreddit key (e.g., "cx5"), this script:
- Finds the matching record in a directory of page_*.keywords.jsonl files
- Prints top-K keywords with scores and sources, plus per-source counts
- Highlights posts_composed terms and maps them back to their seed posts terms (ratio, rank)
- Loads output/subreddits/<Folder>/frontpage.json (if present) and shows:
  - meta.title (anchor), top posts by score/comments
  - Presence of key seeds (e.g., "oil change") in local grams (bigrams/trigrams)
- Computes theme tokens (name + top description terms) and overlap stats

Usage:
  python3 scripts/inspect_subreddit.py --sub cx5 --input-dir output/keywords_10k_v22_embed --k 40
  python3 scripts/inspect_subreddit.py --sub ukpersonalfinance --input-dir output/keywords_10k_v22 --k 30

Notes:
- Works with both baseline and embed outputs.
- Safe to run from repo root.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from glob import glob
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import project helpers
try:
    from src.keyword_extraction.subreddit_data import (
        canonicalize_subreddit_key,
        subreddit_folder_from_name,
    )
    from src.keyword_extraction.text_utils import tokenize_simple, tokens_to_ngrams, split_camel_and_digits
    from src.keyword_extraction.composition import _normalize_anchor_phrase_from_title
except Exception:
    # Minimal fallbacks if imports fail (shouldn't be needed in normal repo usage)
    def canonicalize_subreddit_key(name: str, url: str) -> str:
        if name:
            m = re.search(r"r/([^/\\s]+)", name, flags=re.IGNORECASE)
            if m:
                return m.group(1).strip("/").lower()
            name2 = name.strip().strip("/").lower()
            return re.sub(r"^r/", "", name2)
        if url:
            m = re.search(r"/r/([^/\\s]+)/?", url, flags=re.IGNORECASE)
            if m:
                return m.group(1).lower()
        return ""

    def subreddit_folder_from_name(name: str) -> str:
        n = re.sub(r"^r/+", "", (name or "").strip(), flags=re.IGNORECASE)
        return n.strip("/")

    def tokenize_simple(text: str) -> List[str]:
        if not text:
            return []
        text = text.replace("_", " ").replace("-", " ")
        text = re.sub(r"[^0-9\\w\\s]+", " ", text, flags=re.UNICODE)
        text = text.replace("_", " ")
        text = re.sub(r"\\s+", " ", text.lower()).strip()
        return text.split() if text else []

    def split_camel_and_digits(token: str) -> List[str]:
        if not token:
            return []
        parts = re.split(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])", token)
        out: List[str] = []
        for p in parts:
            out.extend(re.split(r"[^0-9A-Za-z]+", p))
        return [x for x in out if x]

    def _normalize_anchor_phrase_from_title(title: str) -> str:
        return " ".join(tokenize_simple(title))

    def tokens_to_ngrams(tokens: List[str], max_n: int) -> Counter:
        grams = Counter()
        n = len(tokens)
        for k in range(1, max_n + 1):
            if n < k:
                break
            for i in range(0, n - k + 1):
                gram = " ".join(tokens[i : i + k])
                if gram:
                    grams[gram] += 1
        return grams


def _find_record(input_dir: str, subkey: str) -> Tuple[Optional[dict], Optional[str]]:
    """Scan page_*.keywords.jsonl to find the record with canonical key == subkey."""
    paths = sorted(glob(str(Path(input_dir) / "page_*.keywords.jsonl")))
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    key = canonicalize_subreddit_key(rec.get("name", ""), rec.get("url", ""))
                    if key == subkey:
                        return rec, p
        except Exception:
            continue
    return None, None


def _build_theme_tokens(rec: dict, top_desc_k: int = 6) -> set:
    """Tokens from canonical subreddit key + tokens from top-K description terms (by order)."""
    key = canonicalize_subreddit_key(rec.get("name", ""), rec.get("url", ""))
    toks = set()
    for part in split_camel_and_digits(key):
        part = (part or "").strip().lower()
        if part:
            toks.add(part)
    for kw in (rec.get("keywords") or []):
        if "description" in (kw.get("source") or ""):
            for t in tokenize_simple(kw.get("term", "")):
                toks.add(t)
            if len(toks) >= top_desc_k + len(key):  # rough limiter
                break
    return toks


def _load_frontpage(rec: dict, frontpage_root: str) -> Tuple[Optional[dict], Optional[str]]:
    folder = subreddit_folder_from_name(rec.get("name", ""))
    if not folder:
        return None, None
    path = Path(frontpage_root) / folder / "frontpage.json"
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, str(path)
    except Exception:
        return None, None


def _top_posts(fp: dict, limit: int = 8) -> List[dict]:
    posts = (fp or {}).get("posts") or []
    # Sort by (score, comments) desc as a proxy
    posts_sorted = sorted(posts, key=lambda p: (int(p.get("score") or 0), int(p.get("comments") or 0)), reverse=True)
    return posts_sorted[: max(0, limit)]


def _local_grams_from_frontpage(fp: dict, max_ngram: int = 3, include_preview: bool = False) -> Counter:
    posts = (fp or {}).get("posts") or []
    grams = Counter()
    for p in posts:
        title = (p.get("title") or "").strip()
        preview = (p.get("content_preview") or "").strip()
        parts = [title]
        if include_preview and preview:
            parts.append(preview)
        toks = tokenize_simple(" ".join([x for x in parts if x]))
        grams.update(tokens_to_ngrams(toks, max_ngram))
    return grams


def main():
    ap = argparse.ArgumentParser(description="Inspect a single subreddit across keyword outputs and frontpage source.")
    ap.add_argument("--sub", required=True, help="Canonical subreddit key (e.g., cx5)")
    ap.add_argument("--input-dir", required=True, help="Directory containing page_*.keywords.jsonl")
    ap.add_argument("--frontpage-root", default="output/subreddits", help="Root directory for frontpage.json folders")
    ap.add_argument("--k", type=int, default=40, help="Top-K to display")
    ap.add_argument("--include-preview", action="store_true", help="Include content_preview when scanning local grams")
    ap.add_argument("--show-seed-map", action="store_true", help="Show mapping from posts_composed terms to their seeds with ratios")
    args = ap.parse_args()

    subkey = (args.sub or "").strip().lower()
    rec, src_path = _find_record(args.input_dir, subkey)
    if not rec:
        print(f"[inspect] Not found: sub={subkey} in input-dir={args.input_dir}")
        return

    print(f"=== Subreddit: {rec.get('name')} | url={rec.get('url')} ===")
    print(f"rank={rec.get('rank')} subscribers={rec.get('subscribers_count')}")
    print(f"source_file={src_path}")

    # Theme tokens
    theme = _build_theme_tokens(rec, top_desc_k=6)
    print(f"theme_tokens({len(theme)}): {sorted(theme)}")

    kws = rec.get("keywords") or []
    topk = kws[: max(0, args.k)]
    # Per-source counters
    src_counts = Counter()
    for kw in topk:
        parts = set((kw.get("source") or "").split("+"))
        for base in ("name", "description", "posts", "posts_composed"):
            if base in parts:
                src_counts[base] += 1

    print("\n-- Top Keywords --")
    for i, kw in enumerate(topk, start=1):
        t = kw.get("term", "")
        sc = kw.get("score")
        src = kw.get("source")
        print(f"{i:2d}. {t}  | score={sc} | src={src}")

    print("\n-- Source mix (Top-K) --")
    total_top = max(1, len(topk))
    for base in ("name", "description", "posts", "posts_composed"):
        share = src_counts[base] / total_top
        print(f"{base:15s}: {src_counts[base]:3d} ({share:.2%})")

    # Frontpage and anchor info
    fp, fp_path = _load_frontpage(rec, args.frontpage_root)
    anchor_title = ""
    anchor_phrase = ""
    if fp:
        meta = (fp.get("meta") or {})
        anchor_title = (meta.get("title") or "").strip()
        anchor_phrase = _normalize_anchor_phrase_from_title(anchor_title) if anchor_title else ""
        print(f"\n-- Frontpage --")
        if fp_path:
            print(f"path: {fp_path}")
        if anchor_title:
            print(f"meta.title: {anchor_title}")
            print(f"anchor_phrase_lower: {anchor_phrase}")
        posts = _top_posts(fp, limit=8)
        for j, p in enumerate(posts, start=1):
            print(f"#{j} score={p.get('score')} comments={p.get('comments')} created_ts={p.get('created_ts')}")
            print(f"    title: {p.get('title','')[:180]}")

        grams = _local_grams_from_frontpage(fp, max_ngram=3, include_preview=args.include_preview)
        # Show select maintenance seeds if present
        for seed in ["oil change", "cabin air filter", "spark plug", "brake fluid", "timing belt"]:
            if grams.get(seed, 0) > 0:
                print(f"[seed-present] '{seed}' tf={grams[seed]}")

    # Posts composed mapping to seeds (optional detail)
    if args.show_seed_map:
        print("\n-- Posts Composed Seed Map --")
        canon = canonicalize_subreddit_key(rec.get("name", ""), rec.get("url", ""))
        def _derive_seed(term: str) -> Optional[str]:
            tl = (term or "").lower()
            if anchor_phrase and tl.startswith(anchor_phrase + " "):
                return tl[len(anchor_phrase) + 1 :]
            if canon and tl.startswith(canon + " "):
                return tl[len(canon) + 1 :]
            return None

        # Build seed lookup among posts-only (not composed)
        posts_only = {}
        for kw in kws:
            s = kw.get("source") or ""
            if "posts" in s and "composed" not in s:
                posts_only[(kw.get("term") or "").lower()] = float(kw.get("score") or 0.0)

        shown = 0
        for idx, kw in enumerate(kws, start=1):
            s = kw.get("source") or ""
            if "posts_composed" not in s:
                continue
            term = kw.get("term") or ""
            comp_score = float(kw.get("score") or 0.0)
            seed = _derive_seed(term)
            ratio_str = ""
            if seed and seed in posts_only:
                seed_sc = posts_only.get(seed, 0.0)
                ratio = (comp_score / seed_sc) if seed_sc > 0 else 0.0
                ratio_str = f" | seed='{seed}' seed_score={seed_sc:.4f} ratio={ratio:.3f}"
            print(f"rank={idx:2d} composed='{term}' score={comp_score:.4f}{ratio_str}")
            shown += 1
            if shown >= 30:
                break


if __name__ == "__main__":
    main()