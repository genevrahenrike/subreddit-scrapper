## Subreddit Front Page Scraper — Usage & Internals

This guide explains how to use `subreddit_frontpage_scraper.py`, what it saves, and the non-obvious behavior (scrolling, gate handling, fallbacks, and tuning).

### What it does
- Loads `https://www.reddit.com/r/<subreddit>` front page with Playwright using multiple browser engines.
- **Multi-browser fingerprinting**: Supports Chromium, WebKit (Safari-like), and Firefox engines with authentic user agent profiles.
- **Intelligent profile rotation**: Automatically switches between browser profiles to reduce detection and blocking.
- **Persistent session support**: Maintains cookies and cache across requests for improved performance and authenticity.
- Handles cookie/consent and mature content interstitials best‑effort without login.
- Auto-scrolls to trigger lazy loading until a target number of posts are rendered.
- Parses rich post metadata from the new Reddit UI (the `shreddit-post` and `shreddit-ad-post` web components).
- **Detects and handles promoted content** (ads) with configurable filtering options.
- **Extracts comprehensive subreddit metadata** including online user counts and sidebar widgets.
- **Intelligently parses sidebar content** with special handling for link collections and formatted text.
- **Enhanced anti-detection**: Human-like scrolling patterns, randomized delays, and engine-specific stealth evasions.
- Falls back to `https://old.reddit.com/r/<subreddit>/` if the new UI yields no/too few posts.
- Saves JSON to `output/subreddits/<name>/frontpage.json`; optionally saves HTML snapshots for debugging.

---

## Prerequisites
- Python 3.9+
- Dependencies: `pip install -r requirements.txt`
- Browser engines (install as needed):
  - Chromium (default): `playwright install chromium`
  - WebKit (Safari-like): `playwright install webkit`  
  - Firefox: `playwright install firefox`
  - All browsers: `playwright install`

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
  --exclude-promoted \
  --offset 1000 \
  --overwrite \
  --multi-profile \
  --persistent-session \
  --disable-images \
  --wait-for-internet \
  --internet-check-interval 15.0
```

---

## Bandwidth optimization and connectivity handling

### Image download control
By default, the scraper blocks image downloads to save bandwidth, especially important when using residential proxies with data limits:

```bash
# Images blocked by default (recommended for bandwidth saving)
python subreddit_frontpage_scraper.py --subs r/technology

# Explicitly disable images
python subreddit_frontpage_scraper.py --subs r/technology --disable-images

# Enable image downloads (uses more bandwidth)
python subreddit_frontpage_scraper.py --subs r/technology --enable-images
```

**Benefits of blocking images:**
- Significantly reduced bandwidth usage (often 70-90% savings)
- Faster page loading times
- More efficient for residential proxy usage
- Post metadata and text content remain fully available

### Internet connectivity monitoring
The scraper can distinguish between rate limiting and actual internet connectivity issues, automatically waiting for connection restoration:

```bash
# Wait for internet connection (default behavior)
python subreddit_frontpage_scraper.py --subs r/technology

# Don't wait for internet, fail immediately on connectivity issues
python subreddit_frontpage_scraper.py --subs r/technology --no-wait-internet

# Use custom connectivity check endpoint and interval
python subreddit_frontpage_scraper.py --subs r/technology \
  --internet-check-url "https://httpbin.org/status/204" \
  --internet-check-interval 5.0
```

**How connectivity monitoring works:**
- Automatically detects internet connectivity errors (vs rate limiting)
- Uses Google's generate_204 endpoint for reliable connectivity checks
- Waits and retries until internet connection is restored
- Resets retry counter when connection is back
- Distinguishes between network issues and Reddit rate limiting

**Common connectivity error patterns detected:**
- `ERR_INTERNET_DISCONNECTED` - Complete internet loss
- `ERR_NETWORK_CHANGED` - Network interface changes
- `ERR_PROXY_CONNECTION_FAILED` - Proxy connectivity issues
- `ECONNREFUSED` / `EHOSTUNREACH` - Network unreachable

---

## Browser Fingerprinting & Anti-Detection Features

### Browser Engine Selection
Choose from multiple browser engines to diversify your fingerprints and reduce detection:

```bash
# Use WebKit (Safari-like) - most human-like on macOS
python subreddit_frontpage_scraper.py --subs r/technology --browser-engine webkit

