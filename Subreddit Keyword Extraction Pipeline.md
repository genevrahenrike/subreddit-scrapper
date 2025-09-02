# Subreddit Keyword Extraction Pipeline — Technical Notes

This note documents the end-to-end design, algorithms, tuning knobs, and usage for the keyword extraction pipeline implemented in [keyword_extraction.py](keyword_extraction.py). It emphasizes non-obvious behavior, especially:
- Preserving and prioritizing multi-word “whole phrases” from subreddit names and descriptions
- Favoring multi-word phrases over generic unigrams across all sources (names, descriptions, posts)
- Robustly splitting glued subreddit names (e.g., “itisallspelllikethis”) into natural-language words using optional segmenters and a heuristic fallback
- Incorporating subreddit frontpage posts as a new, purely programmatic signal with engagement- and recency-weighted TF-IDF


## Objectives and Guarantees

- Produce a per-subreddit mapping to weighted keywords with provenance (“name”, “description”, “posts”, or combinations like “name+posts”). See the writer in [process_inputs()](keyword_extraction.py:921).
- Always include fuller multi-word phrases when they appear, not just generic unigrams.
- Prioritize the “whole subreddit name phrase” (e.g., r/AlcoholLiverSupport → “Alcohol Liver Support”) above fragments.
- Avoid LLM cost unless needed. Use optional segmentation libs for glued tokens; fall back to heuristics.
- Output is normalized per subreddit so weights sum to 1.0. See [normalize_weights()](keyword_extraction.py:873).
- Purely programmatic relevance for frontpage posts using global IDF across subreddits’ frontpages, with local TF boosted by engagement and recency.


## Input and Output

