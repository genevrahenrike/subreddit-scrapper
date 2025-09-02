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
- Posts extraction: n-gram TF-IDF from frontpage post titles (and optionally content preview), with engagement and recency weighting; phrase preference; optional anchored variants for generic terms.
- Scoring: Combine description TF-IDF, name-derived scores, and posts-derived scores; then normalize per-subreddit so weights sum to 1.0.
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
from typing import Dict, Iterable, List, Tuple, Optional, Set
from datetime import datetime, timezone, timedelta
import numpy as np

# Optional sentence-transformers for embedding rerank
_HAS_ST = False
try:
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.util import cos_sim
    _HAS_ST = True
except Exception:
    _HAS_ST = False

# Lazy model cache for embeddings
_EMBED_MODEL_CACHE: Dict[str, "SentenceTransformer"] = {}

# Optional word segmentation backstops (used for glued lowercase names)
_HAS_WORDSEGMENT = False
_HAS_WORDNINJA = False
_WORDSEGMENT_LOADED = False
try:
    from wordsegment import load as _ws_load, segment as _ws_segment  # type: ignore
    _HAS_WORDSEGMENT = True
except Exception:
    _HAS_WORDSEGMENT = False

try:
    import wordninja as _wordninja  # type: ignore
    _HAS_WORDNINJA = True
except Exception:
    _HAS_WORDNINJA = False


def _ensure_wordsegment_loaded() -> None:
    global _WORDSEGMENT_LOADED
    if _HAS_WORDSEGMENT and not _WORDSEGMENT_LOADED:
        try:
            _ws_load()
            _WORDSEGMENT_LOADED = True
        except Exception:
            globals()["_HAS_WORDSEGMENT"] = False


# -----------------------
# Configuration defaults
# -----------------------

DEFAULT_TOPK = 25
DEFAULT_MAX_NGRAM = 3
DEFAULT_OUTPUT_DIR = "output/keywords"
DEFAULT_NAME_WEIGHT = 3.0
DEFAULT_DESC_WEIGHT = 1.0
DEFAULT_MIN_TOKEN_LEN = 2  # allow short domain terms like ai, ml, uk, us, 3ds

# Description phrase boosts (favor multi-word phrases over generic unigrams)
DEFAULT_DESC_PHRASE_BOOST_BIGRAM = 1.2
DEFAULT_DESC_PHRASE_BOOST_TRIGRAM = 1.4

# Ensure local description phrases even if pruned by global df thresholds
DEFAULT_ENSURE_PHRASES = True
DEFAULT_ENSURE_PHRASES_K = 3

# Posts integration defaults
DEFAULT_POSTS_WEIGHT = 1.5
DEFAULT_POSTS_HALFLIFE_DAYS = 7.0
DEFAULT_POSTS_GENERIC_DF_RATIO = 0.05  # if appears in >=5% subs, consider "generic"
DEFAULT_POSTS_ANCHOR_MULTIPLIER = 0.9   # anchored variant score multiplier
DEFAULT_INCLUDE_CONTENT_PREVIEW = False  # keep off by default (often empty/noisy)

# Posts phrase preference (posts-specific; can be tuned via CLI)
DEFAULT_POSTS_PHRASE_BOOST_BIGRAM = 1.25
DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM = 1.5

# Embedding rerank defaults
DEFAULT_EMBED_RERANK = False
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # fast, strong; consider "BAAI/bge-m3" for multilingual/SOTA
DEFAULT_EMBED_ALPHA = 0.35                      # blend factor for semantic similarity
DEFAULT_EMBED_K_TERMS = 100                     # rerank top-K terms by embeddings


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

    # Calendar months and common abbreviations (generic timeline chatter)
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",

    # Generic colloquialisms often present in posts
    "guys",
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


def segment_token_lower(token: str) -> List[str]:
    """
    Try to segment a glued lowercase token into natural-language words using
    optional libraries, then fall back to heuristic segmentation.
    """
    if not token or not token.isalpha() or not token.islower() or len(token) < 9:
        return [token]
    # Try wordsegment
    if _HAS_WORDSEGMENT:
        try:
            _ensure_wordsegment_loaded()
            segs = _ws_segment(token)
            if segs and len(segs) >= 2:
                return [s.lower() for s in segs if s]
        except Exception:
            pass
    # Try wordninja
    if _HAS_WORDNINJA:
        try:
            segs = _wordninja.split(token)
            if segs and len(segs) >= 2:
                return [s.lower() for s in segs if s]
        except Exception:
            pass
    # Fallback heuristic
    return heuristic_segment_lower(token)


