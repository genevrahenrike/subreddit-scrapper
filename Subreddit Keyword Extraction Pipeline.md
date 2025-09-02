# Subreddit Keyword Extraction Pipeline — Technical Notes

This document provides a comprehensive overview of the keyword extraction pipeline implemented in [`keyword_extraction.py`](keyword_extraction.py:1). It details the system's architecture, from initial tokenization to advanced semantic reranking, and summarizes the experimental findings that have shaped its design.

## 1. Core Objective: Thematic Keyword Extraction

The primary goal is to produce a rank-ordered list of keywords that are thematically relevant to a given subreddit. The system is designed to favor salient, multi-word phrases over isolated, generic unigrams, ensuring that the output reflects the core topics and jargon of the community. This is achieved through a hybrid approach, combining deterministic TF-IDF scoring with optional, more advanced semantic alignment techniques.

**Key Guarantees:**

*   **Phrase-Centric:** The pipeline is biased toward multi-word phrases, ensuring that concepts like "credit card debt" are favored over "credit" and "debt" in isolation.
*   **Thematic Alignment:** Keywords are scored not only on frequency and uniqueness but also on their relevance to the subreddit's central theme, as defined by its name and description.
*   **Provenance:** Every keyword is tagged with its source(s) (e.g., `name`, `description`, `posts`, or combinations like `name+posts`), providing clear traceability.
*   **Scalability and Determinism:** The core pipeline is 100% deterministic and designed to be computationally efficient, allowing for repeatable, low-cost runs across hundreds of thousands of subreddits.

## 2. System Architecture: A Multi-Stage Pipeline

The keyword extraction process is a multi-stage pipeline, with each stage progressively refining the keyword set.

**Stage 1: Document Frequency (DF) Calculation**

The pipeline begins by calculating the document frequency for all n-grams (1 to 3 words) across two distinct corpora:

1.  **Description Corpus:** All subreddit descriptions from the input `page_*.json` files.
2.  **Posts Corpus:** All frontpage post titles from the files specified by `--frontpage-glob`.

This global DF is crucial for the TF-IDF calculation in the next stage, as it allows the system to down-weight terms that are common across many subreddits (e.g., "game," "video," "discussion").

*   **Code Anchors:** [`build_docfreq()`](keyword_extraction.py:912), [`build_posts_docfreq()`](keyword_extraction.py:627)

**Stage 2: Per-Subreddit Keyword Generation**

For each subreddit, keywords are generated from three primary sources:

1.  **Name:** The subreddit's name is robustly parsed to extract meaningful terms. This involves:
    *   Splitting on delimiters (`_`, `-`), camelCase, and digit boundaries.
    *   Applying heuristic and ML-based segmentation for concatenated lowercase names (e.g., "itisallspelllikethis" -> "it is all spell like this").
    *   Expanding common acronyms (e.g., "fps" -> "first person shooter").
    *   The full, cleaned name phrase (e.g., "Alcohol Liver Support") is given a significant score boost to ensure it ranks highly.
    *   **Code Anchors:** [`extract_name_terms()`](keyword_extraction.py:401), [`extract_name_full_phrase()`](keyword_extraction.py:478)

2.  **Description:** The description is processed using a standard TF-IDF model, with boosts applied to bigrams and trigrams to favor phrases. An "ensure phrases" mechanism guarantees that the top locally frequent phrases are retained, even if they are rare globally.
    *   **Code Anchors:** [`compute_tfidf_per_doc()`](keyword_extraction.py:934)

3.  **Posts:** Frontpage post titles are processed with a more sophisticated TF-IDF model that incorporates:
    *   **Engagement Weighting:** The term frequency (TF) is weighted by the post's score and comment count (`1 + log1p(score) + 0.5*log1p(comments)`).
    *   **Recency Weighting:** Scores decay based on the post's age, with a configurable half-life (`--posts-halflife-days`).
    *   **Code Anchors:** [`compute_posts_tfidf_for_frontpage()`](keyword_extraction.py:666)

**Stage 3: Scoring and Merging**

