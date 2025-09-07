# Subreddit Keyword Extraction Pipeline — Technical Notes

This document provides a comprehensive overview of the keyword extraction pipeline implemented in [`__main__.py`](src/keyword_extraction/__main__.py:1). It details the system's architecture, from initial tokenization to advanced semantic reranking, and summarizes the experimental findings that have shaped its design.

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

*   **Code Anchors:** [`scoring.build_docfreq()`](src/keyword_extraction/scoring.py:14), [`posts_processing.build_posts_docfreq()`](src/keyword_extraction/posts_processing.py:56)

**Stage 2: Per-Subreddit Keyword Generation**

For each subreddit, keywords are generated from three primary sources:

1.  **Name:** The subreddit's name is robustly parsed to extract meaningful terms. This involves:
    *   Splitting on delimiters (`_`, `-`), camelCase, and digit boundaries.
    *   Applying heuristic and ML-based segmentation for concatenated lowercase names (e.g., "itisallspelllikethis" -> "it is all spell like this").
    *   Expanding common acronyms (e.g., "fps" -> "first person shooter").
    *   The full, cleaned name phrase (e.g., "Alcohol Liver Support") is given a significant score boost to ensure it ranks highly.
    *   **Code Anchors:** [`name_processing.extract_name_terms()`](src/keyword_extraction/name_processing.py:16), [`name_processing.extract_name_full_phrase()`](src/keyword_extraction/name_processing.py:93)

2.  **Description:** The description is processed using a standard TF-IDF model, with boosts applied to bigrams and trigrams to favor phrases. An "ensure phrases" mechanism guarantees that the top locally frequent phrases are retained, even if they are rare globally.
    *   **Code Anchors:** [`scoring.compute_tfidf_per_doc()`](src/keyword_extraction/scoring.py:36)

3.  **Posts:** Frontpage post titles are processed with a more sophisticated TF-IDF model that incorporates:
    *   **Engagement Weighting:** The term frequency (TF) is weighted by the post's score and comment count (`1 + log1p(score) + 0.5*log1p(comments)`).
    *   **Recency Weighting:** Scores decay based on the post's age, with a configurable half-life (`--posts-halflife-days`).
    *   **Code Anchors:** [`posts_processing.compute_posts_tfidf_for_frontpage()`](src/keyword_extraction/posts_processing.py:95)

**Stage 3: Scoring and Merging**

The scores from the three sources are merged, with configurable weights (`--name-weight`, `--desc-weight`, `--posts-weight`). At this stage, two important thematic alignment features are applied:

1.  **Anchored Variants (Generics):** Generic, high-frequency terms from posts are optionally replaced with an "anchored" version (e.g., "system" -> "valorant system"). This provides context and improves relevance.
    *   **Code Anchors:** [`posts_processing.apply_anchored_variants_for_generic_posts_terms()`](src/keyword_extraction/posts_processing.py:206)

2.  **Theme Penalty:** A penalty is applied to posts-only terms that have no token overlap with the subreddit's "theme" (defined as its name and top description keywords). This down-weights terms that are likely off-topic.
    *   **Code Anchors:** [`__main__.process_inputs()`](src/keyword_extraction/__main__.py:81)

3.  **Theme-Anchored Composition (New):** Compose high-quality composite keywords by prepending a subreddit anchor to top posts phrases and/or subject-whitelisted phrases present in the subreddit’s frontpage titles. Two anchor forms are supported:
    *   Subreddit token (e.g., "cx5").
    *   Frontpage title phrase if present (e.g., "Mazda CX-5" -> "mazda cx 5" as the normalized anchor). Display is recased to "Mazda CX-5 …" where applicable.
    *   Composition draws seeds from:
        - Top-M posts TF-IDF phrases by score.
        - A whitelist of subject phrases (e.g., "oil change", "cabin air filter") when they appear in the subreddit’s own posts.
    *   Scores for composed variants are a fraction of the source phrase score (configurable), so originals remain the primary signal.
    *   **Code Anchors:** [`composition.compose_theme_anchored_from_posts()`](src/keyword_extraction/composition.py:125), [`composition.compose_theme_anchored_from_seeds()`](src/keyword_extraction/composition.py:227), [`composition._collect_present_grams()`](src/keyword_extraction/composition.py:272), [`composition.recase_anchored_display()`](src/keyword_extraction/composition.py:299)

**Stage 4: Optional Embedding-Based Reranking**

To further enhance semantic relevance, an optional reranking step can be enabled (`--embed-rerank`). This uses a pre-trained `sentence-transformers` model to re-score the top candidate keywords based on their cosine similarity to the subreddit's theme vector.

*   **Mechanism:** `new_score = old_score * ((1 - alpha) + alpha * similarity)`
*   This boosts terms that are semantically related to the theme, even if they don't share any tokens.
*   **Code Anchors:** [`embedding.embed_rerank_terms()`](src/keyword_extraction/embedding.py:101)

**Stage 5: Normalization and Output**

Finally, the scores for each subreddit's keywords are normalized to sum to 1.0, and the top K (`--topk`) are written to a JSONL file.

