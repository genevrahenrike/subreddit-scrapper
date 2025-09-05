## Subreddit Front Page Scraper — Usage & Internals

This guide explains how to use `subreddit_frontpage_scraper.py`, what it saves, and the non-obvious behavior (scrolling, gate handling, fallbacks, and tuning).

### What it does
- Loads `https://www.reddit.com/r/<subreddit## Configuration (FPConfig)
Key options you may want to tune:
- `headless` (bool): Run without UI. Set to `False` to watch scrolling and aid debugging.
- `proxy_server` (str | None): Use a proxy (also read from `PROXY_SERVER`).
- `timeout_ms` (int): Playwright page/context default timeouts.
- `user_agent` (str): Overrides the UA string.
- `max_attempts` (int): Browser retry attempts within one scrape.
- `include_promoted` (bool, default True): Whether to include promoted/ad content in results.

Lazy-load / scrolling knobs:
- `min_posts` (int, default 50): Target number of posts to load before stopping.
- `max_scroll_loops` (int): Hard cap on scroll iterations.
- `scroll_step_px` (int): How far to wheel-scroll per iteration.
- `scroll_wait_ms` (int): Wait after each scroll to allow network/render.
- `stagnant_loops` (int): Stop if post count hasn't increased for this many iterations.
- `max_page_seconds` (float, default 75.0): Overall time budget for a single page.
- `save_debug_html` (bool): Write a debug HTML snapshot if too few posts.ght (Chromium).
- Handles cookie/consent and mature content interstitials best‑effort without login.
- Auto-scrolls to trigger lazy loading until a target number of posts are rendered.
- Parses rich post metadata from the new Reddit UI (the `shreddit-post` and `shreddit-ad-post` web components).
- **Detects and handles promoted content** (ads) with configurable filtering options.
- **Extracts comprehensive subreddit metadata** including online user counts and sidebar widgets.
- **Intelligently parses sidebar content** with special handling for link collections and formatted text.
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
python subreddit_frontpage_scraper.py --subs r/funny r/AskReddit
```

CLI options:
```bash
python subreddit_frontpage_scraper.py \
  --subs r/aww r/funny \
  --min-posts 50 \
  --no-headless \
  --proxy "http://user:pass@host:port" \
  --debug-html \
  --exclude-promoted
```

### Promoted content handling
By default, the scraper includes promoted content (ads) in the results. You can control this behavior:

```bash
# Include promoted content (default behavior)
python subreddit_frontpage_scraper.py --subs r/technology

# Exclude promoted content from results  
python subreddit_frontpage_scraper.py --subs r/technology --exclude-promoted

# Explicitly include promoted content
python subreddit_frontpage_scraper.py --subs r/technology --include-promoted
```

The output will show promoted content statistics:
```
[saved] output/subreddits/technology/frontpage.json — posts=32 (promoted=4)
```

### Batch mode (ranked front pages)
Use the helper script to scrape many subreddits from `output/pages/page_*.json` with safe, low parallelism.

Basics:
```bash
# Default: concurrency=2, gentle pacing and browser recycle by chunk size
./scripts/run_frontpage_batch.sh

# Resume a range (indices) with 3 workers
CONCURRENCY=3 ./scripts/run_frontpage_batch.sh --start 4750 --limit 50

# Tune chunking and jitter (stagger worker starts up to 3s)
CONCURRENCY=3 INITIAL_JITTER_S=3.0 ./scripts/run_frontpage_batch.sh --chunk-size 40

# Force re-scrape of existing outputs in the range
CONCURRENCY=2 ./scripts/run_frontpage_batch.sh --start 0 --limit 20 --overwrite
```

Flags forwarded to the Python batcher:
- `--start <N>` and `--limit <K>` — process indices `[N, N+K)` from the unique ranked list.
- `--chunk-size <M>` — recycle the browser every M subs (defaults to 50 if not overridden).
- `--order rank|alpha` — order of the unique list (default: rank).
- `CONCURRENCY=<W>` — parallel Playwright processes (safe 1–3, default 2).
- `INITIAL_JITTER_S=<S>` — worker start jitter in seconds (random 0–S; default 2.0).

Pacing & safety:
- Each worker sleeps 0.5–1.2s between subreddits and staggers its start by up to `INITIAL_JITTER_S`.
- Keep `CONCURRENCY` low (2–3) unless you have ample IP capacity.

