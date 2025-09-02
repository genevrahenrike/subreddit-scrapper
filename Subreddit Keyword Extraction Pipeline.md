# Subreddit Keyword Extraction Pipeline — Technical Notes

This note documents the end-to-end design, algorithms, tuning knobs, and usage for the keyword extraction pipeline implemented in [keyword_extraction.py](keyword_extraction.py). It emphasizes non-obvious behavior, especially:
- Preserving and prioritizing multi-word “whole phrases” from subreddit names and descriptions
- Ensuring phrases like “modern furniture” appear alongside generic unigrams (“modern”), with phrase preference
- Robustly splitting glued subreddit names (e.g., “itisallspelllikethis”) into natural-language words using optional segmenters and a heuristic fallback


## Objectives and Guarantees

- Produce a per-subreddit mapping to weighted keywords with provenance (“name”, “description”, “both”). See the writer in [process_inputs()](keyword_extraction.py:682).
- Always include fuller multi-word phrases when they appear, not just generic unigrams.
- Prioritize the “whole subreddit name phrase” (e.g., r/AlcoholLiverSupport → “Alcohol Liver Support”) above fragments.
- Avoid LLM-cost unless needed. Use optional segmentation libs for glued tokens; fall back to heuristics.
- Output is normalized per subreddit so weights sum to 1.0. See [normalize_weights()](keyword_extraction.py:654).


## Input and Output

- Inputs: page JSON files produced by your scraper (e.g., output/pages/page_60.json).
- Output: one JSONL per input page (e.g., [output/keywords/page_60.keywords.jsonl](output/keywords/page_60.keywords.jsonl)); one record per subreddit:
  - Fields: community_id, name, url, rank, subscribers_count
  - keywords: array of { term, weight, score, source }

Example record excerpt (validated):
- r/AlcoholLiverSupport includes the full name phrase as top term, with fragments present but ranked lower.


## Core Pipeline Overview

1) Load subreddits per page: [iter_subreddits_from_file()](keyword_extraction.py:544)

2) Name keywords
   - Tokenization:
     - Remove r/ prefix, trailing “/”, normalize delimiters: [extract_name_terms()](keyword_extraction.py:380)
     - Split camel/Pascal/digit transitions via [_camel_boundary_re](keyword_extraction.py:214)
     - Segment long lowercase “glued” tokens via [segment_token_lower()](keyword_extraction.py:316) using:
       - wordsegment (if installed), then wordninja (if installed), else a heuristic [heuristic_segment_lower()](keyword_extraction.py:266)
   - Build final list:
     - Keep filtered unigrams (stopwords removed), add bigrams from those unigrams; add acronym expansions from [EXPANSIONS](keyword_extraction.py:189)
   - Extract WHOLE readable phrase (preserving casing) separately in [extract_name_full_phrase()](keyword_extraction.py:457). This function intentionally does not remove stopwords to retain “Alcohol Liver Support”.

3) Description keywords
   - Tokenization and stopwords: [tokenize_simple()](keyword_extraction.py:227), [filter_stop_tokens()](keyword_extraction.py:351), [STOPWORDS](keyword_extraction.py:132)
   - Global DF across selected inputs: [build_docfreq()](keyword_extraction.py:560)
   - Per-document TF-IDF:
     - [compute_tfidf_per_doc()](keyword_extraction.py:582)
     - Phrase preference is further enforced by the post-pass:
       - “Ensure phrases” step re-injects up to N locally frequent bigrams/trigrams even if globally rare: see [process_inputs()](keyword_extraction.py:712).
       - Inserted phrases receive a small boost: desc_tfidf[g] = TF × phrase_boost (no IDF), ensuring fuller phrases visibly surface.

4) Scoring and merge
   - Name side: base weights in [score_name_terms()](keyword_extraction.py:613)
     - 3+ words: +2.5
     - bigram: +1.5
     - unigram: +1.0
     - All multiplied by --name-weight (default 3.0): [DEFAULT_NAME_WEIGHT](keyword_extraction.py:111)
     - The WHOLE name phrase is additionally injected and reinforced in [process_inputs()](keyword_extraction.py:721) so it ranks above fragments.
   - Description side: TF-IDF × --desc-weight, pruned by DF thresholds, then phrase ensure.
   - Merge (preserving provenance) in [merge_scores()](keyword_extraction.py:633).

