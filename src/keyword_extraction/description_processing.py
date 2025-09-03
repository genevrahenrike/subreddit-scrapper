"""
Functions for processing subreddit descriptions.
"""
from typing import List

from .text_utils import filter_stop_tokens, tokenize_simple


def extract_desc_terms(description: str, max_ngram: int) -> List[str]:
    """
    Tokenize description and produce filtered tokens ready for n-gram counting.
    """
    if not description:
        return []
    tokens = tokenize_simple(description)
    tokens = filter_stop_tokens(tokens)
    return tokens