### Programmatic usage
```python
from subreddit_frontpage_scraper import FPConfig, SubredditFrontPageScraper

cfg = FPConfig(
    headless=True,            # set False to watch the browser
    min_posts=50,             # target number of posts to load
    include_promoted=True,    # include promoted/ad content (default)
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
- `meta` — comprehensive page metadata (see below).
- `posts` — list of parsed posts (see below).
- `scraped_at` — ISO timestamp.
- `error` — present only on failure.

### Meta section structure
The `meta` object includes rich subreddit information:
- `title` — subreddit display title (e.g., "r/gaming")
- `description` — community description text
- `subscribers` — total member count (numeric)
- `online_users` — current online user count (numeric) 
- `created_timestamp` — ISO timestamp of subreddit creation
- `sidebar_widgets` — array of parsed sidebar sections (see below)
- `rules` — array of community rules (when available)

### Sidebar widgets structure
The `sidebar_widgets` array contains different types of parsed content:

**Link collections** (Community Bookmarks, Useful Resources, etc.):
```json
{
  "title": "Community Bookmarks",
  "content": [
    {"text": "Community Rules", "url": "https://www.reddit.com/r/gaming/wiki/index"},
    {"text": "Other communities", "url": "https://www.reddit.com/r/gaming/wiki/faq"}
  ]
}
```

**Formatted text content** (Community Info, etc.):
```json
{
  "title": "Community Info", 
  "content": "If your submission does not appear, do not delete it. Simply message the moderators and ask us to look into it.\n\nPlease note, you are required to have some r/gaming Community Karma to make a post. Please comment around before posting.\n\nDo NOT private message or use reddit chat to contact moderators about moderator actions. Only message the team via the link above. Directly messaging individual moderators may result in a temporary ban."
}
```

**Other widgets** (simple text):
```json
{
  "title": "Installed Apps",
  "content": "Get Flair!"
}
```

### Post structure
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
- `is_promoted` (boolean indicating whether this is promoted/ad content)

Fallback (old.reddit) returns a simpler subset: `title`, `permalink`, `score`, `comments`. The scraper merges any old-Reddit-specific `meta` back into `meta`.

Debug HTML snapshot: When too few posts are found, a page snapshot is saved to `output/pages/<sub>_frontpage_debug_<timestamp>.html` for inspection.

---

## Example output improvements

### Enhanced metadata (new features)
```json
{
  "subreddit": "gaming",
  "meta": {
    "title": "r/gaming", 
    "description": "The Number One Gaming forum on the Internet.",
    "subscribers": 47085481,
    "online_users": 1374,
    "created_timestamp": "2025-09-05T03:54:52.345000+0000",
    "sidebar_widgets": [
      {
        "title": "Community Bookmarks",
        "content": [
          {"text": "Community Rules", "url": "https://www.reddit.com/r/gaming/wiki/index"},
          {"text": "Other communities", "url": "https://www.reddit.com/r/gaming/wiki/faq"}
        ]
      },
      {
        "title": "Community Info",
        "content": "If your submission does not appear, do not delete it. Simply message the moderators and ask us to look into it.\n\nPlease note, you are required to have some r/gaming Community Karma to make a post. Please comment around before posting.\n\nDo NOT private message or use reddit chat to contact moderators about moderator actions. Only message the team via the link above. Directly messaging individual moderators may result in a temporary ban."
      }
    ]
  }
}
```

### Cross-subreddit compatibility
The scraper automatically adapts to different subreddit layouts:

**r/AskReddit** - Many bookmarks:
```json
{
  "title": "Community Bookmarks",
  "content": [
    {"text": "Wiki", "url": "/r/AskReddit/wiki/index/"}, 
    {"text": "Ask Others", "url": "https://www.reddit.com/r/AskReddit/wiki/sidebarsubs#wiki_ask_others"},
    {"text": "AskReddit Offshoots", "url": "https://www.reddit.com/r/AskReddit/wiki/sidebarsubs#wiki_askreddit_offshoots"},
    {"text": "Find a Subreddit", "url": "https://www.reddit.com/r/AskReddit/wiki/sidebarsubs#wiki_find_a_subreddit"}
  ]
}
```

**r/sports** - Different naming convention:
```json
{
  "title": "Useful Resources", 
  "content": [
    {"text": "sports subreddits", "url": "http://www.reddit.com/r/sports/wiki/related"},
    {"text": "reddiquette", "url": "https://www.reddit.com/wiki/reddiquette"},
    {"text": "self-promotion", "url": "https://www.reddit.com/wiki/selfpromotion"}
  ]
}
```

---

## Promoted content features

### Detection and parsing
The scraper automatically detects promoted content (ads) through multiple indicators:
- **Element type**: `shreddit-ad-post` web components (new Reddit)
- **Aria labels**: Elements with `aria-label` containing "promoted" or "advertisement"
- **Visual indicators**: Sponsored post markers and promotional badges

### Configuration options
Control promoted content inclusion through:
- **CLI flags**: `--include-promoted` (default) or `--exclude-promoted`
- **FPConfig**: `include_promoted=True/False` parameter
- **Filtering**: Applied after parsing, so metadata includes accurate counts

### Output enhancements
- **Post metadata**: Each post includes `is_promoted: true/false` field
- **Statistics**: Console output shows `posts=X (promoted=Y)` breakdown
- **Filtering transparency**: Promoted count reflects detected ads, regardless of inclusion setting

### Example promoted content output
```json
{
  "title": "Sponsored: New Tech Product Launch",
  "permalink": "https://www.reddit.com/r/technology/comments/...",
  "score": 42,
  "comments": 15,
  "is_promoted": true,
  "post_type": "link",
  "domain": "example.com"
}
```

---

## Metadata parsing features

### Online users detection
The scraper automatically detects and extracts the current number of online users by:
- Locating `faceplate-number` elements with numeric attributes
- Identifying elements followed by "online" text
- Extracting the raw numeric value (not the formatted display text)
- Storing as `online_users` in the metadata

### Flexible sidebar widget parsing
The scraper intelligently handles various sidebar content types:

**Automatic link collection detection**: Any sidebar section with 2+ links is automatically parsed as structured link data, regardless of title. Works with:
- "Community Bookmarks" (common)
- "Useful Resources" (r/sports style)
- "Quick Links", "Related Links", etc.

**Smart text extraction**: For non-link sections like Community Info:
- Preserves paragraph structure with proper line breaks
- Removes technical artifacts (SC_OFF/SC_ON markers)
- Handles proper spacing around links and text
- Filters out duplicate titles and noise

**Robust link text parsing**: For link collections:
- Handles hover states and hidden elements
- Eliminates duplicate text from accessibility features
- Extracts clean link text and URLs
- Supports complex HTML structures with multiple spans

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
  - Keep batch `CONCURRENCY` at 2–3 and use `INITIAL_JITTER_S` to avoid synchronized bursts.

---

## Extending parsing
- The `shreddit-post` and `shreddit-ad-post` elements often expose more attributes that can be pulled in similarly to how `title`, `author`, etc. are extracted now.
- For media posts, additional selectors inside the post card may expose higher‑quality thumbnails or gallery info.
- For comments count and score, Reddit may defer rendering; prefer attribute values when present, and fall back to visible text.
- **Promoted content detection** can be enhanced by adding new selectors or attributes to identify different types of ad content.
- **Sidebar widget parsing** is highly flexible and automatically adapts to new widget types and naming conventions across different subreddits.
- **Metadata extraction** can be extended by adding new selectors to the `_parse_meta` method for additional community information.

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
  - `_parse_posts_new_reddit` (rich parsing of `shreddit-post` and `shreddit-ad-post`)
  - `_parse_meta` (comprehensive metadata extraction including online users and sidebar widgets)
  - `_fetch_old_reddit` (fallback parsing)
  - `save_frontpage` (writes JSON)

**Key parsing methods:**
- `_parse_meta`: Handles online users, sidebar widgets, creation timestamps
- `_parse_posts_new_reddit`: Enhanced to detect and parse promoted content from `shreddit-ad-post` elements
- Promoted content detection: Uses element type and aria-label attributes to identify ads
- Sidebar parsing logic: Automatically detects link collections vs. text content
- Text extraction: Preserves formatting and handles complex HTML structures

For a quick sanity test, run the demo or instantiate with `headless=False` to watch the browser and confirm that posts keep loading as you scroll.
