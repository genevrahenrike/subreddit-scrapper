"""
Functions for scoring and merging keywords from different sources.
"""
import math
from collections import Counter
from typing import Dict, List, Set, Tuple

from . import config
from .description_processing import extract_desc_terms
from .subreddit_data import iter_subreddits_from_file
from .text_utils import tokens_to_ngrams


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
    desc_idf_power: float = config.DEFAULT_DESC_IDF_POWER,
    desc_drop_generic_unigrams: bool = config.DEFAULT_DESC_DROP_GENERIC_UNIGRAMS,
    desc_generic_df_ratio: float = config.DEFAULT_DESC_GENERIC_DF_RATIO,
    desc_drop_generic_phrases: bool = config.DEFAULT_DESC_DROP_GENERIC_PHRASES,
    desc_generic_phrase_df_ratio: float = config.DEFAULT_DESC_GENERIC_PHRASE_DF_RATIO,
) -> Counter:
    """
    Compute TF-IDF for description text of a single document.
    idf = log((1 + N) / (1 + df)) + 1  (smooth), optionally damped:
      idf_eff = idf ** desc_idf_power (0..1 reduces DF dominance)
    score = tf * idf_eff * boost

    Additionally:
      - Prunes rare multi-grams:
          * bigrams kept only if df >= min_df_bigram
          * trigrams kept only if df >= min_df_trigram
      - Optionally drops globally generic unigrams based on DF ratio across subreddits:
          * if desc_drop_generic_unigrams and (df / N) >= desc_generic_df_ratio
      - Optionally drops globally generic phrases (bi/tri-grams) based on DF ratio across subreddits:
          * if desc_drop_generic_phrases and (df / N) >= desc_generic_phrase_df_ratio
    """
    grams = tokens_to_ngrams(tokens, max_ngram)
    tfidf = Counter()
    for g, tf in grams.items():
        n_words = g.count(" ") + 1
        df = docfreq.get(g, 0)

        # Rare multi-gram pruning
        if n_words == 2 and df < min_df_bigram:
            continue
        if n_words == 3 and df < min_df_trigram:
            continue

        # Generic unigram pruning by DF ratio across descriptions
        if n_words == 1 and desc_drop_generic_unigrams:
            df_ratio = (df / total_docs) if total_docs > 0 else 0.0
            if df_ratio >= desc_generic_df_ratio:
                continue

        # Generic phrase pruning by DF ratio across descriptions
        if n_words >= 2 and desc_drop_generic_phrases:
            df_ratio = (df / total_docs) if total_docs > 0 else 0.0
            if df_ratio >= desc_generic_phrase_df_ratio:
                continue

        idf = math.log((1.0 + total_docs) / (1.0 + df)) + 1.0
        idf_eff = idf ** max(0.0, float(desc_idf_power))
        boost = 1.0
        if n_words == 2:
            boost = config.DEFAULT_DESC_PHRASE_BOOST_BIGRAM
        elif n_words == 3:
            boost = config.DEFAULT_DESC_PHRASE_BOOST_TRIGRAM
        tfidf[g] = tf * idf_eff * boost
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