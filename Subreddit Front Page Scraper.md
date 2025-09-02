## Subreddit Front Page Scraper — Usage & Internals

This guide explains how to use `subreddit_frontpage_scraper.py`, what it saves, and the non-obvious behavior (scrolling, gate handling, fallbacks, and tuning).

### What it does
- Loads `https://www.reddit.com/r/<subreddit>/` with Playwright (Chromium).
- Handles cookie/consent and mature content interstitials best‑effort without login.
- Auto-scrolls to trigger lazy loading until a target number of posts are rendered.
- Parses rich post metadata from the new Reddit UI (the `shreddit-post` web component).
- Falls back to `https://old.reddit.com/r/<subreddit>/` if the new UI yields no/too few posts.
- Saves JSON to `output/subreddits/<name>/frontpage.json`; optionally saves HTML snapshots for debugging.

---

## Prerequisites
- Python 3.9+
- Dependencies: `pip install -r requirements.txt`
- One-time browser install: `playwright install chromium`

Optional:
- Proxy: set `PROXY_SERVER` (e.g. `http://user:pass@host:port` or `socks5://host:port`).

---

## Quick start

### Run the built-in demo
This scrapes a couple of popular subreddits and writes JSON to `output/subreddits/*/frontpage.json`.

```bash
python subreddit_frontpage_scraper.py
```

### Programmatic usage
```python
from subreddit_frontpage_scraper import FPConfig, SubredditFrontPageScraper

cfg = FPConfig(
    headless=True,            # set False to watch the browser
    min_posts=50,             # target number of posts to load
)
scraper = SubredditFrontPageScraper(cfg)
scraper._start()
try:
    data = scraper.scrape_frontpage("r/aww")
    scraper.save_frontpage(data["subreddit"], data)
finally:
    scraper._stop()
```

---

## Output structure
File: `output/subreddits/<name>/frontpage.json`

Top-level keys:
- `subreddit` — the normalized subreddit name.
- `url` — the attempted new-Reddit URL.
- `meta` — best-effort page metadata (e.g., `title`).
- `posts` — list of parsed posts (see below).
- `scraped_at` — ISO timestamp.
- `error` — present only on failure.

Each `post` (new Reddit UI) typically includes:
- `title`, `permalink`, `score`, `comments`
- `post_id` (e.g., `t3_...`), `post_type` (text/link/media), `domain`
- `author`, `author_id`
- `subreddit`, `subreddit_id`
- `created_ts` (ISO string from `created-timestamp`)
- `content_href` (canonical content URL)
- `content_preview` (clamped text preview for text posts when present)
- `flair` (list of flair text values)
- `thumbnail_url` (best-effort image in card)

Fallback (old.reddit) returns a simpler subset: `title`, `permalink`, `score`, `comments`. The scraper merges any old-Reddit-specific `meta` back into `meta`.

Debug HTML snapshot: When too few posts are found, a page snapshot is saved to `output/pages/<sub>_frontpage_debug_<timestamp>.html` for inspection.

---

## Configuration (FPConfig)
Key options you may want to tune:
- `headless` (bool): Run without UI. Set to `False` to watch scrolling and aid debugging.
- `proxy_server` (str | None): Use a proxy (also read from `PROXY_SERVER`).
- `timeout_ms` (int): Playwright page/context default timeouts.
- `user_agent` (str): Overrides the UA string.
- `max_attempts` (int): Browser retry attempts within one scrape.

Lazy-load / scrolling knobs:
- `min_posts` (int, default 50): Target number of posts to load before stopping.
- `max_scroll_loops` (int): Hard cap on scroll iterations.
- `scroll_step_px` (int): How far to wheel-scroll per iteration.
- `scroll_wait_ms` (int): Wait after each scroll to allow network/render.
- `stagnant_loops` (int): Stop if post count hasn’t increased for this many iterations.
- `max_page_seconds` (float, default 75.0): Overall time budget for a single page.
- `save_debug_html` (bool): Write a debug HTML snapshot if too few posts.