5) Normalize and write
   - Normalize per-subreddit in [normalize_weights()](keyword_extraction.py:654) so weights sum to 1.0.
   - Persist in JSONL in [process_inputs()](keyword_extraction.py:682).


## Key Algorithms and Non-Obvious Behavior

- Whole subreddit name phrase (priority)
  - Built via [extract_name_full_phrase()](keyword_extraction.py:457).
  - Added to the name scores with an extra bump in [process_inputs()](keyword_extraction.py:721), ensuring top-rank presence.
  - Output re-renders the whole phrase with readable casing: see rendering logic in [process_inputs()](keyword_extraction.py:744).

- Phrase preference over generics
  - Descriptions:
    - TD-IDF naturally favors phrasal n-grams when they carry signal.
    - Post TF-IDF, the “ensure phrases” step explicitly inserts top local bigrams/trigrams if they were pruned globally, improving recall of phrases like “modern furniture”. See [process_inputs()](keyword_extraction.py:712).
  - Names:
    - Multi-word phrases get higher base scores in [score_name_terms()](keyword_extraction.py:613).
    - The whole name phrase receives the strongest net weight (base score × name-weight + extra bump).

- Splitting glued names (e.g., “itisallspelllikethis”)
  - [segment_token_lower()](keyword_extraction.py:316) tries:
    - wordsegment (unigram LM) if installed
    - wordninja (freq-based) if installed
    - fallback [heuristic_segment_lower()](keyword_extraction.py:266)
  - For acronyms and ProperCase, splitting happens via [_camel_boundary_re](keyword_extraction.py:214). Casing is preserved for acronyms and upper tokens in [extract_name_full_phrase()](keyword_extraction.py:457).

- Acronym expansions
  - Configured in [EXPANSIONS](keyword_extraction.py:189), included into name terms to surface phrasal expansions (e.g., fc → “football club”).

- Stopwords importance
  - Descriptions use [STOPWORDS](keyword_extraction.py:132) to drop fillers (e.g., “support” as a generic term).
  - The “whole name phrase” function does NOT remove stopwords, ensuring phrases like “Alcohol Liver Support” remain intact.


## Usage

- Single page:
  - python3 [keyword_extraction.py](keyword_extraction.py) --input-file output/pages/page_60.json --topk 20 --name-weight 3.0 --desc-weight 1.0 --min-df-bigram 2 --min-df-trigram 2 --output-dir output/keywords
- All pages:
  - python3 [keyword_extraction.py](keyword_extraction.py) --input-glob 'output/pages/page_*.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --min-df-bigram 3 --min-df-trigram 3 --output-dir output/keywords

Notes:
- Use higher min-df thresholds at corpus scale to suppress globally rare phrases; the ensure-phrases step will still inject locally salient ones.
- Outputs per page are written to output/keywords/page_N.keywords.jsonl.


## Tuning Knobs

- Name emphasis:
  - --name-weight (default 3.0): [DEFAULT_NAME_WEIGHT](keyword_extraction.py:111)
  - The whole name phrase’s base score (3+ words) is +2.5 in [score_name_terms()](keyword_extraction.py:613), further boosted in [process_inputs()](keyword_extraction.py:721).
- Phrase preference in descriptions:
  - Global pruning: --min-df-bigram / --min-df-trigram to limit rare phrases.
  - Local ensuring: enforced in [process_inputs()](keyword_extraction.py:712)
    - Ensured count: DEFAULT_ENSURE_PHRASES_K (default 3)
    - Inserted fallback score uses TF × a small phrase boost.
- Stopwords:
  - [STOPWORDS](keyword_extraction.py:132) controls generic term suppression in descriptions; do not over-prune.
- Top-K:
  - --topk controls the number of keywords per subreddit.


