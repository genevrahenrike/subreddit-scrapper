"""
Functions for processing subreddit names.
"""
import re
from typing import List, Tuple

from .text_utils import (
    normalize_space,
    segment_token_lower,
    split_camel_and_digits,
    expand_token,
    filter_stop_tokens,
)


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