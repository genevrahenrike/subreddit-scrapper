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

## Notes & Tips
- Respect target site terms and rate limits. The local scraper includes short randomized delays; tune in `LocalScraperConfig`.
- If a page fails to render, increase timeouts in `LocalScraperConfig` and/or add retries.
- ZenRows costs can accumulate; the local mode avoids per-request API fees but may be slower and still subject to site defenses.

## Troubleshooting
- Playwright not installed: run `python -m playwright install chromium` in your venv.
- Modules not found (e.g., `bs4`): `pip install -r requirements.txt`.
- Bot detection hiccups: try enabling a proxy, increasing delays, or running non-headless for debugging.
