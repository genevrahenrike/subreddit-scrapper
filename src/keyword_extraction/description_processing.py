"""
Functions for processing subreddit descriptions.
"""
from typing import List, Optional, Set

from .text_utils import filter_stop_tokens, tokenize_simple, BOUNDARY_TOKEN

# Backward-compatible import; we inline a simple sentence-aware tokenizer to avoid
# altering global tokenize_simple() behavior across other modules.
import re
_SENT_SPLIT_RE = re.compile(r"[\.!\?\n]+")

def _tokenize_with_sentence_boundaries(text: str) -> List[str]:
    if not text:
        return []
    from .text_utils import tokenize_simple as _tok
    parts = _SENT_SPLIT_RE.split(text)
    toks: List[str] = []
    for part in parts:
        seg = (part or "").strip()
        if not seg:
            continue
        seg_toks = _tok(seg)
        if seg_toks:
            toks.extend(seg_toks)
            # Insert a boundary marker between sentences (as a special token)
            toks.append(BOUNDARY_TOKEN)
    # Trim trailing boundary if present
    if toks and toks[-1] == BOUNDARY_TOKEN:
        toks.pop()
    return toks


def extract_desc_terms(description: str, max_ngram: int, extra_stopwords: Optional[Set[str]] = None) -> List[str]:
    """
    Tokenize description and produce filtered tokens ready for n-gram counting.
    Optional extra_stopwords let callers inject dynamic, corpus-derived common words.
    Also inserts sentence boundaries so n-grams do not bridge sentences.
    """
    if not description:
        return []
    # Use sentence-aware tokenization to avoid cross-sentence n-grams
    tokens = _tokenize_with_sentence_boundaries(description)
    # Insert boundary sentinels when removing stopwords so we don't bridge across them
    tokens = filter_stop_tokens(tokens, extra_stopwords=extra_stopwords, insert_boundaries=True)  # type: ignore
    return tokens