# Subreddit Keyword Extraction Pipeline — Technical Notes

This document provides a comprehensive overview of the keyword extraction pipeline implemented in [`keyword_extraction.py`](keyword_extraction.py:1). It details the system's architecture, from initial tokenization to advanced semantic reranking, and summarizes the experimental findings that have shaped its design.

## 1. Core Objective: Thematic Keyword Extraction

The primary goal is to produce a rank-ordered list of keywords that are thematically relevant to a given subreddit. The system is designed to favor salient, multi-word phrases over isolated, generic unigrams, ensuring that the output reflects the core topics and jargon of the community. This is achieved through a hybrid approach, combining deterministic TF-IDF scoring with optional, more advanced semantic alignment techniques.

**Key Guarantees:**

*   **Phrase-Centric:** The pipeline is biased toward multi-word phrases, ensuring that concepts like "credit card debt" are favored over "credit" and "debt" in isolation.
*   **Thematic Alignment:** Keywords are scored not only on frequency and uniqueness but also on their relevance to the subreddit's central theme, as defined by its name and description.
*   **Provenance:** Every keyword is tagged with its source(s) (e.g., `name`, `description`, `posts`, or combinations like `name+posts`), providing clear traceability.
*   **Scalability and Determinism:** The core pipeline is 100% deterministic and designed to be computationally efficient, allowing for repeatable, low-cost runs across thousands of subreddits.

## 2. System Architecture: A Multi-Stage Pipeline

The keyword extraction process is a multi-stage pipeline, with each stage progressively refining the keyword set.

  <!-- Placeholder for a real diagram -->

**Stage 1: Document Frequency (DF) Calculation**

The pipeline begins by calculating the document frequency for all n-grams (1 to 3 words) across two distinct corpora:

1.  **Description Corpus:** All subreddit descriptions from the input `page_*.json` files.
2.  **Posts Corpus:** All frontpage post titles from the files specified by `--frontpage-glob`.

This global DF is crucial for the TF-IDF calculation in the next stage, as it allows the system to down-weight terms that are common across many subreddits (e.g., "game," "video," "discussion").

*   **Code Anchors:** [`build_docfreq()`](keyword_extraction.py:788), [`build_posts_docfreq()`](keyword_extraction.py:600)

**Stage 2: Per-Subreddit Keyword Generation**

For each subreddit, keywords are generated from three primary sources:

1.  **Name:** The subreddit's name is robustly parsed to extract meaningful terms. This involves:
    *   Splitting on delimiters (`_`, `-`), camelCase, and digit boundaries.
    *   Applying heuristic and ML-based segmentation for concatenated lowercase names (e.g., "itisallspelllikethis" -> "it is all spell like this").
    *   Expanding common acronyms (e.g., "fps" -> "first person shooter").
    *   The full, cleaned name phrase (e.g., "Alcohol Liver Support") is given a significant score boost to ensure it ranks highly.
    *   **Code Anchors:** [`extract_name_terms()`](keyword_extraction.py:355), [`extract_name_full_phrase()`](keyword_extraction.py:432)

2.  **Description:** The description is processed using a standard TF-IDF model, with boosts applied to bigrams and trigrams to favor phrases. An "ensure phrases" mechanism guarantees that the top locally frequent phrases are retained, even if they are rare globally.
    *   **Code Anchors:** [`compute_tfidf_per_doc()`](keyword_extraction.py:789)

3.  **Posts:** Frontpage post titles are processed with a more sophisticated TF-IDF model that incorporates:
    *   **Engagement Weighting:** The term frequency (TF) is weighted by the post's score and comment count (`1 + log1p(score) + 0.5*log1p(comments)`).
    *   **Recency Weighting:** Scores decay based on the post's age, with a configurable half-life (`--posts-halflife-days`).
    *   **Code Anchors:** [`compute_posts_tfidf_for_frontpage()`](keyword_extraction.py:635)

**Stage 3: Scoring and Merging**

The scores from the three sources are merged, with configurable weights (`--name-weight`, `--desc-weight`, `--posts-weight`). At this stage, two important thematic alignment features are applied:

1.  **Anchored Variants:** Generic, high-frequency terms from posts are optionally replaced with an "anchored" version (e.g., "system" -> "valorant system"). This provides context and improves relevance.
    *   **Code Anchors:** [`apply_anchored_variants_for_generic_posts_terms()`](keyword_extraction.py:741)

2.  **Theme Penalty:** A penalty is applied to posts-only terms that have no token overlap with the subreddit's "theme" (defined as its name and top description keywords). This down-weights terms that are likely off-topic.
    *   **Code Anchors:** [`process_inputs()`](keyword_extraction.py:1263)

**Stage 4: Optional Embedding-Based Reranking**

To further enhance semantic relevance, an optional reranking step can be enabled (`--embed-rerank`). This uses a pre-trained `sentence-transformers` model to re-score the top candidate keywords based on their cosine similarity to the subreddit's theme vector.

*   **Mechanism:** `new_score = old_score * ((1 - alpha) + alpha * similarity)`
*   This boosts terms that are semantically related to the theme, even if they don't share any tokens.
*   **Code Anchors:** [`embed_rerank_terms()`](keyword_extraction.py:978)

**Stage 5: Normalization and Output**

Finally, the scores for each subreddit's keywords are normalized to sum to 1.0, and the top K (`--topk`) are written to a JSONL file.

*   **Code Anchors:** [`normalize_weights()`](keyword_extraction.py:903)

## 3. Experimental Findings and Tuning

Experiments were conducted to evaluate the impact of various tuning parameters and the embedding reranker.

**Key Findings:**

*   **Phrase Share:** The combination of algorithmic tuning and embedding reranking significantly increased the share of multi-word phrases in the output, from an average of 2.00 (out of 8) in the baseline to 4.08 in the final embedded model. This indicates a successful shift away from generic unigrams.
*   **Semantic Similarity:** The embedding reranker consistently produced a modest but measurable improvement in the average semantic similarity between the keywords and the subreddit's theme.
*   **Qualitative Improvements:**
    *   For `r/learnart`, the reranked output included more specific, thematic phrases like "improve art" and "advice greatly appreciated."
    *   For `r/Brawlstars`, the output shifted from generic terms like "event" to more specific phrases like "enchanted forest" and "season ends."
    *   For `r/NewToReddit`, the output became more focused on actionable advice, with phrases like "new advice" and "wish knew first."

**Recommended Configuration:**

The following command represents the best-performing configuration, balancing thematic relevance, phrase quality, and computational cost:

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
    --posts-phrase-boost-trigram 1.7 \
    --posts-stopwords-extra config/posts_stopwords_extra.txt \
    --posts-phrase-stoplist config/posts_phrase_stoplist.txt \
    --posts-replace-generic-with-anchored \
    --posts-theme-penalty 0.55 \
    --embed-rerank \
    --embed-model 'BAAI/bge-small-en-v1.5' \
    --embed-alpha 0.35
```

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