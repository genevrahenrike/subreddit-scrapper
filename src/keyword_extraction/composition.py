"""
Functions for theme-anchored composition of keywords.
"""
import math
import re
from collections import Counter
from typing import Iterable, List, Optional

import numpy as np
from . import config
from .constants import COMPOSE_TRIM_TAIL_TOKENS


def _normalize_anchor_phrase_from_title(title: str) -> str:
    if not title:
        return ""
    from .text_utils import tokenize_simple
    toks = tokenize_simple(title)
    return " ".join(toks)


def _simplify_seed_for_composition(term: str) -> str:
    """
    Lightly clean seed phrase for composition by trimming generic tail tokens like 'minute(s)', 'today', etc.
    Keeps phrase length >= 2 to avoid collapsing to single uninformative tokens.
    """
    if not term:
        return term
    toks = term.split()
    # Trim only tail tokens, preserving at least a bigram
    changed = False
    while len(toks) >= 2 and toks[-1] in COMPOSE_TRIM_TAIL_TOKENS:
        toks.pop()
        changed = True
    if changed and len(toks) >= 2:
        return " ".join(toks)
    return term


def _norm_nospace(s: Optional[str]) -> str:
    """
    Normalize by lowercasing and removing all whitespace characters.
    Also applies a light singularization for irregular plural 'lives' -> 'life'
    so that 'past lives' ~= 'past life'. This is intentionally conservative.
    """
    if not s:
        return ""
    ns = re.sub(r"\s+", "", s.strip().lower())
    # handle irregular plural: 'lives' -> 'life'
    ns = re.sub(r"lives$", "life", ns)
    return ns