# Use Firefox for different fingerprint  
python subreddit_frontpage_scraper.py --subs r/programming --browser-engine firefox

# Use Chromium (default)
python subreddit_frontpage_scraper.py --subs r/gaming --browser-engine chromium
```

**Browser Profiles:**
- **WebKit**: Safari 18.6 profile with authentic macOS headers and user agent
- **Chromium**: Chrome 124 profile with comprehensive stealth evasions
- **Firefox**: Firefox 130 profile with Mozilla-specific headers

### Multi-Profile Rotation
Automatically rotate between different browser profiles to maximize fingerprint diversity:

```bash
# Enable multi-profile rotation (switches every 3 requests)
python subreddit_frontpage_scraper.py --subs r/a r/b r/c r/d r/e --multi-profile

# Output shows which profile was used:
# [saved] output/subreddits/a/frontpage.json [webkit] — posts=25 (promoted=2)
# [saved] output/subreddits/b/frontpage.json [webkit] — posts=30 (promoted=1) 
# [saved] output/subreddits/c/frontpage.json [webkit] — posts=22 (promoted=3)
# [profile] Switching browser profile after 3 requests
# [browser] Started firefox engine
# [saved] output/subreddits/d/frontpage.json [firefox] — posts=28 (promoted=2)
```

**How Multi-Profile Works:**
- Profiles are shuffled randomly on startup
- Switches browser engine every 3 subreddits by default
- Closes and restarts browser when changing engines
- Creates fresh context for same-engine switches
- Shows current profile in output for transparency

### Persistent Sessions
Enable persistent browser sessions with cookies and cache for improved performance and authenticity:

```bash
# Use persistent session with default directory
python subreddit_frontpage_scraper.py --subs r/news --persistent-session

# Use custom user data directory  
python subreddit_frontpage_scraper.py --subs r/worldnews --persistent-session --user-data-dir ./my_browser_data

# Combine with specific browser engine
python subreddit_frontpage_scraper.py --subs r/science --browser-engine webkit --persistent-session
```

**Benefits of Persistent Sessions:**
- Maintains cookies across requests (appears as returning user)
- Leverages browser cache for faster page loads
- Preserves session state and preferences
- Reduces network traffic and improves throughput
- More authentic browsing patterns

### Advanced Anti-Detection Features

**Human-like Behavior:**
- Randomized scroll patterns (varying speeds, multiple small scrolls)
- Mouse movements before clicking elements
- Variable delays between actions (0.5-1.2s jitter)
- Realistic viewport sizes (1280-1440x800-900)

**Engine-Specific Stealth:**
- **WebKit**: Safari vendor strings, Apple-specific navigator properties
- **Chromium**: Chrome runtime objects, plugin emulation, permissions API
- **Firefox**: Mozilla build IDs, Gecko-specific properties

**Enhanced Error Recovery:**
- Context recycling on connection errors for fresh fingerprints
- Automatic profile switching during retries
- Exponential backoff with jitter (2s, 4s, 8s...)
- Intelligent retry patterns based on error type

---

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

### Parallel execution and range splitting
For large-scale scraping across multiple servers or processes:

```bash
# Single server with 12 processes
CONCURRENCY=12 OVERWRITE=1 ./scripts/run_frontpage_batch.sh

# Split across 6 servers with 4 processes each (24 total)
# Server 1
PROXY_SERVER="http://proxy1:port" CONCURRENCY=4 OVERWRITE=1 \
./scripts/run_frontpage_batch.sh --start 0 --limit 55472

# Server 2  
PROXY_SERVER="http://proxy2:port" CONCURRENCY=4 OVERWRITE=1 \
./scripts/run_frontpage_batch.sh --start 55472 --limit 55472