*   **Code Anchors:** [`scoring.normalize_weights()`](src/keyword_extraction/scoring.py:125)

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
python3 -m src.keyword_extraction \
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
- `--compose-anchor-multiplier FLOAT`: score fraction applied to composed terms (default 1.0).
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
  python3 -m src.keyword_extraction \
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
- Implementation and CLI wiring are in [`__main__.py`](src/keyword_extraction/__main__.py:1). Search for:
  - desc-idf-power, posts-idf-power
  - posts-engagement-alpha
  - compose-seed-source, compose-seed-embed, compose-seed-embed-alpha
  - embed-candidate-pool
- Composition now uses local grams surfaced during posts processing; whitelist composition calls are removed.

LLM as a final optional stage
- v2 is designed to be a high-quality programmatic baseline. If desired, add a thin LLM pass only on borderline phrases (e.g., to canonicalize wording or dedupe near variants), keeping cost low and provenance intact.

Summary
- v2 makes the pipeline less brittle in sparse/biased corpora, removes editorial dependence, and uses embeddings where they add semantic lift without becoming the sole arbiter. The result is a more robust, scalable alternative or precursor to LLM-heavy approaches.

### Follow-up Analysis: Scoring of Composite Phrases

A sensitivity analysis was performed to understand why high-quality, human-validated composite phrases (e.g., "Mazda CX-5 oil change") receive significantly lower scores than their high-frequency, single-phrase counterparts (e.g., "oil change").

**Core Finding:** The low scores are a direct and expected consequence of the **multiplicative scoring logic** used during composition.

**Scoring Mechanism:**
1.  The pipeline identifies a base keyword (e.g., "oil change") and an anchor (e.g., "mazda cx-5"), each with its own TF-IDF-based score.
2.  These scores are normalized to a [0, 1] range.
3.  The final score for the composite phrase is calculated by **multiplying** these normalized scores.

**Implication:**
- Multiplying two numbers that are less than 1.0 will always produce a smaller number. For example, if "oil change" has a normalized score of 0.3 and "mazda cx-5" has a normalized score of 0.4, the composite score is `0.3 * 0.4 = 0.12`.
- This mathematical property is the sole reason for the lower scores. It is not influenced by Document Frequency (DF) at the composition stage, nor is it related to the BGE embedding model, which is only used as an optional final re-ranking step *after* all initial scores are calculated.

**Interpretation and Trade-offs:**
- **Current Behavior:** The system correctly identifies and generates valuable, long-tail composite keywords. However, the scoring mechanism inherently ranks them lower than their popular, constituent parts. This makes them vulnerable to being filtered out if a global quality threshold is applied.
- **Is this a problem?** It depends on the goal.
    - If the goal is to have a single ranked list where only the absolute highest-signal terms appear, the current behavior is acceptable.
    - If the goal is to treat these "value-engineered" composite phrases as premium outputs that deserve special consideration, then their low scores are problematic as they don't reflect their engineered quality.
- **Alternative Perspectives:**
    - One could argue that a composite phrase like "Mazda CX-5 oil change" is a significant quality *improvement* over its parts and its score should reflect that (i.e., be higher, not lower).
    - Alternatively, these composite phrases could be treated as a separate category of output, not to be ranked against standard TF-IDF keywords, but presented as a distinct, high-quality set.

**Path Forward:**
A fair ranking system would require a more rigorous scoring method for composites. This could involve exploring alternative scoring functions (e.g., averaging, weighted-averaging) or applying source-specific normalization. For now, the most effective way to ensure these valuable composites appear in the final output is to use a sufficiently large `--topk` value or the `--ensure-k-from-posts-composed` flag, rather than relying on a score-based quality filter.
## 6. v2.1 Composite Fairness: IDF-anchored scoring, separated scale, and guardrails

Motivation
- Earlier composition multiplied two sub-1.0 normalized signals, systematically suppressing high-quality composites.
- v2.1 replaces this with an IDF-anchored factor and composes on the same TF-IDF scale as seeds, so composed phrases are fairly comparable to original posts terms.

Implementation overview (code anchors)
- Separate selection vs magnitude:
  - Seed selection (ordering) can use local TF or embed-reranked signals; see [composition.compose_theme_anchored_from_posts()](src/keyword_extraction/composition.py:125).
  - Magnitude (scale) for composed terms uses the posts TF-IDF base from [posts_processing.compute_posts_tfidf_for_frontpage()](src/keyword_extraction/posts_processing.py:95).
- Anchor factor driven by posts corpus IDF:
  - Factor computation lives in [composition._compute_anchor_factor()](src/keyword_extraction/composition.py:79) and uses posts DF from [posts_processing.build_posts_docfreq()](src/keyword_extraction/posts_processing.py:56).
  - Formula:
    - idf_eff(anchor) = max(idf(anchor_phrase), idf(anchor_token), 1.0) ** posts_idf_power
    - factor = compose_anchor_multiplier × max(floor, min(cap, (1 − alpha) + alpha × idf_eff(anchor)))
  - Defaults are safe and non-suppressive:
    - compose_anchor_multiplier = 1.0
    - compose_anchor_score_mode = "idf_blend"
    - alpha = 0.7, floor = 1.0, cap = 2.0
