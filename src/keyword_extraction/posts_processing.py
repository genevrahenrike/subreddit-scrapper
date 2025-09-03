"""
Functions for processing subreddit posts.
"""
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple

from . import config
from .text_utils import filter_stop_tokens, tokens_to_ngrams, tokenize_simple


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


def _tokenize_post_text(title: str, preview: str, posts_extra_stopwords: Optional[Set[str]] = None) -> List[str]:
    parts: List[str] = []
    if title:
        parts.append(title)
    if config.DEFAULT_INCLUDE_CONTENT_PREVIEW and preview:
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
    posts_phrase_boost_bigram: float = config.DEFAULT_POSTS_PHRASE_BOOST_BIGRAM,
    posts_phrase_boost_trigram: float = config.DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM,
    drop_generic_unigrams: bool = False,
    generic_df_ratio: float = config.DEFAULT_POSTS_GENERIC_DF_RATIO,
    idf_power: float = config.DEFAULT_POSTS_IDF_POWER,
    engagement_alpha: float = config.DEFAULT_POSTS_ENGAGEMENT_ALPHA,
) -> Tuple[Counter, Counter]:
    """
    Compute posts TF-IDF with optional engagement blending and IDF damping.

    - Per-post factor blends neutral 1.0 with engagement via alpha:
        base = (1 - engagement_alpha) * 1.0 + engagement_alpha * (1 + log1p(score) + 0.5*log1p(comments))
    - Recency decay:
        recency = 0.5 ** (age_days / halflife_days)
    - Weighted TF sums across posts:
        TF_post = count_grams_in_post * (base * recency)

    Returns (tfidf_scores, local_grams_tf) where local_grams_tf are raw bigram/trigram counts for composition.
    """
    posts = frontpage_data.get("posts") or []
    if not posts:
        return Counter(), Counter()

    ref_time = _parse_scraped_at(frontpage_data)

    weighted_tf = Counter()
    local_grams_tf = Counter()  # unweighted counts for "ensure phrases" and composition
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
            recency = 1.0
        else:
            if created_ts.tzinfo is None:
                created_ts = created_ts.replace(tzinfo=timezone.utc)
            age = ref_time - created_ts
            age_days = max(age.total_seconds() / 86400.0, 0.0)
            recency = 0.5 ** (age_days / max(halflife_days, 0.1))

        engagement_component = 1.0 + math.log1p(score) + 0.5 * math.log1p(comments)
        base = (1.0 - engagement_alpha) * 1.0 + engagement_alpha * engagement_component
        post_weight = base * recency

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
        idf_eff = idf ** max(0.0, float(idf_power))
        boost = 1.0
        if n_words == 2:
            boost = posts_phrase_boost_bigram
        elif n_words == 3:
            boost = posts_phrase_boost_trigram
        tfidf[g] = tf * idf_eff * boost

    # Ensure local phrases (bigrams/trigrams) even if pruned; use top local grams by raw TF (unweighted)
    if config.DEFAULT_ENSURE_PHRASES and ensure_k > 0 and local_grams_tf:
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

    return tfidf, local_grams_tf


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
                out[anchored] = score * config.DEFAULT_POSTS_ANCHOR_MULTIPLIER
            if replace_original_generic and term in out:
                del out[term]
    return out