The scores from the three sources are merged, with configurable weights (`--name-weight`, `--desc-weight`, `--posts-weight`). At this stage, two important thematic alignment features are applied:

1.  **Anchored Variants (Generics):** Generic, high-frequency terms from posts are optionally replaced with an "anchored" version (e.g., "system" -> "valorant system"). This provides context and improves relevance.
    *   **Code Anchors:** [`apply_anchored_variants_for_generic_posts_terms()`](keyword_extraction.py:768)

2.  **Theme Penalty:** A penalty is applied to posts-only terms that have no token overlap with the subreddit's "theme" (defined as its name and top description keywords). This down-weights terms that are likely off-topic.
    *   **Code Anchors:** [`process_inputs()`](keyword_extraction.py:1148)

3.  **Theme-Anchored Composition (New):** Compose high-quality composite keywords by prepending a subreddit anchor to top posts phrases and/or subject-whitelisted phrases present in the subreddit’s frontpage titles. Two anchor forms are supported:
    *   Subreddit token (e.g., "cx5").
    *   Frontpage title phrase if present (e.g., "Mazda CX-5" -> "mazda cx 5" as the normalized anchor). Display is recased to "Mazda CX-5 …" where applicable.
    *   Composition draws seeds from:
        - Top-M posts TF-IDF phrases by score.
        - A whitelist of subject phrases (e.g., "oil change", "cabin air filter") when they appear in the subreddit’s own posts.
    *   Scores for composed variants are a fraction of the source phrase score (configurable), so originals remain the primary signal.
    *   **Code Anchors:** [`compose_theme_anchored_from_posts()`](keyword_extraction.py:812), [`compose_theme_anchored_from_seeds()`](keyword_extraction.py:872), [`_collect_present_grams()`](keyword_extraction.py:897), [`recase_anchored_display()`](keyword_extraction.py:864)

**Stage 4: Optional Embedding-Based Reranking**

To further enhance semantic relevance, an optional reranking step can be enabled (`--embed-rerank`). This uses a pre-trained `sentence-transformers` model to re-score the top candidate keywords based on their cosine similarity to the subreddit's theme vector.

*   **Mechanism:** `new_score = old_score * ((1 - alpha) + alpha * similarity)`
*   This boosts terms that are semantically related to the theme, even if they don't share any tokens.
*   **Code Anchors:** [`embed_rerank_terms()`](keyword_extraction.py:1063)

**Stage 5: Normalization and Output**

Finally, the scores for each subreddit's keywords are normalized to sum to 1.0, and the top K (`--topk`) are written to a JSONL file.

*   **Code Anchors:** [`normalize_weights()`](keyword_extraction.py:1020)

## 3. Experimental Findings and Tuning

Experiments were conducted to evaluate the impact of various tuning parameters, the new theme-anchored composition step, and the embedding reranker.

**Key Findings:**

*   **Phrase Share:** The combination of phrase boosts, composition, and optional embedding reranking increased the share and quality of multi-word phrases, surfacing subreddit-themed composites such as "Mazda CX-5 cabin air filter" for `r/CX5`.
*   **Thematic Anchoring:** Composed variants tend to promote actionable, high-signal subjects that match the subreddit theme. When the subreddit’s frontpage meta title is present, display casing preserves readable brand/model forms (e.g., "Mazda CX-5 …").
*   **Quality-Weighted Composition:** Because composed scores are multiplicative fractions of source TF-IDF, high-engagement subjects naturally outrank low-signal chatter. This avoids flooding results with mechanically composed but low-value phrases.
*   **Qualitative Improvements:**
    *   For `r/CX5`, the output includes anchored maintenance terms such as "Mazda CX-5 cabin air filter" and "CX5 cabin air filter" from top posts (video with high engagement).
    *   For `r/prius`, themed composites like "toyota aqua prius" remain favored where topical.
    *   For content-heavy subs, composition helps contextualize generic subjects (e.g., "ranked season") into on-brand phrases ("Pokémon Pocket ranked season").

**Recommended Configuration:**