- Guardrails to avoid flooding and ensure quality:
  - Hard cap per subreddit: DEFAULT_COMPOSE_ANCHOR_MAX_PER_SUB (see [config.py](src/keyword_extraction/config.py:57)).
  - Minimum seed strength: DEFAULT_COMPOSE_ANCHOR_MIN_BASE_SCORE (seed TF-IDF must be ≥ threshold) (see [config.py](src/keyword_extraction/config.py:58)).
  - Ratio cap: DEFAULT_COMPOSE_ANCHOR_MAX_RATIO to bound composed/base score pre-rerank (see [config.py](src/keyword_extraction/config.py:59)).
  - Independent weighting for composed terms in merge via posts-composed-weight; see [`__main__.process_inputs()`](src/keyword_extraction/__main__.py:81).

Scoring details (one-pass summary)
- Selection order uses "seed_scores_for_ordering" (local TF, TF-IDF, or embed-ranked) to pick the top-M seeds.
- Each composed variant is scored on the posts TF-IDF scale via the seed’s base TF-IDF score, scaled by the anchor factor and bounded by guardrails in [composition.compose_theme_anchored_from_posts()](src/keyword_extraction/composition.py:125).

New CLI flags
- --posts-composed-weight FLOAT (defaults to --posts-weight if omitted)
- --compose-anchor-score-mode {fraction,idf_blend} (default idf_blend)
- --compose-anchor-alpha FLOAT
- --compose-anchor-floor FLOAT
- --compose-anchor-cap FLOAT
- --compose-anchor-max-per-sub INT (0 = unlimited; default guards on)
- --compose-anchor-min-base-score FLOAT
- --compose-anchor-max-ratio FLOAT
- All flags are wired in [__main__.main()](src/keyword_extraction/__main__.py:491).

Empirical results on page_31 (r/CX5 page cohort)
- v2e (pre-fairness baseline with idf_blend defaults but without guardrails/separate scale): 
  - subs_with_posts_composed ≈ 12/250; total_composed = 16
  - mean rank ≈ 25.56; ratio (composed/seed) ≈ 1.36 (n=4) → under-surfaced composites.
- v2f (fair factor + 1.0 multiplier, no guardrails): 
  - subs_with_posts_composed ≈ 244/250; total_composed = 7,598
  - mean rank ≈ 20.21; ratio mean ≈ 2.43 (median ≈ 2.85) → strong but over-abundant (flooding risk).
- v2.1 (v2g; fair factor + guardrails):
  - subs_with_posts_composed ≈ 242/250; total_composed = 1,931
  - mean rank ≈ 7.49; ratio mean ≈ 2.45 (median ≈ 2.86), min rank = 1, max ≈ 31
  - Interpretation: composed phrases now surface near the top when justified, without flooding.

Recommended v2.1 configuration (example)
- Deterministic, engagement-off, seed embed rerank, composed-only embed nudging, with fairness/guardrails:
```bash
python3 -m src.keyword_extraction \
  --input-file output/pages/page_31.json \
  --frontpage-glob 'output/subreddits/*/frontpage.json' \
  --output-dir output/keywords_v2g \
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
  --compose-anchor-score-mode idf_blend \
  --compose-anchor-alpha 0.7 \
  --compose-anchor-floor 1.0 \
  --compose-anchor-cap 2.0 \
  --compose-anchor-max-per-sub 8 \
  --compose-anchor-min-base-score 3.0 \
  --compose-anchor-max-ratio 2.0 \
  --posts-composed-weight 1.5 \
  --posts-ensure-k 10 \
  --embed-rerank \
  --embed-model 'BAAI/bge-small-en-v1.5' \
  --embed-alpha 0.35 \
  --embed-k-terms 120 \
  --embed-candidate-pool posts_composed
```

Tuning guidance
- More composed presence: increase --compose-anchor-max-per-sub, lower --compose-anchor-min-base-score modestly, or raise --posts-composed-weight.
- Stronger anchor influence: increase --compose-anchor-alpha and/or --compose-anchor-cap, but keep --compose-anchor-max-ratio reasonable (≈2.0–3.0).
- Stricter outputs: decrease --compose-anchor-cap, lower --compose-anchor-max-per-sub, or increase --compose-anchor-min-base-score.

Backward compatibility
- Legacy "fraction" mode is preserved via --compose-anchor-score-mode fraction, which behaves like the old multiplier-only path (now with a non-suppressive floor if configured).

Where to look in code
- Anchor factor and fairness: [`composition._compute_anchor_factor()`](src/keyword_extraction/composition.py:79)
- Composition with separated ordering vs scale and guardrails: [`composition.compose_theme_anchored_from_posts()`](src/keyword_extraction/composition.py:125)
- Posts TF-IDF base scale: [`posts_processing.compute_posts_tfidf_for_frontpage()`](src/keyword_extraction/posts_processing.py:95)
- CLI wiring: [`__main__.main()`](src/keyword_extraction/__main__.py:491)

