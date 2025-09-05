import re
from collections import Counter
from typing import Iterable, List, Optional, Set

from . import config
from .constants import EXPANSIONS, HEURISTIC_SUFFIXES, STOPWORDS

# Sentinel token inserted at removed-stopword positions to prevent forming n-grams across them.
# This avoids unnatural phrases like "common topics oil" from "... common topics include oil ..."
BOUNDARY_TOKEN = "<_>"

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


def filter_stop_tokens(
    tokens: Iterable[str],
    extra_stopwords: Optional[Set[str]] = None,
    insert_boundaries: bool = False,
) -> List[str]:
    """
    Token filter that supports:
    - Optional curated stopword usage (config.DEFAULT_USE_CURATED_STOPWORDS)
    - Caller-provided extra stopwords
    - Numeric/year pruning and short-token pruning with a small allowlist
    - Optional general English frequency pruning (Zipf ≥ threshold) via wordfreq
    - Optional insertion of BOUNDARY_TOKEN at removed-stopword positions (prevents cross-stopword n-grams)
    """
    out: List[str] = []
    extra = extra_stopwords or set()

    # Optional general English frequency via wordfreq (Zipf scale).
    # Safe to import here; Python caches imports so this is negligible after first call.
    try:
        from wordfreq import zipf_frequency as _zipf_frequency  # type: ignore
        _has_wf = True
    except Exception:
        _has_wf = False

    allow_short = {"ai", "vr", "uk", "us", "eu", "3d"}

    def _append_boundary_once():
        if insert_boundaries and out and out[-1] != BOUNDARY_TOKEN:
            out.append(BOUNDARY_TOKEN)

    for t in tokens:
        lt = (t or "").lower().strip()
        if not lt:
            _append_boundary_once()
            continue

        # Curated stopwords (optional)
        if config.DEFAULT_USE_CURATED_STOPWORDS and (lt in STOPWORDS):
            _append_boundary_once()
            continue
        # Always respect caller-provided extra stopwords
        if lt in extra:
            _append_boundary_once()
            continue

        # Drop numeric-only tokens and common years
        if lt.isdigit():
            _append_boundary_once()
            continue
        if re.fullmatch(r"(19|20)\d{2}", lt):
            _append_boundary_once()
            continue
        if re.fullmatch(r"\d{2,}", lt):
            _append_boundary_once()
            continue

        # Short tokens (allow some domain-meaningful short tokens)
        if len(lt) < config.DEFAULT_MIN_TOKEN_LEN and lt not in allow_short:
            _append_boundary_once()
            continue

        # General English frequency pruning for very common words (unigrams only)
        if config.DEFAULT_USE_GENERAL_ZIPF and _has_wf and lt not in allow_short:
            try:
                if _zipf_frequency(lt, "en") >= float(config.DEFAULT_GENERAL_ZIPF_THRESHOLD):
                    _append_boundary_once()
                    continue
            except Exception:
                # if wordfreq throws for any reason, skip pruning for this token
                pass

        # Keep token
        out.append(lt)

    # Trim trailing boundary if present
    if out and out[-1] == BOUNDARY_TOKEN:
        out.pop()

    return out


def tokens_to_ngrams(tokens: List[str], max_n: int) -> Counter:
    """
    Build contiguous n-grams but do not cross BOUNDARY_TOKEN markers.
    Any window that contains the boundary sentinel is skipped.
    """
    grams = Counter()
    n = len(tokens)
    for k in range(1, max_n + 1):
        if n < k:
            break
        for i in range(0, n - k + 1):
            window = tokens[i : i + k]
            if BOUNDARY_TOKEN in window:
                continue
            gram = " ".join(window)
            if gram:
                grams[gram] += 1
    return grams