The following command represents the best-performing configuration, balancing thematic relevance, phrase quality, and computational cost. It also enables subject-whitelist composition for practical, on-brand composites:

```bash
python3 keyword_extraction.py \
    --input-glob 'output/pages/page_*.json' \
    --frontpage-glob 'output/subreddits/*/frontpage.json' \
    --output-dir output/keywords_final \
    --topk 20 \
    --name-weight 3.0 \
    --desc-weight 1.0 \
    --posts-weight 1.5 \
    --posts-halflife-days 5 \
    --min-df-trigram 2 \
    --posts-generic-df-ratio 0.10 \
    --posts-drop-generic-unigrams \
    --posts-phrase-boost-bigram 1.35 \

### Analysis of Composition Behavior: `r/CX5` Example

A test run on `page_31.json`, which contains `r/CX5`, demonstrates the behavior of the theme-anchored composition.

*   **High-Engagement Composites:** The post "Cabin air filter: < $10 and 1 minute of your time." has very high engagement (795 score, 92 comments). The pipeline correctly identifies "cabin air filter" as a key phrase and, using the frontpage title "Mazda CX-5" as an anchor, produces high-scoring keywords:
    *   `Mazda CX-5 cabin air filter`
    *   `CX5 cabin air filter`
*   **Low-Engagement Composites:** The post "maintenance/oil change" has very low engagement (score 1, comments 1). While "oil change" is on the subject whitelist (`config/compose_subjects.txt`), its base score from TF-IDF is negligible compared to high-engagement posts. The final composed score (`base_score * multiplier * bonus`) is therefore too low for "Mazda CX-5 oil change" to rank in the top keywords for the subreddit.

This outcome is by design. The system correctly prioritizes keywords based on demonstrated community engagement, preventing low-signal or off-topic posts from generating noisy composite keywords. To guarantee the inclusion of specific composed terms like "oil change" when they appear locally, even with low engagement, further enhancements would be needed, such as:
1.  A mechanism to "ensure" a certain number of whitelist-composed terms appear in the output, regardless of score.
2.  Basing the `base_score` for whitelisted subjects on their raw local frequency (TF) instead of the full TF-IDF, which would give them a more stable floor for composition.
    --posts-phrase-boost-trigram 1.7 \
    --posts-stopwords-extra config/posts_stopwords_extra.txt \
    --posts-phrase-stoplist config/posts_phrase_stoplist.txt \
    --posts-replace-generic-with-anchored \
    --posts-theme-penalty 0.55 \
    --compose-subjects-path config/compose_subjects.txt \
    --embed-rerank \
    --embed-model 'BAAI/bge-small-en-v1.5' \
    --embed-alpha 0.35
```

Composition controls (CLI):
- `--no-compose-anchor-posts`: disable composition entirely (enabled by default).
- `--compose-anchor-multiplier FLOAT`: score fraction applied to composed terms (default 0.85).
- `--compose-anchor-top-m INT`: top-M posts phrases to consider for composition (default 20).
- `--compose-anchor-include-unigrams`: allow composing from unigram posts terms (off by default).
- `--compose-anchor-max-final-words INT`: cap final composed phrase length (default 6).
- `--no-compose-anchor-use-title`: do not use meta.title as the anchor phrase; fall back to subreddit token.
- `--compose-subjects-path PATH`: newline-delimited subject whitelist (e.g., "oil change", "cabin air filter") composed only when present in local posts.

## 4. Future Enhancements

*   **Multilingual Support:** The pipeline is ready for multilingual subreddits by simply switching to a multilingual model like `BAAI/bge-m3` via the `--embed-model` flag.
*   **Theme Vector Composition:** The "theme" is currently derived from the name and description. Experimenting with including a small number of top posts-derived keywords could further refine the theme vector, especially for subreddits with sparse descriptions.
*   **Lemmatization:** While currently disabled for performance, optional lemmatization could be added to group different inflections of the same word (e.g., "draw," "drawing," "draws"), potentially improving the accuracy of the DF and TF-IDF scores.
### Score Distribution and Quality Tiers