## 7. v2.2: Cross-subreddit commonness, Zipf-based filtering, and phrase-level DF pruning

Motivation
- Reduce inclusion of low-value, common conversational words without maintaining large curated stoplists.
- Use the actual cross-subreddit corpus to identify generic tokens per run.
- Add a language-level prior (general English frequency) to further suppress boilerplate unigrams.
- Extend “generic” logic beyond unigrams to phrases, with safety guards for small corpora.

What changed (code anchors)
- Cross-subreddit dynamic common unigrams (description):
  - Build DF across selected pages then derive a per-run set of common unigrams and use them as extra stopwords during description tokenization.
  - Guardrails: only enabled when total_docs ≥ 5; also require a minimum absolute DF to avoid small-corpus over-pruning.
  - Implementation and wiring: [`__main__.process_inputs()`](src/keyword_extraction/__main__.py:196) → extra_stopwords passed into [`description_processing.extract_desc_terms()`](src/keyword_extraction/description_processing.py:9) and scored via [`scoring.compute_tfidf_per_doc()`](src/keyword_extraction/scoring.py:36).
- General English frequency (Zipf) for tokens:
  - Optional per-token filter using wordfreq’s Zipf scale inside [`text_utils.filter_stop_tokens()`](src/keyword_extraction/text_utils.py:173).
  - Controlled by config and CLI (see below). Falls back safely if the library isn’t installed.
- Phrase-level generic DF pruning:
  - Description TF-IDF: optional drop of globally generic bigrams/trigrams by DF ratio in [`scoring.compute_tfidf_per_doc()`](src/keyword_extraction/scoring.py:36).
  - Posts TF-IDF: optional drop of globally generic bigrams/trigrams by DF ratio in [`posts_processing.compute_posts_tfidf_for_frontpage()`](src/keyword_extraction/posts_processing.py:95), including respect for ensure-K to avoid flooding.
- Optional inclusion of content preview:
  - Tokenization gate exposed in CLI; wired to config read by [`posts_processing._tokenize_post_text()`](src/keyword_extraction/posts_processing.py:43).

New/updated defaults and config switches
- Config (selected):
  - Dynamic toggles:
    - DEFAULT_USE_CURATED_STOPWORDS (default True)
    - DEFAULT_USE_GENERAL_ZIPF (default True), DEFAULT_GENERAL_ZIPF_THRESHOLD (default 5.0)
  - Description genericity:
    - DEFAULT_DESC_DROP_GENERIC_UNIGRAMS (default True), DEFAULT_DESC_GENERIC_DF_RATIO (default 0.10)
    - DEFAULT_DESC_DROP_GENERIC_PHRASES (default False), DEFAULT_DESC_GENERIC_PHRASE_DF_RATIO (default 0.50)
  - Posts genericity:
    - DEFAULT_POSTS_DROP_GENERIC_PHRASES (default False), DEFAULT_POSTS_GENERIC_PHRASE_DF_RATIO (default 0.50)
- CLI (added):
  - Stopword and Zipf controls:
    - --use-curated-stopwords / --no-curated-stopwords
    - --use-general-zipf / --no-general-zipf
    - --general-zipf-threshold FLOAT
  - Preview gate:
    - --include-content-preview (off by default)

Example runs
- Strict, DF-driven baseline (no curated list; rely on corpus + Zipf):
  ```
  python3 -m src.keyword_extraction \
    --input-glob 'output/pages/page_*.json' \
    --output-dir output/keywords_v22 \
    --topk 25 \
    --min-df-bigram 2 \
    --min-df-trigram 2 \
    --no-curated-stopwords \
    --use-general-zipf \
    --general-zipf-threshold 5.0
  ```
- Phrase pruning on sparse corpora (use cautiously; start with descriptions only):
  - Set config DEFAULT_DESC_DROP_GENERIC_PHRASES=True and DEFAULT_DESC_GENERIC_PHRASE_DF_RATIO in [config.py](src/keyword_extraction/config.py:1), or extend CLI (future) similarly.

Operational guidance
- If outputs still include boilerplate unigrams:
  - Disable curated stopwords, enable Zipf filtering, and keep the threshold near 5.0–5.5.
  - Ensure at least 5 page files in your run so dynamic unigram derivation is enabled (guarded).
- If multi-gram chatter floods:
  - Turn on description phrase generic pruning first; if that’s insufficient, enable posts phrase pruning next.
  - Keep ensure-K locals enabled to preserve strong local phrases.
- Small-corpus safety:
  - Dynamic unigrams are disabled under 5 documents; either expand the corpus or rely more on Zipf in those cases.

Effect
- Reduced generic unigrams without manually curating large stoplists.
- More room for salient multi-word phrases by suppressing common fillers.
- Phrase-level pruning options help prevent “chatter” phrases from dominating, while ensure-K preserves high-signal locals.

