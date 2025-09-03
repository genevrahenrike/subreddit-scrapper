# Subreddit Scraper — ZenRows and Local Headless Browser

This repo scrapes Reddit “Best Communities” pages (e.g., `https://www.reddit.com/best/communities/{page}`) and parses subreddits from rendered HTML.

Two interchangeable ways to fetch pages:
- ZenRows API (existing approach)
- Local headless browser via Playwright (new approach) with basic stealth and optional proxy

Parsed results are written to the `output/` folder.

## Prerequisites
- Python 3.9+ recommended
- macOS shell examples use zsh

## Setup
```zsh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
# For local headless mode only
python -m playwright install chromium
```

## Option A: ZenRows
Use the existing ZenRows-based scraper. Note: current files hardcode an API key; replace with your own key or adjust code to read from an env var.

- Quick test (prints first 2000 chars and parses):
```zsh
source .venv/bin/activate
python test_zenrows.py
```

- Full scraper with progress saves (uses `reddit_scraper.py`):
```zsh
source .venv/bin/activate
python reddit_scraper.py
```
The script starts with a short test (pages 1–5) and then offers to continue to pages 1–1000. Progress snapshots are written to `output/`.

Tips:
- You can tweak ZenRows params like `premium_proxy` and `proxy_country` inside `reddit_scraper.py`.
- Consider moving the API key to an environment variable and loading it in code. Example:
```zsh
export ZENROWS_API_KEY="your_zenrows_key_here"
```

## Option B: Local Headless Browser (Playwright)
This option renders JS locally and applies lightweight stealth to reduce bot detection. It uses your residential/local IP by default and supports an outbound proxy.

- File: `local_reddit_scraper.py`
- Stealth tweaks: hides webdriver flag, sets realistic UA/locale/timezone, and shims a few browser APIs.

### Run a quick scrape
```zsh
source .venv/bin/activate
python local_reddit_scraper.py
```
This scrapes a couple of pages and writes JSON to `output/`.

### Use a proxy (optional)
- No proxy: do nothing (uses your local IP)
- HTTP proxy:
```zsh
export PROXY_SERVER="http://user:pass@host:port"
```
- SOCKS proxy:
```zsh
export PROXY_SERVER="socks5://user:pass@host:port"
```

### Programmatic usage example
```zsh
source .venv/bin/activate
python - <<'PY'
from local_reddit_scraper import LocalRedditCommunitiesScraper, LocalScraperConfig

cfg = LocalScraperConfig(headless=True)  # or set PROXY_SERVER env var
scraper = LocalRedditCommunitiesScraper(cfg)
scraper.scrape_all_pages(start_page=1, end_page=5, save_every=2)
print(f"Total: {len(scraper.all_subreddits)}")
PY
```

### Resume a stopped local scrape
If a run was interrupted, resume from the latest saved page:
```zsh
source .venv/bin/activate
python resume_local_scrape.py --end 1000 --save-every 25
```
The script selects the most advanced dataset among:
- Per-page directory: `output/pages/page_<N>.json`
- `output/reddit_communities_complete.json`
- All `output/reddit_communities_progress_page_<N>.json`
and resumes at the next page, skipping already-present per-page files. To override:
```zsh
python resume_local_scrape.py --from-page 60 --end 1000
```

Notes:
- The local scraper deduplicates by `community_id` (or name+url) before saving and writes `output/manifest.json` with `last_page` and `total`.
- If you suspect stale or inconsistent progress files, you may temporarily move them out of `output/` and resume from a known page with `--from-page`.

### Parser-only test using saved HTML
If you have a saved page like `output/reddit_page_500.html`, you can validate parsing without launching a browser:
```zsh
source .venv/bin/activate
python test_local_parser.py
```

### Migrate legacy outputs to per-page
Convert existing `complete.json`/`progress_page_*.json` into per-page files without re-scraping:
```zsh
source .venv/bin/activate
python migrate_outputs_to_pages.py
```

### Verify per-page outputs
```zsh
source .venv/bin/activate
python verify_output.py output/pages
```

## Output
- Per-page files: `output/pages/page_<N>.json` (each contains {page, count, subreddits[], scraped_at})
- Manifest: `output/manifest.json` (last_page, pages_done[], total, updated_at)
- Legacy (may exist): `output/reddit_communities_progress_page_<N>.json`, `output/reddit_communities_complete.json`
- Ad-hoc artifacts from tests: `output/reddit_page_500.html`, `output/reddit_subreddits_500.json`

## Subreddit front pages (new)
Scrape each subreddit's front page using Playwright and save one JSON per subreddit.

Files:
- `subreddit_frontpage_scraper.py` — scrapes a single subreddit with fallbacks
- `batch_scrape_subreddits.py` — reads `output/pages` and scrapes them in batches

Run (batch):
```zsh
source .venv/bin/activate
python batch_scrape_subreddits.py --start 0 --limit 200 --chunk-size 50
```
Notes:
- Respects `PROXY_SERVER` env var if set.
- Skips already scraped subreddits unless `--overwrite` is provided.
- Outputs to `output/subreddits/<name>/frontpage.json`; per-run manifest at `output/subreddits/manifest.json`.