# And so on...
```

Use the job generator for automatic splitting:
```bash
# Generate commands for 6 servers
python3 scripts/generate_parallel_jobs.py --servers 6 --concurrency 4
```

### Individual scraper with offset support
The main scraper now supports offset for manual parallelization:

```bash
# Process 1: Start from beginning
python subreddit_frontpage_scraper.py --subs r/sub1 r/sub2 r/sub3 --offset 0

# Process 2: Skip first subreddit, start from second
python subreddit_frontpage_scraper.py --subs r/sub1 r/sub2 r/sub3 --offset 1

# With file input (if using retry lists)
python subreddit_frontpage_scraper.py --file retry_list.txt --offset 5000 --overwrite
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

### Error analysis and retry functionality
Analyze scraping results to identify and retry failed subreddits:

```bash
# Analyze current results
python3 scripts/analyze_results.py

# Generate retry list for connection errors
python3 scripts/analyze_results.py --generate-retry --error-types CONNECTION_REFUSED CONNECTION_RESET TIMEOUT

# Retry failed subreddits
python subreddit_frontpage_scraper.py --file retry_subreddits.txt --overwrite
```

The analyzer categorizes errors:
- `CONNECTION_REFUSED` / `CONNECTION_RESET` - Network connectivity issues
- `TIMEOUT` - Request timeouts, often retryable  
- `SERVICE_UNAVAILABLE` / `BAD_GATEWAY` - Server-side issues
- `NOT_FOUND` - Subreddit doesn't exist
- `NO_POSTS` - Subreddit exists but no posts found
- `OTHER` - Miscellaneous errors