Notes
- All filters are deterministic and accept reasonable defaults. The embedding reranker stage remains optional and unchanged.
- If wordfreq cannot be installed due to environment limits, Zipf filtering silently disables; dynamic DF features still work.

## 8. Operational v2.3: Subset alignment, resumability, incremental DF extension, and memory-safe embedding

This section documents operational upgrades added to support very large corpora and staged runs while minimizing memory pressure and enabling reliable resume/extend workflows. Implementation entrypoint: [__main__.py](src/keyword_extraction/__main__.py:1).

What’s new (high level)
- Frontpage-backed subset alignment: Process only subreddits that have a scraped frontpage, and build description DF over the same subset for consistent IDF.
- Resumability and atomic writes: Skip already-finished outputs, persist DF caches, and commit outputs atomically to prevent corruption.
- Incremental DF extension: Extend existing DF caches with new pages/frontpages; run the next batch without recomputing from scratch.
- Memory-safe embedding rerank pass: A standalone “embedding-only” mode reranks existing outputs in a fresh, low-RAM process so GPU acceleration (MPS/CUDA) has headroom.

8.1 Frontpage-backed subset alignment
- Motivation: When only a subset of communities has frontpage data (e.g., 100k of 300k), you can prevent “thin” communities from diluting DF and avoid producing outputs for communities without posts.
- How it works:
  - --require-frontpage limits per-subreddit processing to those with a matching frontpage.json discovered via the frontpage glob.
  - Description DF is computed only over the same canonical key subset (allowed_keys) for IDF consistency.
- CLI:
  - --require-frontpage
- Code anchors:
  - CLI and filtering in [__main__.py](src/keyword_extraction/__main__.py:1)
  - Subset-aware DF: [scoring.build_docfreq()](src/keyword_extraction/scoring.py:14)

8.2 Resumability and atomic writes
- Motivation: Long multi-hour runs must be restartable and protected against partial files.
- Features:
  - --resume skips input page files that already have a non-empty output file.
  - --overwrite forces recompute (ignoring caches and replacing outputs).
  - --desc-df-cache and --posts-df-cache persist DF to JSON; re-used on resumes.
  - Atomic writes: outputs are written to page.keywords.jsonl.tmp and finalized via an atomic replace.
- CLI:
  - --resume, --overwrite, --desc-df-cache PATH, --posts-df-cache PATH
- Code anchors:
  - Main orchestration and atomic finalize in [__main__.py](src/keyword_extraction/__main__.py:1)
  - Description DF build/load: [scoring.build_docfreq()](src/keyword_extraction/scoring.py:14)

8.3 Incremental DF extension (additive runs)
- Motivation: Efficiently extend from 100k to 150k without recomputing DF for the initial 100k.
- How it works:
  - --extend-df-caches merges DF counts from the current inputs into the existing caches (assume inputs are NEW pages to avoid double-counting).
  - Posts DF cache stores the set of canonical keys (“keys”) so only missing frontpages are added.
  - Description DF cache stores an allowed_keys_hash when using --require-frontpage to ensure subset consistency; when extending, the hash is refreshed along with counts.
- CLI:
  - --extend-df-caches (used with the same --desc-df-cache and --posts-df-cache paths)
- Code anchors:
  - Incremental logic and cache guards in [__main__.py](src/keyword_extraction/__main__.py:1)
  - DF builder: [scoring.build_docfreq()](src/keyword_extraction/scoring.py:14), [posts_processing.build_posts_docfreq()](src/keyword_extraction/posts_processing.py:56)

8.4 Memory optimization and GPU-safe embedding pass
- Motivation: Global DF counters can occupy significant RAM during pass 1. To ensure GPU VRAM/Unified Memory headroom for embedding, run the rerank in a separate, lean process.
- Embedding-only rerank mode:
  - --embed-only-input-dir DIR reads existing baseline JSONL outputs, reconstructs the theme from the record (whole name phrase + top description keywords already in the record), and performs embedding-based rerank WITHOUT rebuilding DF or touching /pages data.
  - This mode uses minimal RAM, letting MPS/CUDA allocate larger batches for SentenceTransformers.
- Device controls:
  - EMBED_DEVICE=mps|cuda|cpu and optional EMBED_BATCH_SIZE (e.g., 64, 32, 16) via environment variables.
- Code anchors:
  - Rerank: [embedding.embed_rerank_terms()](src/keyword_extraction/embedding.py:101)
  - Device selection and banner: [embedding._select_device()](src/keyword_extraction/embedding.py:29)
  - CLI wiring: [__main__.py](src/keyword_extraction/__main__.py:1)

8.5 Quick recipes