An analysis of the keyword scores from the final `embed` configuration reveals a wide, positively skewed distribution. This is a desirable characteristic, as it indicates that the model is effective at identifying exceptionally relevant terms and separating them from the bulk of more common, less-thematic keywords.

**Score Distribution (from `page_3.json` analysis):**

*   **Mean Score:** 60.98
*   **Standard Deviation:** 69.72
*   **95th Percentile:** 147.56
*   **99th Percentile:** 380.49

This distribution allows for the creation of clear, data-driven quality tiers, which can be used for filtering or prioritizing keywords in downstream applications:

*   **Premium/Core (Score > 150):** The top ~5% of keywords. These are consistently the core, foundational themes of a subreddit (e.g., `r/burgers -> burger`).
*   **High-Quality (Score 75-150):** The top 25% of keywords. This tier captures highly relevant phrases and topics central to the community's discourse (e.g., `r/tattooadvice -> tattoo today`).
*   **Standard (Score 50-75):** The top 50% of keywords. These are generally relevant but may be more niche or less central than the higher tiers.
*   **Lower-Confidence (<50):** The bottom 50%. This group contains a mix of niche-but-relevant terms, generic conversational phrases, and some noise. The low scores correctly identify these as less thematically important.
## 5. v2 Upgrades: DF-damped scoring, engagement-decoupled posts, local-TF composition, and targeted semantic boosting

This section documents substantial changes introduced in v2 to address practical weaknesses surfaced by the r/CX5 “oil change” case study and similar niches.

Why these changes
- Engagement coupling: We removed engagement from being implicitly “baked-in” to quality. Engagement can be useful but volatile (age and platform dynamics). v2 keeps engagement as an optional blend, not a hardwired quality proxy.
- Weak DF corpus: Descriptions are sparse, and posts corpus (titles) can be thin for many subs. Global DF can overpower locality. v2 damps IDF and strengthens local phrase retainers.
- Whitelist brittleness: Subject whitelists are editorial overhead and can bias outputs. v2 drops whitelist composition in favor of data-driven local grams, with optional semantic guidance.
- Better use of embeddings: IDF can suppress valuable terms in sparse data. We leverage embeddings where they help most: as an optional reranker and for seed selection in composition.

What changed (behavioral)
- Posts engagement decoupled: Per-post TF weight becomes a blend between neutral 1.0 and an engagement factor. Default alpha=0.0 makes engagement “off” by default, allowing you to opt-in.
- DF power damping: Both description and posts IDF are exponentiated to a 0..1 power to reduce DF dominance. This stabilizes scoring in sparse corpora.
- Local TF returned for composition: The posts stage now surfaces local bigram/trigram TF (not just TF-IDF), enabling strong local seeds even when IDF is weak or pruning is aggressive.
- Whitelist composition removed: Composition is now driven by top-M local seeds (TF or TF-IDF or hybrid), optionally reranked semantically. No curated lists required.
- Targeted embedding usage:
  - Seed rerank for composition (optional): Use the theme vector to promote semantically relevant seeds (e.g., “oil change”), even if they are low-engagement.
  - Embedding rerank candidate pooling: Limit semantic reranking to specific source subsets (e.g., posts_composed only) to avoid over-steering the whole list.

New CLI knobs (additive)
- Engagement blend: 
  - --posts-engagement-alpha FLOAT (default 0.0)
- IDF damping:
  - --desc-idf-power FLOAT (default 0.85)
  - --posts-idf-power FLOAT (default 0.65)
- Composition seed source:
  - --compose-seed-source {posts_tfidf,posts_local_tf,hybrid} (default hybrid)
  - --compose-seed-embed (enable semantic rerank of seeds)
  - --compose-seed-embed-alpha FLOAT (default 0.6..0.9 typical)
- Embedding rerank candidate pool:
  - --embed-candidate-pool {union,posts,posts_composed,desc,non_name} (default union)
- Deprecated (kept for compatibility, ignored):
  - --compose-subjects-path, --compose-subjects-bonus

