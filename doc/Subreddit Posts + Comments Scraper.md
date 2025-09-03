## Subreddit Posts + Comments Scraper — Usage & Internals

This guide explains how to use `subreddit_posts_scraper.py` and `batch_scrape_subreddit_posts.py`, what they save, and the non-obvious behavior (filtering, comment loading, concurrency, resume, and tuning).

### What it does
- Loads post permalinks from each subreddit frontpage JSON (pre-scraped).
- Applies configurable filters: minimum score, maximum age, allowed post types, post/comment/depth limits.
- Visits each post page, extracts full post metadata, body text, and a bounded slice of the comment tree.
- Captures media URLs (images/videos), post status flags (locked, stickied, archived), and extended comment attributes (award_count, content_type).
- Supports batch mode: concurrent scraping across many subreddits, with resume/skip and rank/alpha ordering.
- Saves per-post JSON to `output/subreddits/<sub>/posts/*.json` and per-subreddit manifest; global batch manifest tracks aggregate progress.

---

## Prerequisites
- Python 3.9+
- Dependencies: `pip install -r requirements.txt`
- One-time browser install: `playwright install chromium`

Optional:
- Proxy: set `PROXY_SERVER` (e.g. `http://user:pass@host:port` or `socks5://host:port`).

---

## Quick start

### Scrape posts + comments for a single subreddit
Requires frontpage JSON for the subreddit (see frontpage scraper).

```bash
python subreddit_posts_scraper.py --subs r/funny --max-posts 5 --max-comments 30 --min-score 10
```

CLI options:
```bash
python subreddit_posts_scraper.py \
  --subs r/aww r/funny \
  --max-posts 10 \
  --max-comments 100 \
  --max-depth 5 \
  --min-score 5 \
  --allowed-types text image \
  --no-headless \
  --proxy "http://user:pass@host:port" \
  --overwrite
```

### Batch mode (concurrent, ranked or alpha order)
Use the batch script to process many subreddits in parallel, with resume and skip.

```bash
python batch_scrape_subreddit_posts.py --order rank --ranked-limit 100 --concurrency 3 --min-score 5 --max-posts 6 --max-comments 100
```

Flags:
- `--order rank|alpha` — ranked or alphabetical subreddit ordering.
- `--ranked-limit N` — limit to top N ranked subs.
- `--start <N>` and `--limit <K>` — process indices `[N, N+K)` from the ordered list.
- `--concurrency <W>` — number of parallel Playwright processes (safe 1–3, default 2).
- `--overwrite` — re-fetch and overwrite existing post JSON files.
- All post/comment filter flags as above.

Progress is tracked in `output/subreddits/posts_batch_manifest.json`.

---

## Programmatic usage
```python
from subreddit_posts_scraper import PostScrapeConfig, SubredditPostsScraper

cfg = PostScrapeConfig(
    headless=True,            # set False to watch the browser
    min_score=10,             # skip low-engagement posts
    max_posts_per_subreddit=5,
    max_comments_per_post=30,
    allowed_post_types=["text", "image"],
)
scraper = SubredditPostsScraper(cfg)
scraper._start()
try:
    saved = scraper.scrape_subreddit_posts("r/funny", overwrite=True)
finally:
    scraper._stop()
```

---

## Output structure
File: `output/subreddits/<sub>/posts/<post_id>.json`

Top-level keys:
- `id` — Reddit post ID (e.g., `t3_...`).
- `permalink` — canonical post URL.
- `post_title` — full post title.
- `created_timestamp` — ISO timestamp.
- `score` — post score at scrape time.
- `comment_count` — number of comments (scraped slice).
- `post_type` — text, image, video, link, etc.
- `author`, `author_id`, `subreddit`, `subreddit_id`, `domain`.
- `content_href` — canonical content URL.
- `text_body` — full post body text (if present).
- `media_images` — list of image URLs (thumbnails, full-size, etc.).
- `media_videos` — list of video URLs (if present).
- `primary_image` — best-effort main image.
- `is_locked`, `is_stickied`, `is_archived` — post status flags.
- `comments` — list of parsed comments (see below).
- `comment_count_scraped` — number of comments actually scraped.
- `scraped_at` — ISO timestamp.
- `frontpage_*` — merged summary fields from frontpage JSON for context.

Each `comment` includes:
- `id`, `parent_id`, `depth`, `author`, `score`, `award_count`, `content_type`, `created_ts`, `text`.

Manifest files:
- `output/subreddits/<sub>/posts_manifest.json` — lists all post JSON files for the subreddit.
- `output/subreddits/posts_batch_manifest.json` — tracks global batch progress.

---