How the auto-scroll works:
- On load, the scraper presses `End`, then in a loop:
  1) Scrolls last post into view, 2) wheels by `scroll_step_px`, 3) scrolls to bottom, 4) waits `scroll_wait_ms`, 5) waits (best‑effort) for post count to increase.
- Stops when any of: `min_posts` reached, time budget exceeded, too many loops, or no growth for `stagnant_loops`.

---

## Consent/NSFW gates and stealth
- Cookie / consent banners: Attempts to click common Accept buttons.
- Mature content interstitial: Attempts to continue without login.
- Stealth: Sets `navigator.webdriver` to undefined, reasonable `navigator.languages`, `platform`, and a modern UA.

Limitations: Some subreddits or sessions may hard‑require login; in such cases, fallback to old.reddit is attempted but may still be limited.

---

## Fallback to old.reddit
If the new UI yields no posts (or far fewer than expected), the scraper visits `https://old.reddit.com/r/<sub>` and parses classic cards (`div.thing`). This usually returns a usable list of top posts (title/permalink/score/comments), though without the rich metadata available in the new UI.

---

## Troubleshooting & tips
- Too few posts:
  - Inspect the saved HTML under `output/pages/` to see what the DOM contained.
  - Increase `min_posts`, `max_scroll_loops`, or `max_page_seconds`.
  - Try `headless=False` to watch the scroll behavior.
- Suspected gating:
  - Manually verify if the subreddit requires login (try in a fresh incognito browser).
  - Consider using a residential proxy (`PROXY_SERVER`) and a more common UA.
- Rate limiting / flaky loads:
  - Add small sleeps between subreddits.
  - Lower `min_posts` when speed matters.
  - Rotate proxies if scraping many subreddits in a batch.

---

## Extending parsing
- The `shreddit-post` element often exposes more attributes that can be pulled in similarly to how `title`, `author`, etc. are extracted now.
- For media posts, additional selectors inside the post card may expose higher‑quality thumbnails or gallery info.
- For comments count and score, Reddit may defer rendering; prefer attribute values when present, and fall back to visible text.

---

## Error handling
- On success: returns a dict with `posts` and writes JSON when `save_frontpage` is called.
- On error or repeated timeouts: returns a dict with `posts: []` and `error: <message>`;
  a debug HTML snapshot may also be saved if enabled.

---

## Try it
Scrape one subreddit and save JSON:
```bash
python -c "from subreddit_frontpage_scraper import SubredditFrontPageScraper; s=SubredditFrontPageScraper(); s._start();\nimport time;\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\ntry:\n d=s.scrape_frontpage('r/aww'); s.save_frontpage(d['subreddit'], d)\nfinally:\n s._stop()"
```

Scrape with a proxy and a higher target:
```bash
PROXY_SERVER="http://user:pass@host:port" python -c "from subreddit_frontpage_scraper import FPConfig, SubredditFrontPageScraper; cfg=FPConfig(min_posts=80); s=SubredditFrontPageScraper(cfg); s._start();\n\n\n\n\n\n\n\n\n\n\n\n\ntry:\n d=s.scrape_frontpage('r/funny'); s.save_frontpage(d['subreddit'], d)\nfinally:\n s._stop()"
```

---

## Known limitations
- Login‑gated or quarantined subs may not expose content to anonymous sessions.
- The new Reddit UI changes frequently; selectors/attributes may require maintenance.
- Heavy scraping may trigger rate limiting; use conservative pacing and proxies.

---

## Where to look in the code
- Class: `SubredditFrontPageScraper`
  - `_apply_stealth`, `_dismiss_banners`, `_handle_mature_gate`
  - `_auto_scroll_to_load_posts` (lazy-load logic and stopping conditions)
  - `_parse_posts_new_reddit` (rich parsing of `shreddit-post`)
  - `_fetch_old_reddit` (fallback parsing)
  - `save_frontpage` (writes JSON)

For a quick sanity test, run the demo or instantiate with `headless=False` to watch the browser and confirm that posts keep loading as you scroll.