## Optional Word Segmentation (Recommended for glued tokens)

Install either (or both):
- pip install wordsegment wordninja

Auto-detection is built in. The splitter is invoked from [segment_token_lower()](keyword_extraction.py:316) inside [extract_name_terms()](keyword_extraction.py:380) and [extract_name_full_phrase()](keyword_extraction.py:457).


## LLM Last-Line-of-Defense (Design Option)

If some tokens remain stubbornly glued:
- Add a post-pass filtering for long single tokens that resisted segmentation (e.g., lowercase, length ≥ 12).
- Send only those to an LLM for segmentation, cache the results, then merge back.
- This is deliberately not enabled to keep costs low; wordsegment/wordninja + heuristics generally suffice.


## Verified Examples

- Whole name phrase:
  - r/AlcoholLiverSupport → “Alcohol Liver Support” top name term plus “alcohol liver”, “liver support”, etc. Fragments rank below the whole phrase.
- Phrase vs unigram (description):
  - r/southernfood includes “sweet tea” and “sweet”, with “sweet tea” preferred.
- Camel/Pascal handling:
  - r/TwoandaHalfMen → “Twoanda Half Men” is top, “twoanda half”, “half men” and unigrams also present.

These behaviors are a direct result of the combination of whole phrase injection, base score structure, and the phrase-ensure step.


## Performance and Scale

- The docfreq pass scales linearly with number of documents and vocabulary size: [build_docfreq()](keyword_extraction.py:560).
- Per-file processing is streaming; memory footprint is bounded to per-page processing plus docfreq map.
- You can run across thousands of pages; it will iterate writing per-page outputs.


## Limitations and Future Enhancements

- Description phrase boosts currently occur in the phrase-ensure fallback insertion (TF × phrase boost). TF-IDF itself remains vanilla; if you want stronger bias for multi-grams in TF-IDF proper, we can fold in direct multipliers in [compute_tfidf_per_doc()](keyword_extraction.py:582).
- Language-specific stopwords lists would improve non-English descriptions.
- Optional lemmatization could unify inflections (kept off for performance and dependency minimization).
- You can expand [EXPANSIONS](keyword_extraction.py:189) and [HEURISTIC_SUFFIXES](keyword_extraction.py:177) as you discover patterns.


## Design Intent Recap

- Deterministic, cheap to run repeatedly, and scalable to the full dataset.
- Strong SEO alignment: whole subreddit names are turned into readable phrases and prioritized.
- Phrasal preference: descriptions preserve and elevate multi-word concepts, not just a soup of individual unigrams.
- Clear, traceable mapping: each subreddit record shows its own keywords, weights, and sources.


## Reference: Important Code Anchors

- Tokenization and splitting:
  - [_camel_boundary_re](keyword_extraction.py:214)
  - [split_camel_and_digits()](keyword_extraction.py:246)
  - [segment_token_lower()](keyword_extraction.py:316)
  - [heuristic_segment_lower()](keyword_extraction.py:266)
- Name phrase and scoring:
  - [extract_name_terms()](keyword_extraction.py:380)
  - [extract_name_full_phrase()](keyword_extraction.py:457)
  - [score_name_terms()](keyword_extraction.py:613)
- Description TF-IDF and phrases:
  - [build_docfreq()](keyword_extraction.py:560)
  - [compute_tfidf_per_doc()](keyword_extraction.py:582)
  - Phrase ensure post-pass in [process_inputs()](keyword_extraction.py:712)
- Merge, normalize, and write:
  - [merge_scores()](keyword_extraction.py:633)
  - [normalize_weights()](keyword_extraction.py:654)
  - Writer loop in [process_inputs()](keyword_extraction.py:682)


This encapsulates the current behavior, tunings, and verified outcomes. If you want stronger global bias for description phrases directly in TF-IDF, we can add configurable multipliers inside [compute_tfidf_per_doc()](keyword_extraction.py:582). Otherwise the current phrase-ensure step already makes phrases surface reliably above their generic counterparts while keeping costs low and the pipeline deterministic.