A) Baseline over frontpage-backed subset with caches (deterministic, no embeddings)
```bash
python3 -m src.keyword_extraction \
  --input-glob 'output/pages/page_*.json' \
  --frontpage-glob 'output/subreddits/*/frontpage.json' \
  --require-frontpage \
  --output-dir output/keywords_10k_v22 \
  --resume \
  --desc-df-cache output/cache/desc_df_10k_v22.json \
  --posts-df-cache output/cache/posts_df_10k_v22.json \
  --topk 40 \
  --name-weight 3.0 --desc-weight 1.0 \
  --posts-weight 1.5 --posts-composed-weight 1.5 \
  --min-df-bigram 2 --min-df-trigram 2 \
  --posts-ensure-k 10 \
  --posts-generic-df-ratio 0.10 --posts-drop-generic-unigrams \
  --posts-phrase-boost-bigram 1.35 --posts-phrase-boost-trigram 1.7 \
  --posts-stopwords-extra config/posts_stopwords_extra.txt \
  --posts-phrase-stoplist config/posts_phrase_stoplist.txt \
  --desc-idf-power 0.8 --posts-idf-power 0.4 \
  --posts-engagement-alpha 0.0 \
  --compose-seed-source posts_local_tf \
  --compose-anchor-top-m 200 \
  --compose-anchor-score-mode idf_blend \
  --compose-anchor-alpha 0.7 --compose-anchor-floor 1.0 --compose-anchor-cap 2.0 \
  --compose-anchor-max-per-sub 8 --compose-anchor-min-base-score 3.0 \
  --compose-anchor-max-ratio 2.0 \
  --include-content-preview
```

B) Embedding-only rerank (GPU MPS/CUDA), low memory, streaming existing outputs
```bash
EMBED_DEVICE=mps EMBED_BATCH_SIZE=64 PYTORCH_ENABLE_MPS_FALLBACK=1 LLM_SUMMARY=0 \
python3 -m src.keyword_extraction \
  --embed-only-input-dir output/keywords_10k_v22 \
  --output-dir output/keywords_10k_v22_embed \
  --resume \
  --embed-rerank \
  --embed-model 'BAAI/bge-small-en-v1.5' \
  --embed-alpha 0.35 \
  --embed-k-terms 120 \
  --embed-candidate-pool posts_composed \
  --posts-theme-top-desc-k 6
```
- Switch to CUDA with EMBED_DEVICE=cuda. Reduce EMBED_BATCH_SIZE (e.g., 32/16) if memory is tight.

C) Incremental extension (next 50k pages added to DF), then rerank only new outputs
```bash
# Extend DF caches with NEW pages only (avoid double-counting by not re-passing old pages)
python3 -m src.keyword_extraction \
  --input-glob 'output/pages/page_150_to_200.json' \
  --frontpage-glob 'output/subreddits/*/frontpage.json' \
  --require-frontpage \
  --extend-df-caches \
  --output-dir output/keywords_10k_v22 \
  --resume \
  --desc-df-cache output/cache/desc_df_10k_v22.json \
  --posts-df-cache output/cache/posts_df_10k_v22.json \
  --topk 40 ... (same knobs as baseline)

# Embedding-only rerank over the combined baseline outputs (skips already-reranked pages)
EMBED_DEVICE=mps EMBED_BATCH_SIZE=64 PYTORCH_ENABLE_MPS_FALLBACK=1 LLM_SUMMARY=0 \
python3 -m src.keyword_extraction \
  --embed-only-input-dir output/keywords_10k_v22 \
  --output-dir output/keywords_10k_v22_embed \
  --resume \
  --embed-rerank \
  --embed-model 'BAAI/bge-small-en-v1.5' \
  --embed-alpha 0.35 --embed-k-terms 120 \
  --embed-candidate-pool posts_composed
```

8.6 Notes and caveats
- Subset hash: When using --require-frontpage, the description DF cache is tagged with the subset hash (allowed_keys_hash) to guarantee consistency across runs. Extending caches updates counts for new inputs; passing an older cache against a different subset without extension will be rejected for safety.
- Double-counting: --extend-df-caches assumes the current input pages and frontpages are NEW. Do not pass overlapping inputs from previous runs when extending.
- Memory: Avoid caching frontpage JSONs in memory for massive runs; the pipeline loads each JSON per subreddit on demand (streaming). This keeps peak RSS lower and leaves GPU VRAM/Unified Memory for embeddings.
- Scripts: An example end-to-end runner is available at [scripts/run_keywords_10k.sh](scripts/run_keywords_10k.sh:1).

Relevant anchors
- Orchestration and CLI: [__main__.py](src/keyword_extraction/__main__.py:1)
- Description DF build: [scoring.build_docfreq()](src/keyword_extraction/scoring.py:14)
- Posts DF build and TF-IDF: [posts_processing.build_posts_docfreq()](src/keyword_extraction/posts_processing.py:56), [posts_processing.compute_posts_tfidf_for_frontpage()](src/keyword_extraction/posts_processing.py:95)
- Composition fairness and display recasing: [composition.compose_theme_anchored_from_posts()](src/keyword_extraction/composition.py:125), [composition.recase_anchored_display()](src/keyword_extraction/composition.py:299)
- Embedding rerank and device routing: [embedding.embed_rerank_terms()](src/keyword_extraction/embedding.py:101), [embedding._select_device()](src/keyword_extraction/embedding.py:29)
## 9. v2.4 Programmatic decontamination and deduping (no curated stoplists)