def expand_token(token: str) -> List[str]:
    """
    Expand common acronyms/tokens into phrases (lowercase). Return list of phrases (strings with spaces).
    """
    return EXPANSIONS.get(token.lower(), [])


def filter_stop_tokens(tokens: Iterable[str], extra_stopwords: Optional[Set[str]] = None) -> List[str]:
    out = []
    extra = extra_stopwords or set()
    for t in tokens:
        lt = t.lower()
        if lt in STOPWORDS or lt in extra:
            continue
        # Drop numeric-only tokens and common years
        if lt.isdigit():
            continue
        if re.fullmatch(r"(19|20)\d{2}", lt):
            continue
        if re.fullmatch(r"\d{2,}", lt):
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
            # If lowercase long glue, try segmentation backstops (wordsegment/wordninja) then heuristic
            if part.isalpha() and part.islower() and len(part) >= 9:
                split_tokens.extend(segment_token_lower(part))
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
                segs = segment_token_lower(part)
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
# Posts processing (frontpage)
# -----------------------

def _parse_created_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    # Example: "2025-09-02T10:07:33.290000+0000"
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%f%z")
    except Exception:
        # Try without fractional seconds
        try:
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            return None


def _parse_scraped_at(d: dict) -> datetime:
    s = d.get("scraped_at")
    if s:
        try:
            # "2025-09-02T03:24:15.686608" (naive); assume UTC
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return datetime.now(timezone.utc)


