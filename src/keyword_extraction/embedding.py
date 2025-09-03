"""
Functions for embedding-based reranking of keywords.
"""
from collections import Counter
from typing import Dict, List, Optional, Tuple

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
    candidate_pool: str,
) -> Dict[str, Tuple[float, str]]:
    """
    Rerank top-K terms by multiplying their scores by a function of semantic similarity to theme_text.
    new_score = old_score * ((1 - alpha) + alpha * similarity), where similarity in [0,1].

    candidate_pool controls which terms are eligible:
      - "union": all terms
      - "posts": any term whose source includes posts/posts_composed
      - "posts_composed": only composed posts terms
      - "desc": any term whose source includes description
      - "non_name": exclude name-only terms
    """
    if not theme_text or not _HAS_ST:
        return merged
    embedder = _get_embedder(model_name)
    if embedder is None:
        return merged

    # Select candidates by current score then filter by pool
    items = sorted(merged.items(), key=lambda kv: kv[1][0], reverse=True)

    def _in_pool(src: str) -> bool:
        if candidate_pool == "union":
            return True
        if candidate_pool == "posts":
            return ("posts" in src) or ("posts_composed" in src)
        if candidate_pool == "posts_composed":
            return "posts_composed" in src
        if candidate_pool == "desc":
            return "description" in src
        if candidate_pool == "non_name":
            parts = set(src.split("+"))
            return not (parts == {"name"})
        return True

    filtered = [(t, (s, src)) for (t, (s, src)) in items if _in_pool(src)]
    top_items = filtered[: max(0, k_terms)]
    if not top_items:
        return merged

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