### Programmatic usage
```python
from subreddit_frontpage_scraper import FPConfig, SubredditFrontPageScraper

# Basic configuration with bandwidth optimization
cfg = FPConfig(
    headless=True,                    # set False to watch the browser
    min_posts=50,                     # target number of posts to load
    include_promoted=True,            # include promoted/ad content (default)
    max_attempts=3,                   # retry attempts (increased from 2)
    retry_delay_base=2.0,            # base delay for exponential backoff
    disable_images=True,             # block images to save bandwidth (default)
    wait_for_internet=True,          # wait for internet restoration (default)
)

# Advanced browser fingerprinting configuration with connectivity monitoring
cfg_advanced = FPConfig(
    headless=True,
    retry_connection_errors=True,
    disable_images=True,             # save bandwidth on residential proxies
    wait_for_internet=True,          # intelligent connectivity handling
    internet_check_interval=15.0,   # check every 15 seconds when offline
)

scraper = SubredditFrontPageScraper(cfg_advanced)
scraper._start()
try:
    # Scrape multiple subreddits with profile rotation
    for sub in ["r/technology", "r/programming"]:
        data = scraper.scrape_frontpage(sub)
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
- `user_agent` (str): Overrides the UA string (auto-set by browser_engine).
- `max_attempts` (int, default 3): Browser retry attempts within one scrape (increased from 2).
- `include_promoted` (bool, default True): Whether to include promoted/ad content in results.
- `browser_engine` (str, default "chromium"): Browser engine to use - "chromium", "webkit", or "firefox"
- `multi_profile` (bool, default False): Rotate between different browser profiles for fingerprint diversity
- `persistent_session` (bool, default False): Use persistent user data directory with cookies and cache
- `user_data_dir` (str | None): Custom directory for persistent browser user data (auto-generated if None)

Bandwidth optimization:
- `disable_images` (bool, default True): Block image downloads to save bandwidth and improve speed
- `wait_for_internet` (bool, default True): Wait for internet connection to be restored before continuing
- `internet_check_url` (str, default "https://www.google.com/generate_204"): Reliable endpoint for connectivity checks
- `internet_check_interval` (float, default 5.0): Seconds between connectivity checks when offline

Enhanced error handling:
- `retry_connection_errors` (bool, default True): Retry on connection errors like ERR_CONNECTION_REFUSED.
- `retry_delay_base` (float, default 2.0): Base delay for exponential backoff between retries.

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
- Cookie / consent banners: Attempts to click common Accept buttons with human-like delays and mouse movements.
- Mature content interstitial: Attempts to continue without login using multiple selectors.
- **Multi-engine stealth**: Engine-specific anti-detection measures:
  - **WebKit**: Safari vendor strings, Apple navigator properties, authentic macOS fingerprint
  - **Chromium**: Chrome runtime objects, plugin emulation, permissions API, sec-ch-ua headers
  - **Firefox**: Mozilla build IDs, Gecko-specific properties, Firefox navigator attributes
- **Human-like behavior**: Randomized delays, mouse movements, variable scroll patterns, realistic viewport sizes
- **Context recycling**: Fresh browser contexts on errors for improved fingerprint diversity

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
  - **Try different browser engines**: `--browser-engine webkit` or `--browser-engine firefox`
  - **Enable multi-profile rotation**: `--multi-profile` to switch between fingerprints
  - Consider using a residential proxy (`PROXY_SERVER`) and persistent sessions (`--persistent-session`)
- Rate limiting / flaky loads:
  - Add small sleeps between subreddits.
  - Lower `min_posts` when speed matters.
  - **Use multi-profile mode**: `--multi-profile` to rotate between browser fingerprints
  - Rotate proxies if scraping many subreddits in a batch.
  - Keep batch `CONCURRENCY` at 2–3 and use `INITIAL_JITTER_S` to avoid synchronized bursts.
- Connection errors / blocking episodes:
  - **Switch browser engines**: WebKit often bypasses Chrome-specific blocks
  - **Enable context recycling**: Automatic on retries with enhanced error recovery
  - Most connection errors (ERR_CONNECTION_REFUSED, timeouts) are automatically retried
  - Use `scripts/analyze_results.py` to identify patterns in failed subreddits
  - Generate retry lists for persistent failures: `--generate-retry --error-types CONNECTION_REFUSED`
- Large-scale scraping:
  - **Use different browser engines per server**: Distribute fingerprint diversity
  - Split work across multiple servers using `--start` and `--limit` arguments
  - Use different proxies/IPs per server to avoid rate limiting
  - Monitor progress with `output/subreddits/manifest.json`

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

### Enhanced retry logic
The scraper now includes intelligent retry logic:
- **Retryable errors**: Connection refused, timeouts, 5xx server errors are automatically retried
- **Exponential backoff**: Delays increase between retries (2s, 4s, 8s...) with jitter
- **Error categorization**: Different handling for network vs. application errors
- **Retry logging**: Shows retry attempts with truncated error messages

Example retry output:
```
[retry] singapore attempt 2/3 after 2.1s (error: Page.goto: net::ERR_CONNECTION_REFUSED at https://www.reddit.com/r/singapore...)
```

### Batch processing improvements
Enhanced error logging in batch mode categorizes errors:
- `[w5 conn-error]` - Connection-related errors
- `[w5 timeout]` - Timeout errors  
- `[w5 error]` - Other errors
- `[w5 exception]` - Unexpected exceptions

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

## Browser Fingerprinting Examples & Best Practices

### Quick Anti-Detection Tests
Test different browser engines to see which works best for your use case:

```bash
# Test WebKit (Safari-like) - often most successful on macOS
python3 subreddit_frontpage_scraper.py --subs r/technology --browser-engine webkit --min-posts 10

# Test Firefox - good middle ground  
python3 subreddit_frontpage_scraper.py --subs r/technology --browser-engine firefox --min-posts 10

# Test Chromium - most features but also most detected
python3 subreddit_frontpage_scraper.py --subs r/technology --browser-engine chromium --min-posts 10
```

### Production Multi-Profile Setup
For large-scale scraping with maximum fingerprint diversity:

```bash
# Multi-profile with persistent sessions and proxy
python3 subreddit_frontpage_scraper.py \
  --file subreddit_list.txt \
  --multi-profile \
  --persistent-session \
  --proxy "http://user:pass@residential-proxy:port" \
  --min-posts 25 \
  --overwrite

# Output shows profile rotation:
# [browser] Started webkit engine
# [saved] output/subreddits/tech/frontpage.json [webkit] — posts=32 (promoted=3)
# [saved] output/subreddits/prog/frontpage.json [webkit] — posts=28 (promoted=2)
# [saved] output/subreddits/web/frontpage.json [webkit] — posts=30 (promoted=1)
# [profile] Switching browser profile after 3 requests
# [browser] Started firefox engine
# [saved] output/subreddits/python/frontpage.json [firefox] — posts=25 (promoted=2)
```

### Batch Processing with Fingerprint Diversity
Split work across multiple processes/servers with different browser profiles:

```bash
# Server 1: WebKit engine with proxy 1
PROXY_SERVER="http://proxy1:port" python3 subreddit_frontpage_scraper.py \
  --file batch1.txt --browser-engine webkit --persistent-session

# Server 2: Firefox engine with proxy 2  
PROXY_SERVER="http://proxy2:port" python3 subreddit_frontpage_scraper.py \
  --file batch2.txt --browser-engine firefox --persistent-session

# Server 3: Multi-profile rotation with proxy 3
PROXY_SERVER="http://proxy3:port" python3 subreddit_frontpage_scraper.py \
  --file batch3.txt --multi-profile --persistent-session
```

### Recovery from Blocking Episodes
When experiencing connection refusal or rate limiting:

```bash
# Generate retry list from failed attempts
python3 scripts/analyze_results.py --generate-retry --error-types CONNECTION_REFUSED TIMEOUT

# Retry with different browser engine and fresh sessions
python3 subreddit_frontpage_scraper.py \
  --file retry_subreddits.txt \
  --browser-engine webkit \
  --overwrite \
  --min-posts 15

# If still blocked, try multi-profile with longer delays
python3 subreddit_frontpage_scraper.py \
  --file retry_subreddits.txt \
  --multi-profile \
  --persistent-session \
  --overwrite
```

### Debugging Browser Fingerprints
Watch browser behavior to debug detection issues:

```bash
# Watch WebKit in action (non-headless)
python3 subreddit_frontpage_scraper.py \
  --subs r/test \
  --browser-engine webkit \
  --no-headless \
  --debug-html

# Compare behavior across engines
for engine in webkit firefox chromium; do
  echo "Testing $engine engine..."
  python3 subreddit_frontpage_scraper.py \
    --subs r/test --browser-engine $engine --overwrite --min-posts 5
done
```

---

## Known limitations
- Login‑gated or quarantined subs may not expose content to anonymous sessions.
- The new Reddit UI changes frequently; selectors/attributes may require maintenance.
- Heavy scraping may trigger rate limiting; use conservative pacing, proxies, and profile rotation.
- **WebKit limitations**: Fewer configuration options compared to Chromium, but often most successful.
- **Firefox limitations**: Some persistent session features work differently than Chromium.

---

## Where to look in the code
- Class: `SubredditFrontPageScraper`
  - `_start`, `_start_browser` (multi-engine browser initialization)
  - `_get_current_profile`, `_recycle_browser_for_multi_profile` (profile rotation logic)
  - `_apply_stealth`, `_dismiss_banners`, `_handle_mature_gate` (enhanced anti-detection)
  - `_auto_scroll_to_load_posts` (human-like scrolling with randomization)
  - `_parse_posts_new_reddit` (rich parsing of `shreddit-post` and `shreddit-ad-post`)
  - `_parse_meta` (comprehensive metadata extraction including online users and sidebar widgets)
  - `_fetch_old_reddit` (fallback parsing)
  - `save_frontpage` (writes JSON)

**Key browser fingerprinting components:**
- `BROWSER_PROFILES`: Dictionary of authentic browser profiles (WebKit, Chromium, Firefox)
- `_apply_stealth`: Engine-specific anti-detection measures
- Multi-profile rotation: Automatic browser switching every 3 requests
- Context recycling: Fresh fingerprints on connection errors
- Human behavior simulation: Randomized delays, mouse movements, scroll patterns

**Key parsing methods:**
- `_parse_meta`: Handles online users, sidebar widgets, creation timestamps
- `_parse_posts_new_reddit`: Enhanced to detect and parse promoted content from `shreddit-ad-post` elements
- Promoted content detection: Uses element type and aria-label attributes to identify ads
- Sidebar parsing logic: Automatically detects link collections vs. text content
- Text extraction: Preserves formatting and handles complex HTML structures

**New utility scripts:**
- `scripts/generate_parallel_jobs.py`: Generate commands for splitting work across multiple servers
- `scripts/analyze_results.py`: Analyze scraping results and generate retry lists
- Enhanced error handling in `scrape_frontpage` with intelligent retry logic and exponential backoff

---

## Try it

### Quick test with different browser engines
Scrape one subreddit and save JSON with different browser fingerprints:

```bash
# Test WebKit (Safari-like) - recommended for macOS
python3 subreddit_frontpage_scraper.py --subs r/aww --browser-engine webkit --min-posts 10

# Test with persistent session for cache benefits
python3 subreddit_frontpage_scraper.py --subs r/funny --browser-engine webkit --persistent-session --min-posts 10

# Test multi-profile rotation  
python3 subreddit_frontpage_scraper.py --subs r/a r/b r/c r/d --multi-profile --min-posts 5
```

### Advanced fingerprinting test with bandwidth optimization
Scrape with maximum anti-detection features and bandwidth savings:

```bash
# Multi-profile + persistent sessions + proxy + bandwidth optimization
PROXY_SERVER="http://user:pass@host:port" python3 subreddit_frontpage_scraper.py \
  --subs r/technology r/programming r/webdev \
  --multi-profile \
  --persistent-session \
  --disable-images \
  --wait-for-internet \
  --min-posts 20 \
  --debug-html
```

### Programmatic test with all features
```python
from subreddit_frontpage_scraper import FPConfig, SubredditFrontPageScraper

# Maximum anti-detection configuration with bandwidth optimization
cfg = FPConfig(
    browser_engine="webkit",          # Safari-like engine
    multi_profile=True,               # Rotate profiles
    persistent_session=True,          # Maintain cookies/cache
    disable_images=True,              # Save bandwidth
    wait_for_internet=True,           # Handle connectivity issues
    headless=True,                    # or False to watch
    min_posts=20,
    max_attempts=3,
)

scraper = SubredditFrontPageScraper(cfg)
scraper._start()
try:
    for sub in ["r/technology", "r/programming", "r/webdev"]:
        data = scraper.scrape_frontpage(sub)
        scraper.save_frontpage(data["subreddit"], data)
        print(f"✅ {sub}: {len(data['posts'])} posts with {scraper._current_engine}")
finally:
    scraper._stop()
```

For a quick sanity test, run the demo or instantiate with `headless=False` to watch the browser and confirm that posts keep loading as you scroll.

# Network Priority Control for Reddit Scraper

This section explains how to run the Reddit scraper with lower network and CPU priority to avoid competing with important user traffic.

## Quick Start

### Method 1: Built-in Low Priority Flag
```bash
# Run with low priority
python subreddit_frontpage_scraper.py --subs r/technology --low-priority

# Custom nice level (higher = lower priority)
python subreddit_frontpage_scraper.py --subs r/technology --low-priority --nice-level 15
```

### Method 2: Shell Wrapper (Recommended)
```bash
# Basic low priority run
./run_low_priority.sh -- --subs r/technology r/programming

# With bandwidth limiting (requires trickle)
./run_low_priority.sh -b 500k -- --subs r/technology --min-posts 30

# Custom nice level
./run_low_priority.sh -n 15 -- --subs r/technology --disable-images
```

## How It Works

### CPU Priority (Process Nice Level)
- Uses Unix `nice` command to lower CPU scheduling priority
- Nice levels: 0 (normal) to 19 (lowest priority)
- Default low priority level: 10
- Higher numbers = lower priority = less CPU competition

### I/O Priority (Linux only)
- Automatically attempts to set I/O priority to "idle" class using `ionice`
- On macOS, this feature is not available but the script continues normally
- Reduces disk I/O competition with user applications

### Network Bandwidth Limiting (Optional)
- Uses `trickle` utility for bandwidth throttling
- Install: `brew install trickle` (macOS) or `apt-get install trickle` (Linux)
- Limits both download and upload bandwidth
- Does NOT slow down the scraper, just prevents it from saturating the connection

## Installation Requirements

### Basic (CPU Priority only)
No additional installation needed - uses built-in Unix `nice` command.

### Advanced (Network Bandwidth Control)
```bash
# macOS
brew install trickle

# Ubuntu/Debian
sudo apt-get install trickle

# CentOS/RHEL
sudo yum install trickle
```

## Usage Examples

### Background Processing During Work Hours
```bash
# Low priority with bandwidth limit during business hours
./run_low_priority.sh -n 15 -b 300k -- --subs r/technology r/programming r/webdev

# Very low priority for overnight runs
./run_low_priority.sh -n 19 -b 1m -- --file large_subreddit_list.txt
```

### Development Testing
```bash
# Low priority development testing
./run_low_priority.sh -- --subs r/test --headless --min-posts 5 --overwrite
```

### Batch Processing
```bash
# Large batch with minimal system impact
./run_low_priority.sh -n 15 -b 500k -- \
  --file subreddit_list.txt \
  --disable-images \
  --min-posts 25 \
  --multi-profile
```

## Configuration Options

### Built-in Options
- `--low-priority`: Enable low priority mode
- `--nice-level N`: Set nice level (0-19, default: 10)

### Shell Wrapper Options
- `-n, --nice LEVEL`: Set nice level (0-19, default: 10)
- `-b, --bandwidth LIMIT`: Bandwidth limit (e.g., 500k, 1m)
- `-t, --use-trickle`: Force use of trickle
- `-h, --help`: Show help

## Bandwidth Limit Formats
- `500k` = 500 KB/s
- `1m` = 1 MB/s  
- `2000k` = 2 MB/s
- Numbers without suffix = KB/s

## Monitoring Impact

### Check Process Priority
```bash
# Find the scraper process
ps aux | grep subreddit_frontpage_scraper

# Check nice level (NI column)
ps -l -p <PID>
```

### Monitor Network Usage
```bash
# macOS - monitor network activity
nettop -p <PID>

# Linux - monitor bandwidth
iftop
nethogs
```

## Troubleshooting

### Permission Issues
If you get permission errors with `ionice`:
```bash
# The script will continue without I/O priority - this is normal on macOS
```

### Trickle Not Working
```bash
# Check if trickle is installed
which trickle

# Install trickle
brew install trickle  # macOS
sudo apt-get install trickle  # Linux
```

### Bandwidth Still High
- Ensure `--disable-images` is used (blocks 70-90% of bandwidth)
- Lower the bandwidth limit: `-b 200k` instead of `-b 1m`
- Check if multiple processes are running

## Performance Impact

### Without Low Priority
- May saturate network connection
- Can cause lag in video calls, streaming, etc.
- Competes with user applications for CPU

### With Low Priority  
- Automatically yields to user applications
- Network usage controlled and predictable
- Minimal impact on system responsiveness
- Scraping throughput barely affected

## Integration with Batch Scripts

```bash
# Add to existing batch processing
CONCURRENCY=2 ./scripts/run_frontpage_batch.sh --low-priority

# Custom wrapper in your own scripts
nice -n 15 trickle -d 500 -u 200 python subreddit_frontpage_scraper.py --subs "$@"
```

## Best Practices

1. **Always use `--disable-images`** for maximum bandwidth savings
2. **Use nice level 10-15** for background processing during work
3. **Use nice level 15-19** for overnight batch processing  
4. **Set bandwidth limits** when sharing connection with others
5. **Monitor system impact** initially to find optimal settings
6. **Use the shell wrapper** for maximum control and convenience

This ensures the scraper runs efficiently in the background without interfering with your important work!