def canonicalize_subreddit_key(name: str, url: str) -> str:
    """
    Build a canonical lowercase key (e.g., 'valorant') from subreddit name or URL.
    """
    # Try name like "r/VALORANT"
    if name:
        m = re.search(r"r/([^/\s]+)", name, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip("/").lower()
        name2 = name.strip().strip("/").lower()
        return re.sub(r"^r/", "", name2)

    # Try URL like "https://www.reddit.com/r/VALORANT"
    if url:
        m = re.search(r"/r/([^/\s]+)/?", url, flags=re.IGNORECASE)
        if m:
            return m.group(1).lower()

    return ""


def subreddit_folder_from_name(name: str) -> str:
    """
    Derive folder name from display name (preserve casing if present).
    Input "r/VALORANT" -> "VALORANT"
    """
    if not name:
        return ""
    n = re.sub(r"^r/+", "", name.strip(), flags=re.IGNORECASE)
    return n.strip("/")


def _tokenize_post_text(title: str, preview: str, posts_extra_stopwords: Optional[Set[str]] = None) -> List[str]:
    parts: List[str] = []
    if title:
        parts.append(title)
    if DEFAULT_INCLUDE_CONTENT_PREVIEW and preview:
        parts.append(preview)
    if not parts:
        return []
    tokens = tokenize_simple(" ".join(parts))
    tokens = filter_stop_tokens(tokens, extra_stopwords=posts_extra_stopwords)
    return tokens


def build_posts_docfreq(frontpage_paths: List[str], max_ngram: int, posts_extra_stopwords: Optional[Set[str]] = None, posts_phrase_stoplist: Optional[Set[str]] = None) -> Tuple[Counter, int]:
    """
    Compute DF across subreddits' frontpages for n-grams from post titles/previews.
    Returns (docfreq, total_docs) where total_docs = number of frontpage docs considered.
    """
    docfreq = Counter()
    total_docs = 0

    for p in frontpage_paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        posts = data.get("posts") or []
        if not posts:
            continue

        grams_present: Set[str] = set()
        for post in posts:
            title = post.get("title", "") or ""
            preview = post.get("content_preview", "") or ""
            toks = _tokenize_post_text(title, preview, posts_extra_stopwords)
            grams = tokens_to_ngrams(toks, max_ngram)
            if posts_phrase_stoplist:
                for pg in list(grams.keys()):
                    if pg in posts_phrase_stoplist:
                        del grams[pg]
            for g in grams.keys():
                grams_present.add(g)

        if grams_present:
            total_docs += 1
            for g in grams_present:
                docfreq[g] += 1

    return docfreq, total_docs


def compute_posts_tfidf_for_frontpage(
    frontpage_data: dict,
    docfreq: Counter,
    total_docs: int,
    max_ngram: int,
    min_df_bigram: int,
    min_df_trigram: int,
    halflife_days: float,
    ensure_k: int,
    posts_extra_stopwords: Optional[Set[str]] = None,
    posts_phrase_stoplist: Optional[Set[str]] = None,
    posts_phrase_boost_bigram: float = DEFAULT_POSTS_PHRASE_BOOST_BIGRAM,
    posts_phrase_boost_trigram: float = DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM,
    drop_generic_unigrams: bool = False,
    generic_df_ratio: float = DEFAULT_POSTS_GENERIC_DF_RATIO,
) -> Counter:
    """
    Compute engagement- and recency-weighted TF-IDF for a single frontpage document.
    - Weighted TF sums across posts: TF_post = count_grams_in_post * post_weight
    - post_weight = (1 + log1p(score) + 0.5*log1p(comments)) * recency_decay
    - recency_decay = 0.5 ** (age_days / halflife_days)
    """
    posts = frontpage_data.get("posts") or []
    if not posts:
        return Counter()

    ref_time = _parse_scraped_at(frontpage_data)

    weighted_tf = Counter()
    local_grams_tf = Counter()  # unweighted counts for "ensure phrases"
    for post in posts:
        title = post.get("title", "") or ""
        preview = post.get("content_preview", "") or ""
        toks = _tokenize_post_text(title, preview, posts_extra_stopwords)
        if not toks:
            continue
        grams = tokens_to_ngrams(toks, max_ngram)
        if posts_phrase_stoplist:
            for pg in list(grams.keys()):
                if pg in posts_phrase_stoplist:
                    del grams[pg]
        local_grams_tf.update(grams)

        score = max(0, int(post.get("score") or 0))
        comments = max(0, int(post.get("comments") or 0))

        created_ts = _parse_created_ts(post.get("created_ts") or "")
        if created_ts is None:
            # If missing/invalid, do not apply recency penalty
            recency = 1.0
        else:
            if created_ts.tzinfo is None:
                created_ts = created_ts.replace(tzinfo=timezone.utc)
            age = ref_time - created_ts
            age_days = max(age.total_seconds() / 86400.0, 0.0)
            recency = 0.5 ** (age_days / max(halflife_days, 0.1))

        w = 1.0 + math.log1p(score) + 0.5 * math.log1p(comments)
        post_weight = w * recency

        for g, c in grams.items():
            weighted_tf[g] += c * post_weight

    tfidf = Counter()
    for g, tf in weighted_tf.items():
        n_words = g.count(" ") + 1
        df = docfreq.get(g, 0)
        if n_words == 2 and df < min_df_bigram:
            continue
        if n_words == 3 and df < min_df_trigram:
            continue
        # Optionally drop globally generic unigrams
        if n_words == 1 and drop_generic_unigrams:
            df_ratio = (df / total_docs) if total_docs > 0 else 0.0
            if df_ratio >= generic_df_ratio:
                continue
        idf = math.log((1.0 + total_docs) / (1.0 + df)) + 1.0
        boost = 1.0
        if n_words == 2:
            boost = posts_phrase_boost_bigram
        elif n_words == 3:
            boost = posts_phrase_boost_trigram
        tfidf[g] = tf * idf * boost

    # Ensure local phrases (bigrams/trigrams) even if pruned; use top local grams by raw TF (unweighted)
    if DEFAULT_ENSURE_PHRASES and ensure_k > 0 and local_grams_tf:
        candidates = [
            (g, tf) for g, tf in local_grams_tf.items()
            if ((g.count(" ") + 1) >= 2 and g not in tfidf)
        ]
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            for g, tf in candidates[:ensure_k]:
                n_words = g.count(" ") + 1
                boost = posts_phrase_boost_bigram if n_words == 2 else (
                    posts_phrase_boost_trigram if n_words == 3 else 1.0
                )
                tfidf[g] = tf * boost  # fallback: local TF × small phrase boost

    return tfidf


def apply_anchored_variants_for_generic_posts_terms(
    posts_scores: Counter,
    docfreq: Counter,
    total_docs: int,
    anchor_token: str,
    generic_df_ratio: float,
    replace_original_generic: bool = False,
) -> Counter:
    """
    For generic terms (high DF ratio) that do not include the anchor token, add an anchored variant:
      e.g., "abusing system" -> "valorant abusing system"
    Keeps the original score; the anchored variant gets DEFAULT_POSTS_ANCHOR_MULTIPLIER × original_score.
    Optionally drop the original generic term when anchoring (replace_original_generic=True).
    """
    if not posts_scores or not anchor_token:
        return posts_scores

    out = Counter(posts_scores)
    for term, score in posts_scores.items():
        lt = f" {term} "
        if f" {anchor_token} " in lt:
            continue  # already anchored with the subreddit token
        n_words = term.count(" ") + 1
        if n_words >= 3:
            continue  # avoid very long anchored phrases; keep to uni/bi-grams
        df = docfreq.get(term, 0)
        df_ratio = (df / total_docs) if total_docs > 0 else 1.0
        if df_ratio >= generic_df_ratio:
            anchored = f"{anchor_token} {term}"
            if anchored not in out:
                out[anchored] = score * DEFAULT_POSTS_ANCHOR_MULTIPLIER
            if replace_original_generic and term in out:
                del out[term]
    return out


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
    score = tf * idf * boost

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
        boost = 1.0
        if n_words == 2:
            boost = DEFAULT_DESC_PHRASE_BOOST_BIGRAM
        elif n_words == 3:
            boost = DEFAULT_DESC_PHRASE_BOOST_TRIGRAM
        tfidf[g] = tf * idf * boost
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


def merge_sources(
    items: List[Tuple[Counter, float, str]]
) -> Dict[str, Tuple[float, str]]:
    """
    Merge multiple sources of scores.
    items: list of (scores_counter, weight_multiplier, source_name)
    Returns: term -> (score, source_string) where source_string is "name+description+posts" etc.
    """
    out: Dict[str, Tuple[float, Set[str]]] = {}

    for scores, w, src in items:
        if not scores or w <= 0:
            continue
        for term, val in scores.items():
            add = val * w
            if term in out:
                cur, srcs = out[term]
                out[term] = (cur + add, srcs | {src})
            else:
                out[term] = (add, {src})

    # Convert source sets to joined string
    final: Dict[str, Tuple[float, str]] = {}
    for term, (score, srcs) in out.items():
        # normalize ordering for determinism
        src_str = "+".join(sorted(srcs))
        final[term] = (score, src_str)
    return final


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
# Embedding reranker (optional)
# -----------------------
def _get_embedder(model_name: str) -> Optional["SentenceTransformer"]:
    if not _HAS_ST:
        return None
    if model_name in _EMBED_MODEL_CACHE:
        return _EMBED_MODEL_CACHE[model_name]
    try:
        model = SentenceTransformer(model_name)
        _EMBED_MODEL_CACHE[model_name] = model
        return model
    except Exception:
        return None


def _build_theme_text(full_lower: str, desc_tfidf: Counter, top_desc_k: int) -> str:
    """
    Build a concise theme string from the whole subreddit name phrase + top-K description terms.
    """
    parts: List[str] = []
    if full_lower:
        parts.append(full_lower)
    if desc_tfidf and top_desc_k > 0:
        for g, _ in sorted(desc_tfidf.items(), key=lambda x: x[1], reverse=True)[:top_desc_k]:
            parts.append(g)
    return " ; ".join(parts)


def embed_rerank_terms(
    merged: Dict[str, Tuple[float, str]],
    theme_text: str,
    model_name: str,
    alpha: float,
    k_terms: int,
) -> Dict[str, Tuple[float, str]]:
    """
    Rerank top-K terms by multiplying their scores by a function of semantic similarity to theme_text.
    new_score = old_score * ((1 - alpha) + alpha * similarity), where similarity in [0,1].
    """
    if not theme_text or not _HAS_ST:
        return merged
    embedder = _get_embedder(model_name)
    if embedder is None:
        return merged

    # Select top-K by current score
    items = sorted(merged.items(), key=lambda kv: kv[1][0], reverse=True)
    top_items = items[: max(0, k_terms)]

    terms = [t for t, _ in top_items]
    try:
        theme_emb = embedder.encode([theme_text], normalize_embeddings=True)
        term_embs = embedder.encode(terms, normalize_embeddings=True)
    except Exception:
        return merged

    # cos_sim returns matrix (1, K)
    try:
        sims = cos_sim(theme_emb, term_embs).cpu().numpy().reshape(-1)
    except Exception:
        # Fallback cosine
        def _cos(a, b):
            an = np.linalg.norm(a)
            bn = np.linalg.norm(b)
            if an <= 0 or bn <= 0:
                return 0.0
            return float(np.dot(a, b) / (an * bn))
        sims = np.array([_cos(theme_emb[0], term_embs[i]) for i in range(len(terms))], dtype=float)

    # Map similarity to [0,1]
    sims01 = (sims + 1.0) / 2.0

    out: Dict[str, Tuple[float, str]] = dict(merged)
    for (term, (score, src)), s in zip(top_items, sims01):
        factor = (1.0 - alpha) + alpha * float(s)
        out[term] = (score * factor, src)
    return out


# -----------------------
# IO and CLI
# -----------------------

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def out_path_for_input(output_dir: str, input_path: str) -> str:
    base = os.path.basename(input_path)
    base = re.sub(r"\.json$", "", base, flags=re.IGNORECASE)
    return os.path.join(output_dir, f"{base}.keywords.jsonl")


def _build_frontpage_index(frontpage_glob: Optional[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Build index canonical_key -> frontpage_path for fast lookup.
    Returns (index_map, list_of_paths)
    """
    if not frontpage_glob:
        return {}, []
    paths = sorted(glob(frontpage_glob))
    index: Dict[str, str] = {}
    for p in paths:
        # Expect .../output/subreddits/NAME/frontpage.json
        m = re.search(r"/subreddits/([^/]+)/frontpage\.json$", p)
        if not m:
            continue
        folder = m.group(1)
        key = folder.lower()
        index[key] = p
    return index, paths


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
    posts_weight: float = DEFAULT_POSTS_WEIGHT,
    posts_halflife_days: float = DEFAULT_POSTS_HALFLIFE_DAYS,
    posts_generic_df_ratio: float = DEFAULT_POSTS_GENERIC_DF_RATIO,
    posts_ensure_k: int = DEFAULT_ENSURE_PHRASES_K,
    posts_stopwords_extra_path: Optional[str] = None,
    posts_anchor_generics: bool = True,
    posts_phrase_boost_bigram: float = DEFAULT_POSTS_PHRASE_BOOST_BIGRAM,
    posts_phrase_boost_trigram: float = DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM,
    posts_drop_generic_unigrams: bool = False,
    posts_phrase_stoplist_path: Optional[str] = None,
    posts_replace_generic_with_anchored: bool = False,
    posts_theme_penalty: float = 0.65,
    posts_theme_top_desc_k: int = 6,
    # Embedding rerank (optional)
    embed_rerank: bool = DEFAULT_EMBED_RERANK,
    embed_model: str = DEFAULT_EMBED_MODEL,
    embed_alpha: float = DEFAULT_EMBED_ALPHA,
    embed_k_terms: int = DEFAULT_EMBED_K_TERMS,
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
                    desc_tokens, docfreq, total_docs, max_ngram, min_df_bigram, min_df_trigram
                )

                # Ensure local multi-word phrases even if globally rare (keeps fuller phrases)
                if DEFAULT_ENSURE_PHRASES and DEFAULT_ENSURE_PHRASES_K > 0 and desc_tokens:
                    local_grams = tokens_to_ngrams(desc_tokens, max_ngram)
                    candidates = [
                        (g, tf)
                        for g, tf in local_grams.items()
                        if (g.count(" ") + 1) >= 2 and g not in desc_tfidf
                    ]
                    if candidates:
                        candidates.sort(key=lambda x: x[1], reverse=True)
                        for g, tf in candidates[:DEFAULT_ENSURE_PHRASES_K]:
                            n_words = g.count(" ") + 1
                            boost = DEFAULT_DESC_PHRASE_BOOST_BIGRAM if n_words == 2 else (
                                DEFAULT_DESC_PHRASE_BOOST_TRIGRAM if n_words == 3 else 1.0
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

                # Posts TF-IDF (optional)
                posts_scores: Counter = Counter()
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
                            posts_scores = compute_posts_tfidf_for_frontpage(
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
    ap = argparse.ArgumentParser(description="Extract subreddit keywords with TF-IDF from descriptions, names, and optional frontpage posts.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--input-file", type=str, help="Path to one page JSON file")
    g.add_argument("--input-glob", type=str, help="Glob for many page JSON files, e.g., 'output/pages/page_*.json'")
    ap.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR, help="Directory for output JSONL files")
    ap.add_argument("--topk", type=int, default=DEFAULT_TOPK, help="Top-K keywords per subreddit")
    ap.add_argument("--max-ngram", type=int, default=DEFAULT_MAX_NGRAM, help="Max n-gram length for TF-IDF")
    ap.add_argument("--name-weight", type=float, default=DEFAULT_NAME_WEIGHT, help="Weight multiplier for name-derived terms")
    ap.add_argument("--desc-weight", type=float, default=DEFAULT_DESC_WEIGHT, help="Weight multiplier for description TF-IDF")
    ap.add_argument("--min-df-bigram", type=int, default=2, help="Minimum document frequency to keep bigrams")
    ap.add_argument("--min-df-trigram", type=int, default=2, help="Minimum document frequency to keep trigrams")

    # Posts integration CLI
    ap.add_argument("--frontpage-glob", type=str, default=None, help="Glob for frontpage JSON files, e.g., 'output/subreddits/*/frontpage.json'")
    ap.add_argument("--posts-weight", type=float, default=DEFAULT_POSTS_WEIGHT, help="Weight multiplier for posts-derived scores (applied in merge)")
    ap.add_argument("--posts-halflife-days", type=float, default=DEFAULT_POSTS_HALFLIFE_DAYS, help="Recency halflife in days for posts weighting")
    ap.add_argument("--posts-generic-df-ratio", type=float, default=DEFAULT_POSTS_GENERIC_DF_RATIO, help="DF ratio threshold for considering a posts term 'generic'")
    ap.add_argument("--posts-ensure-k", type=int, default=DEFAULT_ENSURE_PHRASES_K, help="Ensure up to K local bigrams/trigrams per frontpage even if pruned by global DF")
    ap.add_argument("--posts-stopwords-extra", type=str, default=None, help="Path to newline-delimited file of extra stopwords to apply only to posts tokenization")
    ap.add_argument("--posts-phrase-boost-bigram", type=float, default=DEFAULT_POSTS_PHRASE_BOOST_BIGRAM, help="Phrase boost for bigrams in posts TF-IDF")
    ap.add_argument("--posts-phrase-boost-trigram", type=float, default=DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM, help="Phrase boost for trigrams in posts TF-IDF")
    ap.add_argument("--posts-drop-generic-unigrams", action="store_true", help="Drop unigram posts terms whose global DF ratio >= --posts-generic-df-ratio")
    ap.add_argument("--posts-theme-penalty", type=float, default=0.65, help="Multiplier to apply to posts terms with zero overlap to subreddit theme tokens (name + top description terms)")
    ap.add_argument("--posts-theme-top-desc-k", type=int, default=6, help="How many top description terms to include when forming the theme token set")
    # Embedding rerank
    ap.add_argument("--embed-rerank", action="store_true", help="Enable embedding-based reranking of terms for semantic alignment to subreddit theme")
    ap.add_argument("--embed-model", type=str, default=DEFAULT_EMBED_MODEL, help="SentenceTransformers model id (e.g., 'BAAI/bge-small-en-v1.5' or 'BAAI/bge-m3')")
    ap.add_argument("--embed-alpha", type=float, default=DEFAULT_EMBED_ALPHA, help="Blend factor for embedding similarity contribution")
    ap.add_argument("--embed-k-terms", type=int, default=DEFAULT_EMBED_K_TERMS, help="Rerank top-K terms by embeddings")
    ap.add_argument("--posts-phrase-stoplist", type=str, default=None, help="Path to newline-delimited file of phrases (bigrams/trigrams) to exclude from posts tokenization/DF")
    ap.add_argument("--posts-replace-generic-with-anchored", action="store_true", help="When anchoring generic uni/bi-grams, drop the original unanchored term")
    ap.add_argument("--no-posts-anchor-generics", action="store_true", help="Disable adding anchored variants for generic posts terms")

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
        embed_rerank=args.embed_rerank,
        embed_model=args.embed_model,
        embed_alpha=args.embed_alpha,
        embed_k_terms=args.embed_k_terms,
    )


if __name__ == "__main__":
    main()