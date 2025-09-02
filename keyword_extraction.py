#!/usr/bin/env python3
"""
Keyword extraction for subreddit pages.

- Reads one or many output/pages/page_*.json files (page-sized, ~250 subs each)
- Produces per-subreddit keyword lists with relevance weights (JSONL), keeping a clear mapping
- Lightweight: pure Python, no external dependencies required

Usage examples:
  python3 keyword_extraction.py --input-file output/pages/page_60.json
  python3 keyword_extraction.py --input-glob "output/pages/page_*.json" --topk 25
  python3 keyword_extraction.py --input-file output/pages/page_60.json --output-dir output/keywords

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
- Scoring: Combine description TF-IDF and name-derived scores, then normalize per-subreddit so weights sum to 1.0.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from glob import glob
from typing import Dict, Iterable, List, Tuple


# -----------------------
# Configuration defaults
# -----------------------

DEFAULT_TOPK = 25
DEFAULT_MAX_NGRAM = 3
DEFAULT_OUTPUT_DIR = "output/keywords"
DEFAULT_NAME_WEIGHT = 3.0
DEFAULT_DESC_WEIGHT = 1.0
DEFAULT_MIN_TOKEN_LEN = 2  # allow short domain terms like ai, ml, uk, us, 3ds


# Curated light stopword list: English + subreddit boilerplate
STOPWORDS = {
    # Articles, pronouns, prepositions, auxiliaries, etc.
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "than",
    "for", "to", "from", "in", "on", "at", "of", "by", "with", "without",
    "into", "onto", "off", "over", "under", "about", "after", "before",
    "as", "is", "am", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "they", "their", "them",
    "you", "your", "we", "our", "us", "he", "she", "his", "her", "hers",
    "i", "me", "my", "mine",
    "no", "not", "only", "also", "very", "more", "most", "less", "least",
    "so", "such", "can", "cannot", "cant", "could", "should", "would",
    "do", "does", "did", "doing", "done",
    "will", "wont", "won", "shall", "may", "might", "must",
    "all", "any", "some", "many", "much", "few", "several", "various",
    "own", "same", "other", "another", "each", "every", "either", "neither",
    "here", "there", "where", "when", "why", "how",
    "what", "which", "who", "whom", "whose",
    # Common subreddit boilerplate
    "welcome", "subreddit", "community", "official", "unofficial",
    "dedicated", "place", "space", "home", "discussion", "discuss", "talk",
    "share", "sharing", "post", "posts", "posting", "please", "read", "rules",
    "join", "fans", "fan", "related", "anything", "everything", "everyone",
    "anyone", "someone", "something", "stuff", "things",
    "news", "updates", "help",
    "about", "focused", "focusedon", "focus",
    "series", "tv", "show", "shows", "movie", "movies", "film", "films",
    "game", "games", "gaming", "videogame", "videogames",
    "forum", "sub", "reddit", "r",
    # Geography broad fillers
    "world", "global", "international",
    # Frequency and connector words
    "including", "include", "includes", "etc",
    # Numbers written in words (light)
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    # Cleanup for common artifacts and generic filler in bios
    "nother",  # from A(nother)
    "amp",     # from &
    "sn",      # local acronym seen in some descriptions
    "safe", "work", "works", "working", "great",
    # Media/generic content terms that often add noise
    "collection", "collections", "picture", "pictures", "video", "videos",
    "photo", "photos", "image", "images", "pic", "pics", "gallery",
}

# Common suffix/prefix clues to heuristically segment concatenated names (lowercase)
HEURISTIC_SUFFIXES = [
    "club", "food", "house", "houses", "baking", "cooking", "music", "girls",
    "boys", "games", "game", "garden", "gardening", "coding", "code", "design",
    "dev", "devs", "dogs", "dog", "cats", "cat", "jobs", "job", "news", "art",
    "arts", "sports", "sport", "cars", "car", "coin", "coins", "crypto",
    "market", "markets", "fashion", "makeup", "beauty", "support",
    "trading", "stocks", "nails", "drama", "school", "schools", "theory",
    "gardeners", "photography",
    "fc",  # football club
]

# Acronym and token expansions (lowercase key -> list of expansions)
EXPANSIONS = {
    "fc": ["football club"],
    "uk": ["united kingdom"],
    "us": ["united states"],
    "usa": ["united states"],
    "eu": ["europe"],
    "3ds": ["nintendo 3ds"],
    "ai": ["artificial intelligence"],
    "ml": ["machine learning"],
    "mlops": ["machine learning operations"],
    "ux": ["user experience"],
    "ui": ["user interface"],
    "diy": ["do it yourself"],
    "rpg": ["role playing game"],
    "ttrpg": ["tabletop role playing game"],
    "fps": ["first person shooter"],
}


# -----------------------
# Small text utilities
# -----------------------

_ws_re = re.compile(r"\s+")
# Split camelCase, PascalCase, digit transitions, and acronym-to-Word (e.g., UKGardening -> UK | Gardening)
_camel_boundary_re = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])"          # lower/digit -> Upper
    r"|(?<=[A-Z])(?=[A-Z][a-z])"       # ACRONYM -> ProperCase boundary
    r"|(?<=[A-Za-z])(?=[0-9])"         # letter -> digit
    r"|(?<=[0-9])(?=[A-Za-z])"         # digit -> letter
)


def normalize_space(s: str) -> str:
    return _ws_re.sub(" ", s).strip()


def tokenize_simple(text: str) -> List[str]:
    """
    Unicode-aware word tokenizer. Keeps letters and digits, drops underscores and punctuation.
    Lowercases and strips.
    """
    if not text:
        return []
    # Replace underscores/hyphens with space to avoid glue
    text = text.replace("_", " ").replace("-", " ")
    # Keep letters/digits; Python \w includes underscore, so strip it manually
    text = re.sub(r"[^0-9\w\s]+", " ", text, flags=re.UNICODE)  # drop punctuation, keep word chars
    text = text.replace("_", " ")
    text = normalize_space(text.lower())
    if not text:
        return []
    tokens = text.split()
    return tokens


def split_camel_and_digits(token: str) -> List[str]:
    """
    Split camel/pascal case and letter-digit boundaries.
    Preserves all-uppercase short acronyms as a single token.
    """
    if not token:
        return []
    if token.isupper() and len(token) <= 5:
        return [token]  # keep acronym
    parts = _camel_boundary_re.split(token)
    # Some parts may still include caps at start; lower case them for normalization
    out = []
    for p in parts:
        if not p:
            continue
        out.extend(re.split(r"[^0-9A-Za-z]+", p))
    out = [x for x in out if x]
    return out


def heuristic_segment_lower(token: str) -> List[str]:
    """
    Very lightweight heuristic to segment a long lowercase token by common suffixes.
    Example: southernfood -> ["southern", "food"], rangersfc -> ["rangers", "fc"]
    """
    if not token or not token.isalpha():
        return [token]
    if len(token) <= 8:
        return [token]
    # Try repeatedly peeling known suffixes
    parts = []
    t = token
    changed = True
    while changed:
        changed = False
        for suf in HEURISTIC_SUFFIXES:
            if t.endswith(suf) and len(t) > len(suf) + 2:
                head = t[: len(t) - len(suf)]
                parts.append(head)
                parts.append(suf)
                t = ""  # consumed
                changed = True
                break
        # If not matched, attempt a middle split at most once: at vowels boundary
        if not changed and t:
            # find a boundary near the middle at a vowel transition: e.g., glutenfree -> gluten free
            mid = len(t) // 2
            # search rightwards for a vowel boundary
            m = re.search(r"[aeiouy][^aeiouy]", t[mid:])
            if m:
                pos = mid + m.end() - 1
                if 3 <= pos <= len(t) - 3:
                    parts.append(t[:pos])
                    parts.append(t[pos:])
                    t = ""
                    changed = True
    if not parts:
        return [token]
    # parts might include empty strings if weird split - filter
    parts = [p for p in parts if p]
    # If we produced 3+ pieces by repeated splits, flatten: re-segment each recursively if needed
    final = []
    for p in parts:
        if p.isalpha() and len(p) > 10:
            final.extend(heuristic_segment_lower(p))
        else:
            final.append(p)
    return final


def expand_token(token: str) -> List[str]:
    """
    Expand common acronyms/tokens into phrases (lowercase). Return list of phrases (strings with spaces).
    """
    return EXPANSIONS.get(token.lower(), [])


def filter_stop_tokens(tokens: Iterable[str]) -> List[str]:
    out = []
    for t in tokens:
        lt = t.lower()
        if lt in STOPWORDS:
            continue
        if len(lt) < DEFAULT_MIN_TOKEN_LEN and lt not in {"ai", "vr", "uk", "us", "eu", "3d"}:
            continue
        out.append(lt)
    return out


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


# -----------------------
# Name parsing
# -----------------------

def extract_name_terms(raw_name: str) -> List[str]:
    """
    Extract keywords from a subreddit name string like 'r/Crossdressing_support', 'r/rangersfc', 'r/TwoandaHalfMen'.

    Steps:
    - strip 'r/' prefix and trailing '/'
    - split on delimiters, camel case, digit boundaries
    - for long lowercase runs, use heuristic segmentation
    - add acronym expansions
    - return deduplicated lowercased tokens and common bigrams for better phrasing
    """
    if not raw_name:
        return []

    name = raw_name.strip()
    # remove r/ prefix and trailing slash
    name = re.sub(r"^r/+", "", name, flags=re.IGNORECASE)
    name = name.rstrip("/")

    # normalize delimiters
    name = name.replace("_", " ").replace("-", " ").replace(".", " ")
    name = normalize_space(name)

    # split tokens (keep case for camel split)
    rough_tokens = re.split(r"\s+", name)

    split_tokens: List[str] = []
    for tok in rough_tokens:
        if not tok:
            continue
        # First pass split by camel/digit boundaries
        for part in split_camel_and_digits(tok):
            if not part:
                continue
            # If lowercase long glue, try heuristic segmentation
            if part.isalpha() and part.islower() and len(part) >= 9:
                split_tokens.extend(heuristic_segment_lower(part))
            else:
                split_tokens.append(part.lower())

    # Expand acronyms
    expanded_phrases: List[str] = []
    for t in split_tokens:
        expanded_phrases.extend(expand_token(t))

    # Filter stopwords
    filtered = filter_stop_tokens(split_tokens)

    # Build full phrase from filtered tokens (captures the WHOLE split name)
    full_phrase = " ".join(filtered) if filtered else ""

    # Compose bigrams for name-derived tokens to capture intermediate phrases
    bigrams = []
    if len(filtered) >= 2:
        for i in range(len(filtered) - 1):
            bigrams.append(f"{filtered[i]} {filtered[i+1]}")

    # Candidate ordering: full phrase first (if multi-word), then unigrams, bigrams, expansions
    candidates: List[str] = []
    if full_phrase and " " in full_phrase:
        candidates.append(full_phrase)
    candidates.extend(filtered)
    candidates.extend(bigrams)
    candidates.extend(expanded_phrases)

    # Merge and deduplicate while preserving order
    seen = set()
    ordered_terms: List[str] = []
    for term in candidates:
        lt = term.lower()
        if lt and lt not in seen:
            seen.add(lt)
            ordered_terms.append(lt)

    return ordered_terms


def extract_name_full_phrase(raw_name: str) -> Tuple[str, str]:
    """
    Build the WHOLE phrase from the subreddit name by robust splitting/segmentation.
    Returns a tuple (full_lower, full_cased). If nothing useful, returns ("", "").

    Note: Unlike extract_name_terms, this function does NOT remove stopwords.
    The intention is to preserve the entire readable phrase (e.g., "Alcohol Liver Support").
    """
    if not raw_name:
        return "", ""

    name = raw_name.strip()
    name = re.sub(r"^r/+", "", name, flags=re.IGNORECASE)
    name = name.rstrip("/")
    name = name.replace("_", " ").replace("-", " ").replace(".", " ")
    name = normalize_space(name)

    rough_tokens = re.split(r"\s+", name)

    lower_tokens: List[str] = []
    cased_tokens: List[str] = []

    for tok in rough_tokens:
        if not tok:
            continue
        parts = split_camel_and_digits(tok)
        for part in parts:
            if not part:
                continue
            # For long lowercase globs, try heuristic segmentation
            if part.isalpha() and part.islower() and len(part) >= 9:
                segs = heuristic_segment_lower(part)
            else:
                segs = [part]

            for seg in segs:
                if not seg:
                    continue
                low = seg.lower()
                lower_tokens.append(low)
                # Preserve acronyms; title-case plain lowercase; otherwise keep as-is
                if seg.isupper():
                    disp = seg
                elif seg.islower():
                    disp = seg.title()
                else:
                    disp = seg
                cased_tokens.append(disp)

    if not lower_tokens:
        return "", ""

    full_lower = " ".join(lower_tokens)
    full_cased = " ".join(cased_tokens)
    return full_lower, full_cased


# -----------------------
# Description processing
# -----------------------

def extract_desc_terms(description: str, max_ngram: int) -> List[str]:
    """
    Tokenize description and produce filtered tokens ready for n-gram counting.
    """
    if not description:
        return []
    tokens = tokenize_simple(description)
    tokens = filter_stop_tokens(tokens)
    return tokens


# -----------------------
# Scoring
# -----------------------

@dataclass
class SubDoc:
    community_id: str
    name: str
    url: str
    rank: int | None
    subscribers_count: int | None
    desc_text: str
    name_terms: List[str]


def iter_subreddits_from_file(path: str) -> Iterable[SubDoc]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    subs = data.get("subreddits", []) or []
    for s in subs:
        yield SubDoc(
            community_id=s.get("community_id", ""),
            name=s.get("name", ""),
            url=s.get("url", ""),
            rank=s.get("rank"),
            subscribers_count=s.get("subscribers_count"),
            desc_text=s.get("description", "") or "",
            name_terms=extract_name_terms(s.get("name", "")),
        )


def build_docfreq(
    input_paths: List[str],
    max_ngram: int,
) -> Tuple[Counter, int]:
    """
    First pass: compute document frequency for description n-grams across all selected files.
    Returns (docfreq Counter, total_docs N)
    """
    docfreq = Counter()
    total_docs = 0

    for p in input_paths:
        for sub in iter_subreddits_from_file(p):
            total_docs += 1
            tokens = extract_desc_terms(sub.desc_text, max_ngram)
            grams = tokens_to_ngrams(tokens, max_ngram)
            for g in grams.keys():
                docfreq[g] += 1

    return docfreq, total_docs


def compute_tfidf_per_doc(
    tokens: List[str],
    docfreq: Counter,
    total_docs: int,
    max_ngram: int,
    min_df_bigram: int,
    min_df_trigram: int,
) -> Counter:
    """
    Compute TF-IDF for description text of a single document.
    idf = log((1 + N) / (1 + df)) + 1  (smooth)
    score = tf * idf

    Additionally prunes rare multi-grams:
      - bigrams kept only if df >= min_df_bigram
      - trigrams kept only if df >= min_df_trigram
    """
    grams = tokens_to_ngrams(tokens, max_ngram)
    tfidf = Counter()
    for g, tf in grams.items():
        n_words = g.count(" ") + 1
        df = docfreq.get(g, 0)
        if n_words == 2 and df < min_df_bigram:
            continue
        if n_words == 3 and df < min_df_trigram:
            continue
        idf = math.log((1.0 + total_docs) / (1.0 + df)) + 1.0
        tfidf[g] = tf * idf
    return tfidf


def score_name_terms(name_terms: List[str]) -> Counter:
    """
    Assign base weights to name-derived terms.
    Heuristics:
      - unigrams get 1.0
      - bigrams (contain space) get 1.5
      - expanded phrases (2+ words) included same way via extract_name_terms
    """
    scores = Counter()
    for t in name_terms:
        n_words = t.count(" ") + 1
        if n_words >= 3:
            scores[t] += 2.5  # prioritize full multi-word phrases from the name
        elif n_words == 2:
            scores[t] += 1.5
        else:
            scores[t] += 1.0
    return scores


def merge_scores(desc_scores: Counter, name_scores: Counter, desc_w: float, name_w: float) -> Dict[str, Tuple[float, str]]:
    """
    Merge description TF-IDF and name term weights into a combined dict:
      term -> (score, source)
    where source in {"description", "name", "both"}
    """
    out: Dict[str, Tuple[float, str]] = {}

    for term, v in desc_scores.items():
        out[term] = (v * desc_w, "description")

    for term, v in name_scores.items():
        if term in out:
            cur, src = out[term]
            out[term] = (cur + v * name_w, "both" if src == "description" else src)
        else:
            out[term] = (v * name_w, "name")

    return out


def normalize_weights(term_scores: Dict[str, Tuple[float, str]]) -> List[Tuple[str, float, float, str]]:
    """
    Normalize combined scores so weights sum to 1.0 per document.
    Returns list of tuples (term, weight, raw_score, source)
    """
    total = sum(v for v, _ in term_scores.values()) or 1.0
    items = []
    for term, (score, source) in term_scores.items():
        items.append((term, score / total, score, source))
    # sort by raw score desc
    items.sort(key=lambda x: x[2], reverse=True)
    return items


# -----------------------
# IO and CLI
# -----------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def out_path_for_input(output_dir: str, input_path: str) -> str:
    base = os.path.basename(input_path)
    base = re.sub(r"\.json$", "", base, flags=re.IGNORECASE)
    return os.path.join(output_dir, f"{base}.keywords.jsonl")


def process_inputs(
    input_paths: List[str],
    output_dir: str,
    topk: int,
    max_ngram: int,
    name_weight: float,
    desc_weight: float,
    min_df_bigram: int,
    min_df_trigram: int,
) -> None:
    if not input_paths:
        print("No input files matched.", file=sys.stderr)
        return

    ensure_dir(output_dir)

    # Pass 1: global docfreq across selected inputs (for description n-grams)
    print(f"[pass1] building docfreq over {len(input_paths)} file(s)...", file=sys.stderr)
    docfreq, total_docs = build_docfreq(input_paths, max_ngram)
    print(f"[pass1] total_docs={total_docs:,}, unique_terms={len(docfreq):,}", file=sys.stderr)

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
                    desc_tokens, docfreq, total_docs, max_ngram, min_df_bigram, min_df_trigram
                )

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

                # Merge and normalize
                merged = merge_scores(desc_tfidf, name_scores, desc_weight, name_weight)
                ranked = normalize_weights(merged)
                top = ranked[:topk]

                rec = {
                    "community_id": sub.community_id,
                    "name": sub.name,
                    "url": sub.url,
                    "rank": sub.rank,
                    "subscribers_count": sub.subscribers_count,
                    "keywords": [
                        {
                            "term": (full_cased if (t == full_lower and src != "description" and " " in t) else t),
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
    ap = argparse.ArgumentParser(description="Extract subreddit keywords with TF-IDF and name parsing.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input-file", type=str, help="Path to one page JSON file")
    g.add_argument("--input-glob", type=str, help="Glob for many page JSON files, e.g., 'output/pages/page_*.json'")
    ap.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR, help="Directory for output JSONL files")
    ap.add_argument("--topk", type=int, default=DEFAULT_TOPK, help="Top-K keywords per subreddit")
    ap.add_argument("--max-ngram", type=int, default=DEFAULT_MAX_NGRAM, help="Max n-gram length for description TF-IDF")
    ap.add_argument("--name-weight", type=float, default=DEFAULT_NAME_WEIGHT, help="Weight multiplier for name-derived terms")
    ap.add_argument("--desc-weight", type=float, default=DEFAULT_DESC_WEIGHT, help="Weight multiplier for description TF-IDF")
    ap.add_argument("--min-df-bigram", type=int, default=2, help="Minimum document frequency to keep bigrams")
    ap.add_argument("--min-df-trigram", type=int, default=2, help="Minimum document frequency to keep trigrams")

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
    )


if __name__ == "__main__":
    main()