## Configuration (PostScrapeConfig)
Key options you may want to tune:
- `headless` (bool): Run without UI. Set to `False` to watch the browser and aid debugging.
- `proxy_server` (str | None): Use a proxy (also read from `PROXY_SERVER`).
- `timeout_ms` (int): Playwright page/context default timeouts.
- `user_agent` (str): Overrides the UA string.
- `min_score` (int): Skip posts below this score.
- `max_age_hours` (float | None): Skip posts older than this age.
- `allowed_post_types` (list | None): Restrict to specific post types (e.g. text, image, video, link).
- `max_posts_per_subreddit` (int): Cap posts per subreddit per run.
- `max_comments_per_post` (int): Cap comment nodes captured (breadth-first by DOM order).
- `max_comment_depth` (int): Ignore deeper nested comments.
- `comment_scroll_wait_ms` (int): Wait after each comment scroll.
- `comment_max_scroll_loops` (int): Hard cap on comment scroll iterations.
- `max_post_attempts` (int): Retry attempts per post.
- `min_delay`, `max_delay` (float): Polite delay between posts.

Comment loading strategy:
1. Loads the post page and waits for `<shreddit-post>`.
2. Performs incremental scrolls to trigger lazy comment loads.
3. Clicks up to two "More replies" buttons per loop (best-effort).
4. Stops when reaching limits or stagnation.

---

## Consent/NSFW gates and stealth
- Cookie / consent banners: Attempts to click common Accept buttons.
- Mature content interstitial: Attempts to continue without login.
- Stealth: Sets `navigator.webdriver` to undefined, reasonable `navigator.languages`, `platform`, and a modern UA.

Limitations: Some posts or sessions may hard‑require login; in such cases, scraping may be incomplete.

---

## Resume, skip, and overwrite
- By default, skips posts with existing JSON files unless `--overwrite` is set.
- Overwrite mode deletes and regenerates post JSONs, ensuring latest fields and fixes.
- Batch manifest tracks aggregate progress; per-subreddit manifest lists all post files.

---

## Troubleshooting & tips
- Too few comments:
  - Increase `max_comments`, `max_comment_depth`, or `comment_max_scroll_loops`.
  - Try `headless=False` to watch the scroll and expansion behavior.
- Suspected gating:
  - Manually verify if the post requires login (try in a fresh incognito browser).
  - Use a residential proxy and a more common UA.
- Rate limiting / flaky loads:
  - Add small sleeps between posts and subreddits.
  - Lower `max_posts` and concurrency when speed matters.
  - Rotate proxies if scraping many subreddits in a batch.
  - Keep batch `concurrency` at 2–3 and use `initial_jitter_s` to avoid synchronized bursts.

---

## Extending parsing
- The `shreddit-post` and `shreddit-comment` elements expose many attributes; you can add more fields by broadening the attribute capture loop.
- For media posts, additional selectors inside the post card may expose galleries, GIFs, or higher-quality assets.
- For awards, flair, and other metadata, inspect the DOM and add extraction logic as needed.

---

## Error handling
- On success: writes per-post JSON and updates manifest files.
- On error or repeated timeouts: skips the post and logs the error; batch manifest records progress.

---

## Try it
Scrape posts + comments for one subreddit and save JSON:
```bash
python subreddit_posts_scraper.py --subs r/funny --max-posts 5 --max-comments 30 --min-score 10
```

Scrape in batch mode with concurrency and overwrite:
```bash
python batch_scrape_subreddit_posts.py --order rank --ranked-limit 20 --concurrency 2 --max-posts 2 --max-comments 20 --overwrite
```

---

## Known limitations
- Login‑gated or quarantined posts may not expose content to anonymous sessions.
- The new Reddit UI changes frequently; selectors/attributes may require maintenance.
- Heavy scraping may trigger rate limiting; use conservative pacing and proxies.

---

## Where to look in the code
- Class: `SubredditPostsScraper`
  - `_start`, `_new_context`, `_apply_stealth`, `_stop`
  - `load_frontpage_cached`, `iter_candidates`, `filter_candidates`
  - `scrape_post` (loads permalink, scrolls for comments)
  - `_auto_scroll_comments` (handles lazy loading & “More replies” clicks)
  - `_parse_post_component` (broad attribute capture, media, status flags)
  - `_parse_comments` (award_count, content_type, text body)
  - `scrape_subreddit_posts` (orchestrates per-sub filtering & saving)
  - `_infer_post_id_from_permalink`, `_update_sub_manifest`
- Batch: `batch_scrape_subreddit_posts.py`
  - `main`, `_worker_process`, `save_batch_manifest`, `compute_order`

For a quick sanity test, run with `--no-headless` to watch the browser and confirm that comments keep loading as you scroll.
