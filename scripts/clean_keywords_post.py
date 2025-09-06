#!/usr/bin/env python3
"""
Keyword JSONL post-processor (programmatic, no curated stoplists)

Purpose
- Clean already-produced keyword JSONL files without re-running TF‑IDF/DF.
- Fix repetitive/redundant phrases, drop obvious technical artifacts, filter non‑English scripts.
- Programmatically derive cross-record document frequency (DF) and drop globally generic terms by DF ratio.
- Dedupe near-identical variants (spacing/punctuation/casing), keeping the highest-score entry.
- Renormalize weights so they sum to 1.0 after drops/dedup.

Important
- No curated stoplists or manual blocklists are used. Everything is derived programmatically.
- The DF-based drop operates over the provided file(s) as a corpus (two-pass stream).

Input/Output
- Input: page_*.keywords.jsonl files (each line: one subreddit record).
- Output: cleaned JSONL written to a separate directory, atomically (.tmp then replace).

Usage
  # Clean a single file (DF computed over that file's records)
  python3 scripts/clean_keywords_post.py \
    --input-file output/keywords_v22/page_31.keywords.jsonl \
    --output-dir output/keywords_v22_clean

  # Clean a whole directory (DF computed across all JSONL files in the directory)
  python3 scripts/clean_keywords_post.py \
    --input-dir output/keywords_v22 \
    --output-dir output/keywords_v22_clean

  # Conservative language filters but still remove technical artifacts and near-dups
  python3 scripts/clean_keywords_post.py \
    --input-dir output/keywords_v22 \
    --output-dir output/keywords_v22_clean \
    --keep-cjk --keep-cyrillic --keep-greek

  # Strong technical filtering and more aggressive DF-drop for posts-only sources
  python3 scripts/clean_keywords_post.py \
    --input-dir output/keywords_v22 \
    --output-dir output/keywords_v22_clean \
    --tech-filter-strong \
    --df-drop-threshold 0.20 \
    --df-drop-sources posts_union

Notes
- This tool streams line-by-line; it does not load full JSONL into memory.
- It preserves raw scores and sources; only 'term' may be normalized (e.g., collapse repeated words).
- It renormalizes weights among kept terms so weights sum to 1.0 per record.
"""

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

# Technical/web artifact cues (programmatic; no curated strings)
TECH_WEB_TOKENS: Set[str] = {
    "http", "https", "www", "www2", "com", "net", "org", "io", "co",
    "store", "shop", "coupon", "promo", "subscribe", "login", "signin",
    "download", "update", "version", "release", "playlist", "stream"
}

_HEX_TOKEN_RE = re.compile(r"^[0-9a-f]{6,}$", re.IGNORECASE)
_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]")
_NONALNUM_RE = re.compile(r"[^0-9A-Za-z]+")
_SPACE_RE = re.compile(r"\s+")

# Unicode ranges
_CJK_RE = re.compile(
    "["  # CJK Unified Ideographs + extensions + Hiragana/Katakana + halfwidth katakana
    "\u3040-\u30ff"
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uf900-\ufaff"
    "\uff66-\uff9d"
    "]"
)
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_GREEK_RE = re.compile(r"[\u0370-\u03FF]")

# ---------------------------
# Helpers: normalization, anchors, language/tech filters
# ---------------------------

def normalize_for_dedupe(term: str) -> str:
    """
    Normalize a term for near-duplicate detection and DF accounting.
    - Lowercase
    - Remove all non-alphanumeric chars (collapses spacing/casing/punct variants)
    """
    t = (term or "").lower().strip()
    t = _NONALNUM_RE.sub("", t)
    return t


def collapse_repeated_adjacent_words(term: str) -> str:
    """
    Collapse adjacent duplicate words, case-insensitive:
      'big big problem' -> 'big problem'
      'surströmming surströmming challenge' -> 'surströmming challenge'
    """
    if not term:
        return term
    toks = _SPACE_RE.split(term.strip())
    out: List[str] = []
    prev = None
    for tok in toks:
        key = tok.lower()
        if key and key != prev:
            out.append(tok)
        prev = key
    return " ".join(out)