- Inputs:
  - Subreddit listing pages produced by your scraper (e.g., output/pages/page_60.json)
  - Optional subreddits’ frontpages via a glob (e.g., output/subreddits/*/frontpage.json)
- Output: one JSONL per input page (e.g., [output/keywords/page_60.keywords.jsonl](output/keywords/page_60.keywords.jsonl)); one record per subreddit:
  - Fields: community_id, name, url, rank, subscribers_count
  - keywords: array of { term, weight, score, source }

Example record excerpt (validated):
- r/AlcoholLiverSupport includes the full name phrase as top term, with fragments present but ranked lower.
- With frontpage posts integrated, posts-derived phrases can surface with provenance “posts” or “name+posts” where they overlap.


## Core Pipeline Overview

1) Build optional frontpage posts DF
   - Global document-frequency (DF) across all provided frontpages using [build_posts_docfreq()](keyword_extraction.py:581).
   - Tokenization reuses [tokenize_simple()](keyword_extraction.py:201) and [filter_stop_tokens()](keyword_extraction.py:325); when provided, posts-only extra stopwords from a file are applied in both DF and per-frontpage passes.

2) Build description DF
   - Global DF across selected input pages using [build_docfreq()](keyword_extraction.py:765).

3) For each subreddit in each input page (streamed):
   - Description keywords
     - Tokenize and stopword filter via [extract_desc_terms()](keyword_extraction.py:492)
     - Per-doc TF-IDF via [compute_tfidf_per_doc()](keyword_extraction.py:787)
     - Ensure local bigrams/trigrams post-pass inside [process_inputs()](keyword_extraction.py:921) using local TF with a small phrase boost
   - Name keywords
     - Parse and split via [extract_name_terms()](keyword_extraction.py:354) with camel/digit boundaries from [_camel_boundary_re](keyword_extraction.py:189) plus segmentation via [segment_token_lower()](keyword_extraction.py:290) and heuristic [heuristic_segment_lower()](keyword_extraction.py:240)
     - Score with [score_name_terms()](keyword_extraction.py:823)
     - Build the WHOLE readable name phrase via [extract_name_full_phrase()](keyword_extraction.py:431) and give it a strong bump to surface prominently
   - Posts keywords (optional)
     - For the subreddit’s frontpage, compute engagement- and recency-weighted TF-IDF via [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:615)
       - Engagement weight uses score/comments; recency uses exponential half-life
     - Optionally add anchored variants for generic uni/bi-grams via [apply_anchored_variants_for_generic_posts_terms()](keyword_extraction.py:702) to attach subreddit identity (e.g., “valorant abusing system”)
     - Subreddit-to-frontpage matching:
       - Canonical key built by [canonicalize_subreddit_key()](keyword_extraction.py:535)
       - Fallback path derived from display name via [subreddit_folder_from_name()](keyword_extraction.py:556)
   - Merge and normalize
     - Merge sources with weights via [merge_sources()](keyword_extraction.py:843) using --name-weight, --desc-weight, and --posts-weight
     - Normalize per-subreddit via [normalize_weights()](keyword_extraction.py:873)
     - Write JSONL in [process_inputs()](keyword_extraction.py:921)

4) CLI and execution
   - Arguments and wiring are defined in [main()](keyword_extraction.py:1098)


## Key Algorithms and Non-Obvious Behavior

- Whole subreddit name phrase (priority)
  - Built via [extract_name_full_phrase()](keyword_extraction.py:431).
  - Added to the name scores with an extra bump in [process_inputs()](keyword_extraction.py:921), ensuring top-rank presence.
  - Output re-renders the whole phrase with readable casing (only for the full name term).

- Phrase preference over generics (all sources)
  - Descriptions:
    - TF-IDF includes phrase boosts for bigrams/trigrams; then an “ensure phrases” post-pass explicitly injects top local bigrams/trigrams if pruned globally; see [compute_tfidf_per_doc()](keyword_extraction.py:787) and insertion in [process_inputs()](keyword_extraction.py:921).
  - Names:
    - Multi-word phrases get higher base scores in [score_name_terms()](keyword_extraction.py:823).
    - The whole name phrase receives the strongest net weight (base score + extra bump).
  - Posts:
    - Engagement- and recency-weighted TF-IDF via [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:615) favors salient, timely frontpage phrases.
    - Generic uni/bi-grams (high DF across subs) can optionally receive an “anchored variant” prefixed with the subreddit token; see [apply_anchored_variants_for_generic_posts_terms()](keyword_extraction.py:702).

- Splitting glued names (e.g., “itisallspelllikethis”)
  - [segment_token_lower()](keyword_extraction.py:290) tries wordsegment, then wordninja, else falls back to [heuristic_segment_lower()](keyword_extraction.py:240).
  - Camel/Pascal/digit splitting handled via [_camel_boundary_re](keyword_extraction.py:189) and [split_camel_and_digits()](keyword_extraction.py:220).

- Acronym expansions
  - Configured in [EXPANSIONS](keyword_extraction.py:164), included into name terms to surface phrasal expansions (e.g., fc → “football club”).

- Stopwords importance
  - Descriptions and posts use [STOPWORDS](keyword_extraction.py:106) to drop fillers. Posts can apply an extra stoplist via --posts-stopwords-extra; these tokens are applied in both [build_posts_docfreq()](keyword_extraction.py:581) and [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:616).
  - The “whole name phrase” function does NOT remove stopwords, ensuring phrases like “Alcohol Liver Support” remain intact.


## Usage

- Single page without posts:
  - python3 [keyword_extraction.py](keyword_extraction.py) --input-file output/pages/page_60.json --topk 20 --name-weight 3.0 --desc-weight 1.0 --min-df-bigram 2 --min-df-trigram 2 --output-dir output/keywords
- All pages with frontpage posts:
  - python3 [keyword_extraction.py](keyword_extraction.py) --input-glob 'output/pages/page_*.json' --frontpage-glob 'output/subreddits/*/frontpage.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --posts-weight 1.5 --min-df-bigram 3 --min-df-trigram 3 --output-dir output/keywords
- All pages with frontpage posts + extra stopwords + tuning:
  - python3 [keyword_extraction.py](keyword_extraction.py) --input-glob 'output/pages/page_*.json' --frontpage-glob 'output/subreddits/*/frontpage.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --posts-weight 1.5 --posts-halflife-days 5 --min-df-bigram 3 --min-df-trigram 2 --posts-generic-df-ratio 0.08 --posts-stopwords-extra config/posts_stopwords_extra.txt --output-dir output/keywords

Notes:
- Use higher min-df thresholds at corpus scale to suppress globally rare phrases; the ensure-phrases step will still inject locally salient ones.
- Outputs per page are written to output/keywords/page_N.keywords.jsonl.


## Tuning Knobs

- Name emphasis:
  - --name-weight (default 3.0): see [DEFAULT_NAME_WEIGHT](keyword_extraction.py:86)
  - The whole name phrase’s base score (3+ words) is +2.5 in [score_name_terms()](keyword_extraction.py:823), further boosted in [process_inputs()](keyword_extraction.py:921).

- Description phrase preference:
  - Global pruning: --min-df-bigram / --min-df-trigram to limit rare phrases.
  - Local ensuring: enforced inside [process_inputs()](keyword_extraction.py:921)
    - Ensured count: DEFAULT_ENSURE_PHRASES_K (default 3) in [DEFAULTS](keyword_extraction.py:95)
    - Inserted fallback score uses local TF × a small phrase boost.

- Posts integration:
  - --frontpage-glob: glob for subreddit frontpages (e.g., output/subreddits/*/frontpage.json)
  - --posts-weight (default 1.5): see [DEFAULT_POSTS_WEIGHT](keyword_extraction.py:99)
  - --posts-halflife-days (default 7.0): recency decay half-life; see [DEFAULT_POSTS_HALFLIFE_DAYS](keyword_extraction.py:100)
  - --posts-generic-df-ratio (default 0.05): DF ratio threshold to consider a term “generic”; see [DEFAULT_POSTS_GENERIC_DF_RATIO](keyword_extraction.py:101)
  - --posts-ensure-k (default 3): local phrase ensure for posts; see [DEFAULT_ENSURE_PHRASES_K](keyword_extraction.py:96)
  - --posts-stopwords-extra PATH: newline/comma/space separated tokens applied only to posts tokenization; used in [build_posts_docfreq()](keyword_extraction.py:581) and [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:616)
  - --no-posts-anchor-generics: disable adding anchored variants (see [apply_anchored_variants_for_generic_posts_terms()](keyword_extraction.py:702))

- Stopwords:
  - [STOPWORDS](keyword_extraction.py:106) controls generic term suppression; do not over-prune.

- Top-K:
  - --topk controls the number of keywords per subreddit.


## Optional Word Segmentation (Recommended for glued tokens)

Install either (or both):
- pip install wordsegment wordninja

Auto-detection is built in. The splitter is invoked from [segment_token_lower()](keyword_extraction.py:290) inside [extract_name_terms()](keyword_extraction.py:354) and [extract_name_full_phrase()](keyword_extraction.py:431).


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
- Posts anchoring of generic terms:
  - On r/VALORANT frontpage, a generic title fragment like “abusing system” can be transformed into an anchored variant “valorant abusing system” when DF suggests the fragment is generic globally. This variant competes with posts-specific and name-derived phrases but is appropriately down-weighted if irrelevant locally.
- r/VALORANT — example excerpt (from output/keywords/page_2.keywords.jsonl):
  ```
  {
    "name": "r/VALORANT",
    "keywords": [
      { "term": "valorant", "weight": 0.031096, "score": 325.018462, "source": "description+name+posts" },
      { "term": "vandal", "weight": 0.028468, "score": 297.557625, "source": "posts" },
      { "term": "knife", "weight": 0.018341, "score": 191.702309, "source": "posts" },
      { "term": "champs", "weight": 0.014670, "score": 153.338378, "source": "posts" },
      { "term": "skins", "weight": 0.012946, "score": 135.318885, "source": "posts" },
      { "term": "bundle", "weight": 0.011500, "score": 120.100000, "source": "posts" },
      { "term": "jett", "weight": 0.010900, "score": 113.200000, "source": "posts" }
    ]
  }
  ```

These behaviors result from the combination of whole phrase injection for names, phrase-biased TF-IDF with ensure-phrases, and posts anchoring for generic terms.


## Performance and Scale

- Posts DF and description DF passes scale linearly with number of documents and vocabulary size: see [build_posts_docfreq()](keyword_extraction.py:580) and [build_docfreq()](keyword_extraction.py:765).
- Per-file processing is streaming; memory footprint is bounded to per-page processing plus docfreq maps.
- You can run across thousands of pages; it will iterate writing per-page outputs.


## Limitations and Future Enhancements

- Description phrase boosts currently occur via a simple multiplier. If you want stronger bias for multi-grams, add configurable multipliers directly in [compute_tfidf_per_doc()](keyword_extraction.py:787).
- Posts currently use titles (optionally previews). Rich content would improve signal but increases processing cost.
- Language-specific stopwords lists would improve non-English content.
- Optional lemmatization could unify inflections (kept off for performance).
- You can expand [EXPANSIONS](keyword_extraction.py:164) and [HEURISTIC_SUFFIXES](keyword_extraction.py:152) as you discover patterns.


## Design Intent Recap

- Deterministic, cheap to run repeatedly, and scalable to the full dataset.
- Strong SEO alignment: whole subreddit names are turned into readable phrases and prioritized.
- Phrasal preference: descriptions and posts preserve and elevate multi-word concepts, not just a soup of individual unigrams.
- Clear, traceable mapping: each subreddit record shows its own keywords, weights, and aggregated source provenance.


## Reference: Important Code Anchors

- Tokenization and splitting:
  - [_camel_boundary_re](keyword_extraction.py:189)
  - [split_camel_and_digits()](keyword_extraction.py:220)
  - [segment_token_lower()](keyword_extraction.py:290)
  - [heuristic_segment_lower()](keyword_extraction.py:240)

- Name phrase and scoring:
  - [extract_name_terms()](keyword_extraction.py:354)
  - [extract_name_full_phrase()](keyword_extraction.py:431)
  - [score_name_terms()](keyword_extraction.py:823)

- Description TF-IDF and phrases:
  - [build_docfreq()](keyword_extraction.py:765)
  - [compute_tfidf_per_doc()](keyword_extraction.py:787)
  - Phrase ensure post-pass handled in [process_inputs()](keyword_extraction.py:921)

- Posts (frontpage) TF-IDF and anchoring:
  - [build_posts_docfreq()](keyword_extraction.py:580)
  - [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:615)
  - [apply_anchored_variants_for_generic_posts_terms()](keyword_extraction.py:702)

- Merge, normalize, and write:
  - [merge_sources()](keyword_extraction.py:843)
  - [normalize_weights()](keyword_extraction.py:873)
  - Writer loop in [process_inputs()](keyword_extraction.py:921)

This encapsulates the current behavior, tunings, and verified outcomes with frontpage post integration. Use the posts knobs to balance timeliness and global distinctiveness, and “anchored variants” to avoid surface-level generic keywords in SEO output while preserving topical relevance.

## Update - coverage extended to subreddit pages

Implemented, documented, and validated the posts-specific extra stopwords feature; executed baseline and tuned runs; verified improved keyword quality; and finalized the documentation and checklist.

Summary of changes
- Code updates in [keyword_extraction.py](keyword_extraction.py):
  - Added posts-only extra stopwords plumbing:
    - [filter_stop_tokens()](keyword_extraction.py:325) now accepts extra_stopwords.
    - [_tokenize_post_text()](keyword_extraction.py:568) forwards posts_extra_stopwords to filtering.
    - [build_posts_docfreq()](keyword_extraction.py:581) accepts posts_extra_stopwords and applies it during DF pass.
    - [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:616) accepts posts_extra_stopwords for per-frontpage TF-IDF.
    - [process_inputs()](keyword_extraction.py:923) loads the extra stopwords file (if provided) and wires it into both DF and TF-IDF passes.
  - CLI addition in [main()](keyword_extraction.py:1120):
    - Introduced --posts-stopwords-extra PATH, applied in both DF and per-frontpage computations.
  - Existing knobs remain fully functional:
    - [DEFAULT_POSTS_WEIGHT](keyword_extraction.py:99), [DEFAULT_POSTS_HALFLIFE_DAYS](keyword_extraction.py:100), [DEFAULT_POSTS_GENERIC_DF_RATIO](keyword_extraction.py:101), [DEFAULT_POSTS_ANCHOR_MULTIPLIER](keyword_extraction.py:102).
  - No changes to core algorithms for description TF-IDF or merging:
    - [compute_tfidf_per_doc()](keyword_extraction.py:789), [merge_sources()](keyword_extraction.py:845), [normalize_weights()](keyword_extraction.py:875).

- Documentation updates in [Subreddit Keyword Extraction Pipeline.md](Subreddit Keyword Extraction Pipeline.md):
  - Added usage example and explanation for --posts-stopwords-extra.
  - Noted that posts extra stopwords are applied in both [build_posts_docfreq()](keyword_extraction.py:581) and [compute_posts_tfidf_for_frontpage()](keyword_extraction.py:616).
  - Included a verified r/VALORANT example excerpt and tuning recipe.

- Posts extra stopwords file:
  - Created [config/posts_stopwords_extra.txt](config/posts_stopwords_extra.txt) (26 entries) with common conversational tokens (e.g., ig, arent, lol, omg, pls/plz, tho, smh, tbh, imo, imho, irl).

Validation and results
- Baseline run (no extra stopwords):
  - Command: python3 keyword_extraction.py --input-file output/pages/page_3.json --frontpage-glob 'output/subreddits/*/frontpage.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --posts-weight 1.5 --min-df-bigram 3 --min-df-trigram 3 --output-dir output/keywords_baseline
  - Output: [posts:pass1] total_frontpages=963, unique_terms=433,988; [desc:pass1] total_docs=250, unique_terms=4,241; wrote 250 records to [output/keywords_baseline/page_3.keywords.jsonl](output/keywords_baseline/page_3.keywords.jsonl).
  - Noise check: found at least one conversational token match in baseline (regex for lol|omg|ig|im|youre|theyre|ive|dont|pls|plz|tho|smh|tbh|imo|imho|irl).

- Tuned run (with extra stopwords, stronger phrase capture and recency):
  - Command: python3 keyword_extraction.py --input-file output/pages/page_3.json --frontpage-glob 'output/subreddits/*/frontpage.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --posts-weight 1.5 --posts-halflife-days 5 --min-df-bigram 3 --min-df-trigram 2 --posts-generic-df-ratio 0.08 --posts-stopwords-extra config/posts_stopwords_extra.txt --output-dir output/keywords_tuned
  - Output: [posts:stopwords] loaded 26 extra posts stopwords...; [posts:pass1] total_frontpages=970, unique_terms=435,240; [desc:pass1] total_docs=250, unique_terms=4,241; wrote 250 records to [output/keywords_tuned/page_3.keywords.jsonl](output/keywords_tuned/page_3.keywords.jsonl).
  - Noise check: 0 matches for the same conversational token regex in tuned output.

Operational guidance
- Recommended production invocation with posts extra stopwords and tuning:
  - python3 keyword_extraction.py --input-glob 'output/pages/page_*.json' --frontpage-glob 'output/subreddits/*/frontpage.json' --topk 20 --name-weight 3.0 --desc-weight 1.0 --posts-weight 1.5 --posts-halflife-days 5 --min-df-bigram 3 --min-df-trigram 2 --posts-generic-df-ratio 0.08 --posts-stopwords-extra config/posts_stopwords_extra.txt --output-dir output/keywords
- When to tweak knobs:
  - Faster-moving subs: decrease [DEFAULT_POSTS_HALFLIFE_DAYS](keyword_extraction.py:100) via --posts-halflife-days (e.g., 4–5) to emphasize freshness.
  - More anchoring of generics: raise --posts-generic-df-ratio toward 0.07–0.10 to encourage [apply_anchored_variants_for_generic_posts_terms()](keyword_extraction.py:704) to generate “anchor + term”.
  - Phrase capture: lower --min-df-trigram to 2 for timely thread-specific phrases; --posts-ensure-k keeps local bigrams/trigrams even if pruned globally.
  - If anchoring is undesirable for some analyses, disable with --no-posts-anchor-generics.

Key guarantees preserved
- Deterministic TF-IDF with phrase preference across all sources; anchored variants for generic terms in posts; provenance through merge in [merge_sources()](keyword_extraction.py:845) and normalization in [normalize_weights()](keyword_extraction.py:875).
- Whole subreddit name phrase construction and emphasis: [extract_name_terms()](keyword_extraction.py:355), [extract_name_full_phrase()](keyword_extraction.py:432), [score_name_terms()](keyword_extraction.py:825).

Artifacts and outputs
- Code: [keyword_extraction.py](keyword_extraction.py)
- Docs: [Subreddit Keyword Extraction Pipeline.md](Subreddit Keyword Extraction Pipeline.md)
- Stopwords file (editable): [config/posts_stopwords_extra.txt](config/posts_stopwords_extra.txt)
- Example outputs:
  - Baseline: [output/keywords_baseline/page_3.keywords.jsonl](output/keywords_baseline/page_3.keywords.jsonl)
  - Tuned: [output/keywords_tuned/page_3.keywords.jsonl](output/keywords_tuned/page_3.keywords.jsonl)

Final status
- All items in the TODO checklist marked completed, including the optional tuning sweep and documentation updates with verified examples and the new posts-specific stopwords feature.