Motivation
- Eliminate manual, curated stoplists which are brittle and non-scalable.
- Replace with deterministic, corpus-driven filters and light, in-pipeline cleanup to suppress obvious artifacts without editorial maintenance.

What changed (code)
- Deprecated manual stoplists:
  - Posts phrase stoplist flag is now ignored; a deprecation banner is printed in [__main__.py](src/keyword_extraction/__main__.py:1).
  - Posts extra stopwords file is also ignored with a deprecation banner in [__main__.py](src/keyword_extraction/__main__.py:1).
- In-pipeline term cleanup (new CLI in [__main__.main()](src/keyword_extraction/__main__.py:1)):
  - --clean-collapse-adj-dups / --no-clean-collapse-adj-dups
    - Collapse adjacent duplicate words in terms (e.g., "big big problem" -> "big problem").
  - --clean-dedupe-near / --no-clean-dedupe-near
    - Near-duplicate dedupe by normalized alnum key (merges spacing/punct casing variants; keeps higher score or source-preferred).
  - --drop-nonlatin
    - Drop terms containing CJK/Cyrillic/Greek scripts for English-focused runs (off by default).
  - --max-nonascii-ratio FLOAT
    - Drop terms whose non-ASCII ratio exceeds the threshold (negative disables; default -1).
- Programmatic filters retained:
  - Cross-subreddit DF and DF-ratio controls (v2.2).
  - Optional embedding rerank targeting specific sources for semantic cleanup (v2, v2.1).

Runner updates
- Batch script updated to remove curated stoplist flags and turn on programmatic cleanup:
  - See [scripts/run_keywords_10k.sh](scripts/run_keywords_10k.sh:1), which now passes:
    - --clean-collapse-adj-dups
    - --clean-dedupe-near
    - --drop-nonlatin
    - --max-nonascii-ratio 0.50
  - And no longer passes:
    - --posts-phrase-stoplist PATH (deprecated; ignored)
    - --posts-stopwords-extra PATH (deprecated; ignored)

Example (frontpage-backed subset, deterministic baseline)
```bash
python3 -m src.keyword_extraction \
  --input-glob 'output/pages/page_*.json' \
  --frontpage-glob 'output/subreddits/*/frontpage.json' \
  --require-frontpage \
  --output-dir output/keywords_v24 \
  --resume \
  --desc-df-cache output/cache/desc_df_v24.json \
  --posts-df-cache output/cache/posts_df_v24.json \
  --topk 40 \
  --name-weight 3.0 --desc-weight 1.0 \
  --posts-weight 1.5 --posts-composed-weight 1.5 \
  --min-df-bigram 2 --min-df-trigram 2 \
  --posts-ensure-k 10 \
  --posts-generic-df-ratio 0.10 --posts-drop-generic-unigrams \
  --posts-phrase-boost-bigram 1.35 --posts-phrase-boost-trigram 1.7 \
  --desc-idf-power 0.8 --posts-idf-power 0.4 \
  --posts-engagement-alpha 0.0 \
  --compose-seed-source posts_local_tf \
  --compose-anchor-top-m 200 \
  --compose-anchor-score-mode idf_blend \
  --compose-anchor-alpha 0.7 --compose-anchor-floor 1.0 --compose-anchor-cap 2.0 \
  --compose-anchor-max-per-sub 8 --compose-anchor-min-base-score 3.0 \
  --compose-anchor-max-ratio 2.0 \
  --clean-collapse-adj-dups \
  --clean-dedupe-near \
  --drop-nonlatin \
  --max-nonascii-ratio 0.50 \
  --include-content-preview
```

Optional post-processing (streamed, no curated lists)
- For already-produced JSONL outputs, a programmatic cleaner is provided at [scripts/clean_keywords_post.py](scripts/clean_keywords_post.py:1):
  - Two-pass DF over provided files (directory or single file).
  - Drops globally generic terms by DF ratio for chosen sources (e.g., posts_union), with per-run min-doc guard.
  - Collapses adjacent duplicates; dedupes near-identicals by normalized key; filters technical artifacts and non-Latin scripts.
  - Renormalizes weights post-drop/dedupe.
- Example:
```bash
python3 scripts/clean_keywords_post.py \
  --input-dir output/keywords_v24 \
  --output-dir output/keywords_v24_clean \
  --df-drop-threshold 0.25 \
  --df-drop-sources posts_union \
  --emit-stats
```

Rationale and behavior
- Removes manual “cheats” and replaces them with deterministic, corpus-derived suppression.
- Adjacent-duplicate collapse and near-duplicate dedupe address repetitive/redundant phrase artifacts and spacing/punct variants without curated lists.
- Non-Latin and non-ASCII controls provide a clean English-focused mode while keeping multilingual optionality (see embed model swaps).
- Curated phrase files remain in the repo only for historical reference; the pipeline ignores them at runtime.