def _equal_lex_loose(a: Optional[str], b: Optional[str]) -> bool:
    """
    Loose lexical equality to avoid composing anchor + seed when they are essentially the same term.
    - Lowercase
    - Strip whitespace
    - Ignore a single trailing 's' pluralization difference
    """
    na = _norm_nospace(a)
    nb = _norm_nospace(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # singularize one trailing 's'
    if na.endswith("s"):
        na_s = na[:-1]
    else:
        na_s = na
    if nb.endswith("s"):
        nb_s = nb[:-1]
    else:
        nb_s = nb
    return na_s == nb_s


def _compute_anchor_factor(
    anchor_phrase_lower: Optional[str],
    anchor_token: Optional[str],
    posts_docfreq: Counter,
    posts_total_docs: int,
    idf_power: float,
    score_mode: str,
    alpha: float,
    floor: float,
    cap: float,
    multiplier: float,
) -> float:
    """
    Compute multiplicative factor to apply to a seed score when composing an anchored variant.

    Modes:
      - "fraction": return multiplier (legacy behavior)
      - "idf_blend": return multiplier * max(floor, min(cap, (1-alpha) + alpha * idf_eff))
        where idf_eff = max(idf(anchor_phrase), idf(anchor_token), 1.0) ** idf_power
    """
    # Legacy mode (still respect floor/cap)
    if score_mode == "fraction":
        base = float(multiplier)
        if cap > 0:
            base = min(cap, base)
        return max(floor, base)

    N = max(1, int(posts_total_docs))

    def _idf_eff(term: Optional[str]) -> float:
        if not term:
            return 1.0
        df = posts_docfreq.get(term, 0)
        idf = math.log((1.0 + N) / (1.0 + df)) + 1.0
        return idf ** max(0.0, float(idf_power))

    anchor_idf = max(_idf_eff(anchor_phrase_lower), _idf_eff(anchor_token), 1.0)
    a = max(0.0, min(1.0, float(alpha)))
    base = (1.0 - a) + a * float(anchor_idf)
    factor = float(multiplier) * base
    if cap > 0:
        factor = min(cap, factor)
    factor = max(floor, factor)
    return factor


def compose_theme_anchored_from_posts(
    seed_scores_for_ordering: Counter,
    base_scores_for_scale: Counter,
    anchor_phrase_lower: Optional[str],
    anchor_token: Optional[str],
    top_m: int,
    include_unigrams: bool,
    max_final_words: int,
    multiplier: float,
    score_mode: str,
    anchor_alpha: float,
    anchor_floor: float,
    anchor_cap: float,
    max_per_sub: int,
    min_base_score: float,
    max_ratio: float,
    posts_docfreq: Counter,
    posts_total_docs: int,
    idf_power: float,
) -> Counter:
    """
    Compose anchored variants using:
      - seed_scores_for_ordering: ranking/selection signal (e.g., local TF or embed-reranked)
      - base_scores_for_scale: TF-IDF scale used for composed score magnitude
      - max_per_sub: cap number of composed variants per subreddit (0 = unlimited)
      - min_base_score: require seed TF-IDF >= this threshold to compose
      - max_ratio: cap composed/base ratio before rerank (0 = disabled)
    """
    if not seed_scores_for_ordering:
        return Counter()
    out = Counter()
    produced = 0
    # Select top-M seeds by the ordering signal
    items = sorted(seed_scores_for_ordering.items(), key=lambda kv: kv[1], reverse=True)
    seeds = items[: max(0, top_m)]

    # Compute a single anchor factor per subreddit (depends only on anchor + corpus)
    factor = _compute_anchor_factor(
        anchor_phrase_lower,
        anchor_token,
        posts_docfreq,
        posts_total_docs,
        idf_power,
        score_mode,
        anchor_alpha,
        anchor_floor,
        anchor_cap,
        multiplier,
    )

    # Normalize guards
    mbs = max(0.0, float(min_base_score))
    mr = float(max_ratio)

    for term, _seed_rank in seeds:
        if max_per_sub and produced >= max_per_sub:
            break
        seed = _simplify_seed_for_composition(term)
        # Avoid composing when the anchor equals the seed (e.g., "pastlife" vs "past life", including 'lives' -> 'life')
        if _equal_lex_loose(seed, anchor_phrase_lower) or _equal_lex_loose(seed, anchor_token):
            continue
        n_words = seed.count(" ") + 1
        if n_words == 1 and not include_unigrams:
            continue
        # Skip if already anchored by anchor token or phrase
        t_spaced = f" {seed} "
        if anchor_token and f" {anchor_token} " in t_spaced:
            continue
        if anchor_phrase_lower and t_spaced.startswith(f" {anchor_phrase_lower} "):
            continue
        # Compose variants (prefer phrase when available)
        variants: List[str] = []
        if anchor_phrase_lower:
            final_words = (anchor_phrase_lower.count(" ") + 1) + n_words
            if final_words <= max_final_words:
                variants.append(f"{anchor_phrase_lower} {seed}")
        if anchor_token:
            final_words = 1 + n_words
            if final_words <= max_final_words:
                variants.append(f"{anchor_token} {seed}")

        # Score composed variants on the same scale as base TF-IDF (fairness)
        sc_base = float(base_scores_for_scale.get(term, seed_scores_for_ordering.get(term, 0.0)))
        if sc_base < mbs:
            continue
        # Pre-rerank composed score with ratio cap
        composed_score = sc_base * factor
        if mr > 0.0:
            composed_score = min(composed_score, sc_base * mr)

        for v in variants:
            if v in base_scores_for_scale or v in out:
                continue
            out[v] = composed_score
            produced += 1
            if max_per_sub and produced >= max_per_sub:
                break
        if max_per_sub and produced >= max_per_sub:
            break
    return out


def compose_theme_anchored_from_seeds(
    seed_terms: Iterable[str],
    base_scores: Counter,
    anchor_phrase_lower: Optional[str],
    anchor_token: Optional[str],
    max_final_words: int,
    multiplier: float,
    subjects_bonus: float,
) -> Counter:
    """
    Compose anchored variants from an explicit list of seed phrases.
    Uses base_scores[seed] when available; otherwise uses a small baseline of 1.0.
    """
    out = Counter()
    for term in seed_terms:
        if not term:
            continue
        seed = _simplify_seed_for_composition(term)
        n_words = seed.count(" ") + 1
        if n_words < 2:
            continue  # prefer phrases
        # Avoid duplicating already-anchored
        t_spaced = f" {seed} "
        if anchor_token and f" {anchor_token} " in t_spaced:
            continue
        if anchor_phrase_lower and t_spaced.startswith(f" {anchor_phrase_lower} "):
            continue
        variants: List[str] = []
        if anchor_phrase_lower:
            final_words = (anchor_phrase_lower.count(" ") + 1) + n_words
            if final_words <= max_final_words:
                variants.append(f"{anchor_phrase_lower} {seed}")
        if anchor_token:
            final_words = 1 + n_words
            if final_words <= max_final_words:
                variants.append(f"{anchor_token} {seed}")
        if not variants:
            continue
        sc = base_scores.get(term, 1.0)
        for v in variants:
            if v not in out:
                out[v] = sc * multiplier * subjects_bonus
    return out


def _collect_present_grams(
    frontpage_data: dict,
    max_ngram: int,
    posts_extra_stopwords_set: set,
    posts_phrase_stoplist_set: set,
) -> set:
    """
    Collect normalized bigrams/trigrams present in the subreddit frontpage titles (and optional previews).
    Mirrors the tokenization used in posts TF-IDF.
    """
    present: set = set()
    posts = frontpage_data.get("posts") or []
    from .posts_processing import _tokenize_post_text
    from .text_utils import tokens_to_ngrams
    for post in posts:
        title = post.get("title", "") or ""
        preview = post.get("content_preview", "") or ""
        toks = _tokenize_post_text(title, preview, posts_extra_stopwords_set)
        grams = tokens_to_ngrams(toks, max_ngram)
        for g in list(grams.keys()):
            if (g.count(" ") + 1) >= 2:
                if posts_phrase_stoplist_set and g in posts_phrase_stoplist_set:
                    continue
                present.add(g)
    return present


def recase_anchored_display(
    term: str,
    canon: str,
    display_key: str,
    anchor_phrase_lower: Optional[str],
    anchor_title: Optional[str],
) -> str:
    # Map "mazda cx 5 oil change" -> "Mazda CX-5 oil change" when title is available
    if anchor_title and anchor_phrase_lower and term.startswith(anchor_phrase_lower + " "):
        suffix = term[len(anchor_phrase_lower):]  # keep leading space
        return f"{anchor_title}{suffix}"
    # Map "cx5 oil change" -> "CX5 oil change"
    if display_key and canon and term.startswith(canon + " "):
        suffix = term[len(canon):]  # keep leading space
        return f"{display_key}{suffix}"
    return term

def _compose_rank_seeds_with_embed(seed_base: Counter, theme_text: str, model_name: str, alpha: float) -> Counter:
    """
    Rerank seed phrases by combining normalized local TF/score with embedding similarity to the theme.
    combined = (1 - alpha) * norm_tf + alpha * sim01
    Returns a Counter mapping seed -> combined score.
    """
    from .embedding import _get_embedder, _HAS_ST
    try:
        if not _HAS_ST:
            return Counter(seed_base)
        embedder = _get_embedder(model_name)
        if embedder is None:
            return Counter(seed_base)
        # Limit pool size for performance
        items = list(seed_base.items())
        items.sort(key=lambda kv: kv[1], reverse=True)
        pool = items[:config.COMPOSE_SEED_MAX_POOL]
        terms = [t for t, _ in pool]
        max_tf = max((v for _, v in pool), default=1.0) or 1.0
        theme_emb = embedder.encode([theme_text], normalize_embeddings=True)
        term_embs = embedder.encode(terms, normalize_embeddings=True)
        from sentence_transformers.util import cos_sim
        try:
            sims = cos_sim(theme_emb, term_embs).cpu().numpy().reshape(-1)
        except Exception:
            def _cos(a, b):
                an = np.linalg.norm(a)
                bn = np.linalg.norm(b)
                if an <= 0 or bn <= 0:
                    return 0.0
                return float(np.dot(a, b) / (an * bn))
            sims = np.array([_cos(theme_emb[0], term_embs[i]) for i in range(len(terms))], dtype=float)
        sims01 = (sims + 1.0) / 2.0
        out = Counter()
        a = max(0.0, min(1.0, float(alpha)))
        for (term, tf), s in zip(pool, sims01):
            norm_tf = float(tf) / max_tf
            out[term] = (1.0 - a) * norm_tf + a * float(s)
        # Include any remaining terms with plain TF to avoid dropping tail
        for term, tf in items[config.COMPOSE_SEED_MAX_POOL:]:
            if term not in out:
                out[term] = float(tf) / (max_tf or 1.0)
        return out
    except Exception:
        return Counter(seed_base)