def has_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def has_cyrillic(s: str) -> bool:
    return bool(_CYRILLIC_RE.search(s))


def has_greek(s: str) -> bool:
    return bool(_GREEK_RE.search(s))


def nonascii_ratio(s: str) -> float:
    if not s:
        return 0.0
    total = len(s)
    na = len(_NON_ASCII_RE.findall(s))
    return (na / total) if total > 0 else 0.0


def is_technical_artifact(term: str, strong: bool = False) -> bool:
    """
    Heuristics to catch URL/domain fragments and hex-like garbage.
    - If 'com','http','https','www' appear as tokens => drop
    - If 2+ tokens from TECH_WEB_TOKENS are present => drop
    - If at least half of tokens look like hex strings => drop
    - If strong=True, drop if any token length>=18 alnum without vowels (likely hash/id)
    """
    toks = [t for t in _SPACE_RE.split((term or "").strip().lower()) if t]
    if not toks:
        return False
    # Early reject on common web tokens
    if any(t in {"http", "https", "www", "www2", "com"} for t in toks):
        return True
    # Count web-ish tokens
    web_hits = sum(1 for t in toks if t in TECH_WEB_TOKENS)
    if web_hits >= 2:
        return True
    # Hex-ish ratio
    hex_hits = sum(1 for t in toks if _HEX_TOKEN_RE.match(t))
    if hex_hits >= max(1, len(toks) // 2):
        return True
    if strong:
        # Alnum long tokens without vowels (likely ids)
        for t in toks:
            if len(t) >= 18 and t.isalnum():
                if not re.search(r"[aeiou]", t):
                    return True
    return False


def _canonical_subreddit_key(name: str, url: str) -> str:
    """
    Extract canonical subreddit key (lower) from name like 'r/CX5' or URL '/r/CX5/'.
    """
    key = ""
    if name:
        m = re.search(r"r/([^/\s]+)", name, flags=re.IGNORECASE)
        if m:
            key = m.group(1).strip("/").lower()
    if (not key) and url:
        m = re.search(r"/r/([^/\s]+)/?", url, flags=re.IGNORECASE)
        if m:
            key = m.group(1).strip("/").lower()
    return key


def _anchor_tokens_from_record(rec: Dict) -> Set[str]:
    """
    Derive anchor tokens usable for protection:
    - canonical key (e.g., 'cx5')
    - alnum-only variant (e.g., 'cx-5' -> 'cx5')
    """
    name = str(rec.get("name", "") or "")
    url = str(rec.get("url", "") or "")
    canon = _canonical_subreddit_key(name, url)
    anchors: Set[str] = set()
    if canon:
        anchors.add(canon)
        anchors.add(_NONALNUM_RE.sub("", canon))
    return {a for a in anchors if a}


def _term_contains_anchor(term: str, anchors: Set[str]) -> bool:
    """
    Check if the normalized term contains any normalized anchor token.
    """
    if not anchors:
        return False
    tnorm = _NONALNUM_RE.sub("", (term or "").lower())
    for a in anchors:
        if a and a in tnorm:
            return True
    return False


# ---------------------------
# DF-based genericity (programmatic)
# ---------------------------

def _source_parts(src: str) -> Set[str]:
    parts = set((src or "").split("+"))
    return {p for p in parts if p}


def _in_df_pool(src: str, pool: str) -> bool:
    parts = _source_parts(src)
    if pool == "union":
        return True
    if pool == "posts":
        return "posts" in parts
    if pool == "posts_composed":
        return "posts_composed" in parts
    if pool == "posts_union":
        return ("posts" in parts) or ("posts_composed" in parts)
    if pool == "desc":
        return "description" in parts
    if pool == "non_name":
        # exclude name-only terms
        return not (parts == {"name"})
    # default: union
    return True


def _list_candidates(input_dir: str) -> List[str]:
    files: List[str] = []
    try:
        for name in sorted(os.listdir(input_dir)):
            if name.endswith(".jsonl") and ".keywords." in name:
                files.append(os.path.join(input_dir, name))
    except Exception as e:
        print(f"[clean] failed to list {input_dir}: {e}", file=sys.stderr)
    return files


def _compute_df_for_paths(paths: List[str], df_pool: str) -> Tuple[Dict[str, int], int]:
    """
    Two-pass DF builder over provided JSONL paths.
    Returns (df_counts over normalized terms, total_docs).
    total_docs = number of subreddit records observed.
    """
    df: Dict[str, int] = {}
    total_docs = 0

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fin:
                for line in fin:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    kws = list(rec.get("keywords") or [])
                    if not kws:
                        continue
                    total_docs += 1
                    seen_this_doc: Set[str] = set()
                    for kw in kws:
                        try:
                            term = str(kw.get("term", "") or "")
                            src = str(kw.get("source", "") or "")
                        except Exception:
                            continue
                        if not _in_df_pool(src, df_pool):
                            continue
                        # Normalize via dedupe normalizer to merge spacing/punct variants
                        dkey = normalize_for_dedupe(term)
                        if not dkey:
                            continue
                        seen_this_doc.add(dkey)
                    if seen_this_doc:
                        for k in seen_this_doc:
                            df[k] = df.get(k, 0) + 1
        except Exception as e:
            print(f"[clean] warn: skipping {p} due to read error: {e}", file=sys.stderr)

    return df, total_docs


# ---------------------------
# Cleaning pipeline
# ---------------------------

def should_drop_by_lang_and_tech(
    term_original: str,
    args: argparse.Namespace,
) -> Tuple[bool, str]:
    # Technical/web artifacts
    if args.tech_filter or args.tech_filter_strong:
        if is_technical_artifact(term_original, strong=bool(args.tech_filter_strong)):
            return True, "tech"
    # Language/script filters
    if not args.keep_cjk and has_cjk(term_original):
        return True, "cjk"
    if not args.keep_cyrillic and has_cyrillic(term_original):
        return True, "cyrillic"
    if not args.keep_greek and has_greek(term_original):
        return True, "greek"
    if args.max_nonascii_ratio >= 0.0:
        if nonascii_ratio(term_original) > args.max_nonascii_ratio:
            return True, "nonascii"
    return False, ""


def process_record(
    rec: Dict,
    args: argparse.Namespace,
    df_counts: Optional[Dict[str, int]],
    df_total_docs: int,
) -> Dict:
    """
    Clean one subreddit record:
      - collapse repeated words
      - filter language/technical artifacts
      - DF-based generic drop over selected sources (programmatic)
      - dedupe near-identicals
      - renormalize weights among kept terms
    """
    kws = list(rec.get("keywords") or [])
    if not kws:
        return rec

    # Sort defensively by score desc
    try:
        kws.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    except Exception:
        pass

    anchor_tokens = _anchor_tokens_from_record(rec)

    kept: List[Dict] = []
    chosen: Dict[str, int] = {}  # dedupe_key -> index in kept
    drops = {
        "tech": 0, "cjk": 0, "cyrillic": 0, "greek": 0, "nonascii": 0,
        "score": 0, "dup": 0, "df": 0
    }

    enable_df_drop = (
        args.df_drop_enable
        and df_counts is not None
        and df_total_docs >= max(0, int(args.df_drop_min_docs))
        and df_total_docs > 0
    )
    thr = float(args.df_drop_threshold)

    for kw in kws:
        try:
            term = str(kw.get("term", "") or "")
            score = float(kw.get("score") or 0.0)
            src = str(kw.get("source", "") or "")
        except Exception:
            continue

        if args.min_score > 0.0 and score < args.min_score:
            drops["score"] += 1
            continue

        # Collapse adjacent duplicates in-place
        cleaned_term = collapse_repeated_adjacent_words(term)

        # Language/technical filters
        ld_drop, reason = should_drop_by_lang_and_tech(cleaned_term, args)
        if ld_drop:
            drops[reason] += 1
            continue

        # DF-based drop (programmatic, optional)
        if enable_df_drop and _in_df_pool(src, args.df_drop_sources):
            if not (args.anchor_protect and _term_contains_anchor(cleaned_term, anchor_tokens)):
                dkey_df = normalize_for_dedupe(cleaned_term)
                if dkey_df:
                    df_val = int(df_counts.get(dkey_df, 0))
                    df_ratio = (df_val / df_total_docs) if df_total_docs > 0 else 0.0
                    if df_ratio >= thr:
                        drops["df"] += 1
                        continue

        # Dedupe near-identical variants by normalized form
        dkey = normalize_for_dedupe(cleaned_term)
        if not dkey:
            drops["dup"] += 1
            continue

        if dkey in chosen:
            # Keep the higher score; if tie, prefer posts_composed > posts > description > name
            prev_idx = chosen[dkey]
            prev = kept[prev_idx]
            prev_score = float(prev.get("score") or 0.0)
            if score > prev_score:
                kept[prev_idx] = {
                    **kw,
                    "term": cleaned_term,
                }
            elif abs(score - prev_score) < 1e-9:
                def _rank(src_val: str) -> int:
                    order = ["posts_composed", "posts", "description", "name"]
                    parts = (src_val or "").split("+")
                    best = 999
                    for p in parts:
                        try:
                            idx = order.index(p)
                            if idx < best:
                                best = idx
                        except ValueError:
                            pass
                    return best
                if _rank(src) < _rank(str(prev.get("source") or "")):
                    kept[prev_idx] = {
                        **kw,
                        "term": cleaned_term,
                    }
            else:
                drops["dup"] += 1
            continue

        # Keep term
        new_kw = dict(kw)
        new_kw["term"] = cleaned_term
        kept.append(new_kw)
        chosen[dkey] = len(kept) - 1

    # Renormalize weights to sum to 1.0 among kept
    total_score = sum(float(k.get("score") or 0.0) for k in kept) or 1.0
    for k in kept:
        sc = float(k.get("score") or 0.0)
        k["weight"] = round(sc / total_score, 6)

    # Replace keywords
    rec_out = dict(rec)
    rec_out["keywords"] = kept

    # Optionally attach simple stats for debugging
    if args.emit_stats:
        rec_out["_postproc"] = {
            "dropped": drops,
            "kept_count": len(kept),
            "orig_count": len(kws),
            "df_docs": df_total_docs,
        }

    return rec_out


def process_file(
    in_path: str,
    out_dir: str,
    args: argparse.Namespace,
    df_counts: Optional[Dict[str, int]],
    df_total_docs: int,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.basename(in_path)
    out_path = os.path.join(out_dir, base)
    tmp_path = out_path + ".tmp"

    written = 0
    with open(in_path, "r", encoding="utf-8") as fin, open(tmp_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = (line or "").strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            cleaned = process_record(rec, args, df_counts, df_total_docs)
            fout.write(json.dumps(cleaned, ensure_ascii=False) + "\n")
            written += 1

    try:
        os.replace(tmp_path, out_path)
    except Exception as e:
        print(f"[clean] finalize failed for {out_path}: {e}", file=sys.stderr)
    print(f"[clean] wrote {written} records -> {out_path}", file=sys.stderr)


# ---------------------------
# CLI
# ---------------------------

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Clean subreddit keyword JSONL outputs (programmatic, no curated stoplists).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input-file", type=str, help="One page_*.keywords.jsonl file")
    g.add_argument("--input-dir", type=str, help="Directory containing page_*.keywords.jsonl files (non-recursive)")

    ap.add_argument("--output-dir", type=str, required=True, help="Directory to write cleaned JSONL files")

    # Filters
    ap.add_argument("--min-score", type=float, default=0.0, help="Drop keywords with raw score < min-score (default 0)")
    ap.add_argument("--tech-filter", action="store_true", help="Enable technical/web artifact filter (default off)")
    ap.add_argument("--tech-filter-strong", action="store_true", help="Stronger technical filter (hash-like long tokens)")
    ap.add_argument("--keep-cjk", action="store_true", help="Keep CJK phrases (default drop)")
    ap.add_argument("--keep-cyrillic", action="store_true", help="Keep Cyrillic phrases (default drop)")
    ap.add_argument("--keep-greek", action="store_true", help="Keep Greek phrases (default drop)")
    ap.add_argument("--max-nonascii-ratio", type=float, default=0.50, help="Drop term if non-ASCII-char ratio exceeds this (default 0.50, set <0 to disable)")

    # DF-based genericity (programmatic)
    # Enable by default; use --no-df-drop to disable.
    ap.add_argument("--df-drop-threshold", type=float, default=0.25, help="Drop term if DF ratio across docs >= threshold (default 0.25)")
    ap.add_argument("--df-drop-min-docs", type=int, default=5, help="Minimum docs required to activate DF drop (default 5)")
    ap.add_argument(
        "--df-drop-sources",
        type=str,
        choices=["union", "posts", "posts_composed", "posts_union", "desc", "non_name"],
        default="posts_union",
        help="Which term sources participate in DF-based drop (default posts_union = posts or posts_composed)"
    )
    g_anchor = ap.add_mutually_exclusive_group()
    g_anchor.add_argument("--anchor-protect", dest="anchor_protect", action="store_true", default=True,
                          help="Protect terms that contain the subreddit anchor token from DF-drop (default on)")
    g_anchor.add_argument("--no-anchor-protect", dest="anchor_protect", action="store_false",
                          help="Disable anchor protection during DF-drop")
    g_df = ap.add_mutually_exclusive_group()
    g_df.add_argument("--df-drop-enable", dest="df_drop_enable", action="store_true", default=True,
                      help="Enable DF-based programmatic drop (default on)")
    g_df.add_argument("--no-df-drop", dest="df_drop_enable", action="store_false",
                      help="Disable DF-based programmatic drop")

    # Output diagnostics
    ap.add_argument("--emit-stats", action="store_true", help="Attach _postproc stats to each record (for debugging)")

    return ap.parse_args()


def main() -> None:
    args = parse_args()

    # Default behavior: enable the basic technical filter unless user explicitly opts out
    if not args.tech_filter and not args.tech_filter_strong:
        # Gentle default to catch the worst offenders
        args.tech_filter = True

    # Build DF over the chosen input scope
    if args.input_file:
        df_paths = [args.input_file]
        print(f"[clean] DF pass over 1 file: {os.path.basename(args.input_file)}", file=sys.stderr)
    else:
        df_paths = _list_candidates(args.input_dir)
        print(f"[clean] DF pass over {len(df_paths)} files in {args.input_dir}", file=sys.stderr)

    df_counts: Optional[Dict[str, int]] = None
    df_total_docs = 0
    if args.df_drop_enable:
        df_counts, df_total_docs = _compute_df_for_paths(df_paths, args.df_drop_sources)
        try:
            print(f"[clean] built DF: docs={df_total_docs:,}, unique_terms={len(df_counts):,}, pool={args.df_drop_sources}", file=sys.stderr)
        except Exception:
            pass

    # Process inputs
    if args.input_file:
        process_file(args.input_file, args.output_dir, args, df_counts, df_total_docs)
        return

    files = df_paths
    if not files:
        print(f"[clean] no candidate files in {args.input_dir}", file=sys.stderr)
        return
    for p in files:
        process_file(p, args.output_dir, args, df_counts, df_total_docs)


if __name__ == "__main__":
    main()