Where to look in code
- CLI and cleanup integration: [__main__.py](src/keyword_extraction/__main__.py:1)
- Runner with new knobs: [scripts/run_keywords_10k.sh](scripts/run_keywords_10k.sh:1)
- Post-processor (streamed DF + cleanup): [scripts/clean_keywords_post.py](scripts/clean_keywords_post.py:1)

## 10. v2.5 Operational updates: robust resume, no-empty outputs, and range-based incremental runner

Motivation
- Previous passes could leave zero-byte or placeholder per-page outputs, which then caused --resume to skip reprocessing incorrectly.
- Incremental staging benefits from selecting page ranges directly from existing output/pages/page_*.json and repairing stale outputs automatically.

What changed (code anchors)
- Valid resume checks (no more skipping on empty files)
  - Resume now skips only when an existing output contains at least one valid JSON object line. Zero-byte or non-JSON placeholder files are treated as invalid and forced to recompute.
  - Logic: [_is_valid_output_file()](src/keyword_extraction/__main__.py:138), applied in the resume check at [__main__.process_inputs()](src/keyword_extraction/__main__.py:441).

- No empty outputs are created
  - If a page yields zero subreddits passing filters (e.g., --require-frontpage), the pipeline does not create an empty output file. Temporary .tmp is deleted and any prior zero-byte placeholder is removed.
  - Finalize behavior: see [__main__.process_inputs()](src/keyword_extraction/__main__.py:886).

- Incremental runner with page-range subset + stale output repair
  - New/updated runner: [scripts/run_keywords_overnight_coreext_150k.sh](scripts/run_keywords_overnight_coreext_150k.sh:1).
  - Supports three modes to choose input pages:
    1) Positional glob:
       ./scripts/run_keywords_overnight_coreext_150k.sh 'output/pages/page_1001.json'
    2) Env glob:
       export NEW_PAGE_GLOB='output/pages/page_1001.json'
       ./scripts/run_keywords_overnight_coreext_150k.sh
    3) Page range over existing chunked pages:
       START_PAGE=1001 END_PAGE=1200 ./scripts/run_keywords_overnight_coreext_150k.sh
       - Optional PAGES_DIR (default output/pages) and SUBSET_ROOT (default output/pages_subset)
       - The script builds a subset directory of symlinks/copies and runs the pipeline with --extend-df-caches and --require-frontpage.

  - Stale output repair (pre-run)
    - When REPAIR_BAD_OUTPUTS=1 (default), the runner removes any per-page outputs that are zero-byte or have no JSON lines before invoking the pipeline, so those pages will be recomputed instead of being skipped by --resume.
    - See the repair block at [scripts/run_keywords_overnight_coreext_150k.sh](scripts/run_keywords_overnight_coreext_150k.sh:84).

Incremental usage (examples)
- Range-based (recommended, frontpage-backed subset):
  ```
  START_PAGE=401 END_PAGE=600 REPAIR_BAD_OUTPUTS=1 \
  ./scripts/run_keywords_overnight_coreext_150k.sh
  ```
  - This constructs a subset from output/pages/page_401..page_600.json, repairs stale outputs in the target OUT_DIR, and runs:
    - --require-frontpage
    - --extend-df-caches
    - --emit-core-extended (core=name+description, extended=posts+posts_composed)
    - --resume and all tuned knobs
  - Output directory default: output/keywords_10k_v24_k100_coreext

- Explicit glob:
  ```
  REPAIR_BAD_OUTPUTS=1 ./scripts/run_keywords_overnight_coreext_150k.sh 'output/pages/page_401.json'
  ```

Why this is robust
- DF caches
  - Posts DF extension merges only unseen frontpage keys (delta) even if overlapped pages are passed, avoiding double counting. See [__main__.process_inputs()](src/keyword_extraction/__main__.py:316).
  - Description DF cache, when present and not --overwrite, is loaded as-is and is not merge-added in this flow; no double-count risk. See [__main__.process_inputs()](src/keyword_extraction/__main__.py:381).
- Expected tapering at higher ranks
  - With --require-frontpage, later page_N files will gradually contain fewer subreddits having a scraped frontpage.json, so per-page “records written” naturally declines and may hit 0. This is correct behavior (filtering to the frontpage-backed subset).

Embedding-only note (CLI surface)
- The current CLI requires one of --input-file or --input-glob. A standalone “embed-only input dir” flag is not exposed at present; any embedding rerank should be performed within a normal baseline run by passing --embed-rerank and related flags.
- Embedding controls: [embedding.embed_rerank_terms()](src/keyword_extraction/embedding.py:101), device selection at [embedding._select_device()](src/keyword_extraction/embedding.py:29). To enable GPU on Apple Silicon: set EMBED_DEVICE=mps and (optionally) EMBED_BATCH_SIZE.

Summary of v2.5 operational behavior
- Resume only skips truly valid outputs; zero-byte/placeholder files are recomputed.
- No empty outputs are created when zero records are produced for a page.
- Range-based incremental runner selects input pages directly from output/pages chunk files; optional pre-run repair removes stale outputs to unblock recomputation.
- Posts DF extend remains additive and safe against double counting; description DF cache loads as-is unless intentionally rebuilt.