Design rationale aligned to observed issues
- Don’t over-index on engagement: Now an optional multiplicative factor controlled by --posts-engagement-alpha. Default 0.0 eliminates accidental bias toward aging/viral artifacts.
- Reduce DF sway in sparse text: IDF power damping flattens overly sharp DF curves. Combined with existing ensure-K locals, this yields more resilient phrasal coverage from small inputs.
- Replace whitelist with data: Local TF seeds reflect what the community actually says; optional semantic seed rerank makes those seeds theme-aligned without curation burden.
- Use embeddings with surgical scope: Rerank only posts_composed (or posts) to steer composed outputs without disturbing global ordering from name/description signals.

Reproduction examples (v2 patterns)
- Engagement-off, DF-damped, local-TF seeds with semantic seed rerank, rerank only composed outputs:
  ```
  python3 keyword_extraction.py \
      --input-file output/pages/page_31.json \
      --frontpage-glob 'output/subreddits/*/frontpage.json' \
      --output-dir output/keywords_v2d \
      --topk 40 \
      --name-weight 3.0 \
      --desc-weight 1.0 \
      --posts-weight 1.5 \
      --posts-halflife-days 3650 \
      --min-df-bigram 2 \
      --min-df-trigram 2 \
      --posts-drop-generic-unigrams \
      --posts-generic-df-ratio 0.10 \
      --posts-phrase-boost-bigram 1.35 \
      --posts-phrase-boost-trigram 1.7 \
      --posts-stopwords-extra config/posts_stopwords_extra.txt \
      --posts-phrase-stoplist config/posts_phrase_stoplist.txt \
      --desc-idf-power 0.8 \
      --posts-idf-power 0.4 \
      --posts-engagement-alpha 0.0 \
      --compose-seed-source posts_local_tf \
      --compose-seed-embed \
      --compose-seed-embed-alpha 0.9 \
      --compose-anchor-top-m 200 \
      --posts-ensure-k 10 \
      --embed-rerank \
      --embed-model 'BAAI/bge-small-en-v1.5' \
      --embed-alpha 0.35 \
      --embed-k-terms 120 \
      --embed-candidate-pool posts_composed
  ```
  Notes:
  - Engagement off isolates topicality.
  - Lower posts IDF power (0.4) suppresses DF overreach.
  - Seed-embed alpha 0.9 strongly favors thematically pertinent seeds in composition (e.g., “oil change”).
  - Embedding rerank applied only to posts_composed terms (candidate pool), preserving core ordering elsewhere.

Observed result on r/CX5 (page_31)
- With the configuration above, the final Top-K contains on-topic terms including:
  - “cx5”
  - “cabin air filter” and variants
  - “oil” (seed presence; whether “oil change” appears depends on exact local TF vs. other seeds, but seed rerank raises its odds without engagement bias)
- The pipeline no longer requires a subject whitelist to surface these topics; composition derives from the subreddit’s own local content.

Practical guidance
- If you want stronger composed variants like “Mazda CX-5 oil change”, prefer:
  - Seed source = posts_local_tf or hybrid
  - Higher --compose-anchor-top-m to widen seed pool
  - Higher --compose-seed-embed-alpha if your theme is clean (name + top desc)
  - Consider --embed-candidate-pool posts_composed so only composed terms are nudged semantically

Where to look in code
- Implementation and CLI wiring are in [`keyword_extraction.py`](keyword_extraction.py). Search for:
  - desc-idf-power, posts-idf-power
  - posts-engagement-alpha
  - compose-seed-source, compose-seed-embed, compose-seed-embed-alpha
  - embed-candidate-pool
- Composition now uses local grams surfaced during posts processing; whitelist composition calls are removed.

LLM as a final optional stage
- v2 is designed to be a high-quality programmatic baseline. If desired, add a thin LLM pass only on borderline phrases (e.g., to canonicalize wording or dedupe near variants), keeping cost low and provenance intact.

Summary
- v2 makes the pipeline less brittle in sparse/biased corpora, removes editorial dependence, and uses embeddings where they add semantic lift without becoming the sole arbiter. The result is a more robust, scalable alternative or precursor to LLM-heavy approaches.