## Subreddit posts + comments (next step)
After front pages are scraped you can deepen collection by visiting individual post permalinks and capturing:
- Full post metadata + body text
- A bounded slice of the comment tree (configurable depth & count)

File: `subreddit_posts_scraper.py`

### Why a separate script?
Separation keeps frontpage collection fast/light and lets you apply stricter filters (score, age, type) before paying the cost of loading full threads and comments.

### Data organization
```
output/
	subreddits/
		<sub>/
			frontpage.json             # from frontpage scraper
			posts/                     # new per-post directory
				t3_<id>.json             # one file per post w/ comments slice
			posts_manifest.json        # summary list of post files
```

Each post JSON baseline fields (prefixed frontpage_* when sourced from frontpage):
- permalink, subreddit, post_title, text_body, score, comment_count, created_timestamp
- comments[]: list of { id, parent_id, depth, author, score, award_count, content_type, created_ts, text }
- comment_count_scraped: number of comment nodes captured (may be < comment_count)
- scraped_at: ISO timestamp
- frontpage_*: original frontpage summary attributes for provenance (e.g. frontpage_score, frontpage_flair)
- media fields: media_images[], media_videos[], primary_image (if available), is_locked, is_stickied, is_archived

### Run (ranked order) example
Process top 50 ranked subreddits (based on earlier community ranking pages):
```zsh
source .venv/bin/activate
python subreddit_posts_scraper.py --ranked --ranked-limit 50 --min-score 5 --max-posts 8 --max-comments 120 --max-depth 5
```

### Run (explicit subreddits)
```zsh
source .venv/bin/activate
python subreddit_posts_scraper.py --subs r/python r/machinelearning --min-score 10 --allowed-types text image --max-posts 5
```

### Key filtering flags
- `--min-score N` : skip low-engagement posts (uses frontpage score)
- `--max-age-hours H` : skip older than H hours (uses created timestamp attribute if present)
- `--allowed-types ...` : restrict to specific post types (e.g. text, image, video, link)
- `--max-posts` : cap posts per subreddit per run
- `--max-comments` : cap comment nodes captured (breadth-first by DOM order)
- `--max-depth` : ignore deeper nested comments

### Comment loading strategy
The script:
1. Loads the post page and waits for `<shreddit-post>`.
2. Performs incremental scrolls to trigger lazy comment loads.
3. Clicks up to two "More replies" buttons per loop (best-effort).
4. Stops when reaching limits or stagnation.

### Overwriting
Use `--overwrite` to re-fetch existing post JSON files (otherwise skipped).

### Batch mode across many subs (concurrent)
```zsh
source .venv/bin/activate
python batch_scrape_subreddit_posts.py --order rank --ranked-limit 100 --concurrency 3 --min-score 5 --max-posts 6 --max-comments 100
```
Writes progress manifest: `output/subreddits/posts_batch_manifest.json`.

### Extensibility ideas
Future add-ons (not yet implemented):
- Media asset extraction (images/video URLs)
- Award counts / flair parsing inside comments
- Thread ranking heuristics (e.g., prioritize posts with high comments/score ratio)
- Optional recursive expansion of hidden comment branches beyond initial slice

### Caution
Full-thread scraping is heavier. Keep `max_posts` & `max_comments` conservative to reduce risk of triggering anti-bot measures. Consider longer delays if you scale concurrency.

## Notes & Tips
- Respect target site terms and rate limits. The local scraper includes short randomized delays; tune in `LocalScraperConfig`.
- If a page fails to render, increase timeouts in `LocalScraperConfig` and/or add retries.
- ZenRows costs can accumulate; the local mode avoids per-request API fees but may be slower and still subject to site defenses.

## Troubleshooting
- Playwright not installed: run `python -m playwright install chromium` in your venv.
- Modules not found (e.g., `bs4`): `pip install -r requirements.txt`.
- Bot detection hiccups: try enabling a proxy, increasing delays, or running non-headless for debugging.

## Keyword Extraction (refactored)

The keyword extraction pipeline has been refactored into a package under `src/keyword_extraction`. Use the module entrypoint instead of the old monolith script.

- Entrypoint: [__main__.py](src/keyword_extraction/__main__.py:1)
- Pipeline technical notes: [doc/Subreddit Keyword Extraction Pipeline.md](doc/Subreddit%20Keyword%20Extraction%20Pipeline.md:1)
- CLI definition: [__main__.main()](src/keyword_extraction/__main__.py:491)

Examples:
```zsh
# Single page file
python3 -m src.keyword_extraction --input-file output/pages/page_60.json --output-dir output/keywords

# Many page files
python3 -m src.keyword_extraction --input-glob "output/pages/page_*.json" --output-dir output/keywords

# Include posts/frontpages (optional but recommended for better keywords)
python3 -m src.keyword_extraction \
  --input-glob "output/pages/page_*.json" \
  --frontpage-glob "output/subreddits/*/frontpage.json" \
  --output-dir output/keywords_final \
  --topk 25
```

Output:
- For each input page_N.json, the extractor writes: `output/keywords/page_N.keywords.jsonl`
- Each line is a JSON record with per-subreddit keywords and weights.

Notes:
- Embedding-based rerank is optional; install `sentence-transformers` if you plan to enable `--embed-rerank`.
- The old `keyword_extraction.py` entrypoint was replaced by the package entrypoint shown above.
