"""
Configuration defaults for keyword extraction.
"""

DEFAULT_TOPK = 25
DEFAULT_MAX_NGRAM = 3
DEFAULT_OUTPUT_DIR = "output/keywords"
DEFAULT_NAME_WEIGHT = 3.0
DEFAULT_DESC_WEIGHT = 1.0
DEFAULT_MIN_TOKEN_LEN = 2  # allow short domain terms like ai, ml, uk, us, 3ds

# Description phrase boosts (favor multi-word phrases over generic unigrams)
DEFAULT_DESC_PHRASE_BOOST_BIGRAM = 1.2
DEFAULT_DESC_PHRASE_BOOST_TRIGRAM = 1.4

# Ensure local description phrases even if pruned by global df thresholds
DEFAULT_ENSURE_PHRASES = True
DEFAULT_ENSURE_PHRASES_K = 3

# Posts integration defaults
DEFAULT_POSTS_WEIGHT = 1.5
DEFAULT_POSTS_HALFLIFE_DAYS = 7.0
DEFAULT_POSTS_GENERIC_DF_RATIO = 0.05  # if appears in >=5% subs, consider "generic"
DEFAULT_POSTS_ANCHOR_MULTIPLIER = 0.9   # anchored variant score multiplier
DEFAULT_INCLUDE_CONTENT_PREVIEW = False  # keep off by default (often empty/noisy)

# Posts phrase preference (posts-specific; can be tuned via CLI)
DEFAULT_POSTS_PHRASE_BOOST_BIGRAM = 1.25
DEFAULT_POSTS_PHRASE_BOOST_TRIGRAM = 1.5
# Posts phrase commonness controls (optional)
DEFAULT_POSTS_DROP_GENERIC_PHRASES = False
DEFAULT_POSTS_GENERIC_PHRASE_DF_RATIO = 0.50

# Embedding rerank defaults
DEFAULT_EMBED_RERANK = False
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # fast, strong; consider "BAAI/bge-m3" for multilingual/SOTA
DEFAULT_EMBED_ALPHA = 0.35                      # blend factor for semantic similarity
DEFAULT_EMBED_K_TERMS = 100                     # rerank top-K terms by embeddings

# IDF damping and engagement blending defaults
DEFAULT_DESC_IDF_POWER = 0.85
DEFAULT_POSTS_IDF_POWER = 0.65
DEFAULT_POSTS_ENGAGEMENT_ALPHA = 0.0
DEFAULT_EMBED_CANDIDATE_POOL = "union"

# Dynamic commonness filtering and general-frequency controls
# - Curated stopwords can be disabled to rely primarily on corpus DF + general English frequency.
DEFAULT_USE_CURATED_STOPWORDS = True
# - Enable/disable use of general English word frequency (Zipf scale) to drop very common unigrams.
DEFAULT_USE_GENERAL_ZIPF = True
# - Words with Zipf frequency >= threshold are considered very common (e.g., 5.0 ~ common English words).
#   Set to 0 or negative to disable.
DEFAULT_GENERAL_ZIPF_THRESHOLD = 5.0
# - Description TF-IDF: optionally drop globally generic unigrams by DF ratio across subreddits.
DEFAULT_DESC_DROP_GENERIC_UNIGRAMS = True
DEFAULT_DESC_GENERIC_DF_RATIO = 0.10  # if appears in >=10% of descriptions, treat as generic
# - Optionally drop globally generic phrases (bi/tri-grams) in descriptions by DF ratio.
DEFAULT_DESC_DROP_GENERIC_PHRASES = False
DEFAULT_DESC_GENERIC_PHRASE_DF_RATIO = 0.50

# Composed theme-anchored keywords defaults
DEFAULT_COMPOSE_ANCHOR_POSTS = True
DEFAULT_COMPOSE_ANCHOR_MULTIPLIER = 1.0
DEFAULT_COMPOSE_ANCHOR_TOP_M = 20
DEFAULT_COMPOSE_ANCHOR_INCLUDE_UNIGRAMS = False
DEFAULT_COMPOSE_ANCHOR_MAX_FINAL_WORDS = 6
DEFAULT_COMPOSE_ANCHOR_USE_TITLE = True

# New: scoring behavior for composed phrases
DEFAULT_COMPOSE_ANCHOR_SCORE_MODE = "idf_blend"  # choices: "fraction", "idf_blend"
DEFAULT_COMPOSE_ANCHOR_ALPHA = 0.7               # strength of IDF contribution (0..1)
DEFAULT_COMPOSE_ANCHOR_FLOOR = 1.0               # non-suppressive floor for composed factor
DEFAULT_COMPOSE_ANCHOR_CAP = 2.0                 # optional cap to prevent runaway boosts
# New: guardrails to prevent composed flooding and unfair overshadow
DEFAULT_COMPOSE_ANCHOR_MAX_PER_SUB = 8           # hard cap of composed terms per subreddit (0=unlimited)
DEFAULT_COMPOSE_ANCHOR_MIN_BASE_SCORE = 3.0      # minimum TF-IDF score of seed to be eligible for composition
DEFAULT_COMPOSE_ANCHOR_MAX_RATIO = 2.0           # cap composed/base ratio before rerank (0=disabled)

# Seed selection controls for composition
DEFAULT_COMPOSE_SEED_EMBED = False
DEFAULT_COMPOSE_SEED_EMBED_ALPHA = 0.6
COMPOSE_SEED_MAX_POOL = 200

# Bonus multiplier applied specifically to composed variants originating from whitelist subjects
DEFAULT_COMPOSE_SUBJECTS_BONUS = 1.25