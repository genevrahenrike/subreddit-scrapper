devlog-frontpage-scraper.md

Implemented connectivity hardening and proxy-pool capabilities as requested:

Key enhancements
- Immediate traffic-pattern refresh on refusal
  - On first detection of connection-refused errors (including NS_ERROR_CONNECTION_REFUSED), the scraper performs a low-cost external traffic refresh to break the single-site traffic pattern before any cooldown is applied.
  - Code: [python.SubredditFrontPageScraper._traffic_pattern_refresh()](subreddit_frontpage_scraper.py:669), wired in [python.SubredditFrontPageScraper.scrape_frontpage()](subreddit_frontpage_scraper.py:1180).

- Periodic low-frequency refresh while healthy
  - When enabled, a refresh runs every N seconds (default 300s) in healthy states, both at the start of a scrape and right after cooldown ends.
  - Code paths: [python.SubredditFrontPageScraper.scrape_frontpage()](subreddit_frontpage_scraper.py:1021) and post-cooldown refresh at [python.SubredditFrontPageScraper.scrape_frontpage()](subreddit_frontpage_scraper.py:1066).

- Robust proxy pool rotation (HTTP + SOCKS5)
  - Load pools from JSON files with entries having url and status "OK".
  - On refusal episodes, optionally switch to the next proxy; after a configurable number of healthy successes, optionally restore direct.
  - Loader: [python.SubredditFrontPageScraper._load_proxy_pool()](subreddit_frontpage_scraper.py:696)
  - Switch: [python.SubredditFrontPageScraper._switch_to_next_proxy()](subreddit_frontpage_scraper.py:784)
  - Apply change with safe restart: [python.SubredditFrontPageScraper._apply_proxy_change()](subreddit_frontpage_scraper.py:736)
  - Restore direct: [python.SubredditFrontPageScraper._maybe_restore_direct()](subreddit_frontpage_scraper.py:801)

- Expanded refusal detection
  - Now includes NS_ERROR_CONNECTION_REFUSED explicitly across engines.
  - Code: [python.SubredditFrontPageScraper._is_connection_refused_error()](subreddit_frontpage_scraper.py:557)

Configuration and CLI
- New FPConfig fields: see [python.FPConfig](subreddit_frontpage_scraper.py:73)
  - traffic_refresh_enabled (default True)
  - traffic_refresh_interval_seconds (default 300.0)
  - traffic_refresh_on_refused (default True)
  - use_proxy_pool (default False)
  - proxy_pool_http_file (default "config/http.proxies.json")
  - proxy_pool_socks5_file (default "config/socks5.proxies.json")
  - switch_to_proxy_on_refused (default False)
  - restore_direct_after_successes (default 8)

- New CLI flags (wired to FPConfig): [python.__main__ argparser](subreddit_frontpage_scraper.py:1813)
  - Traffic refresh
    - --traffic-refresh-enabled | --no-traffic-refresh
    - --traffic-refresh-interval-seconds 300
  - Proxy pool
    - --use-proxy-pool
    - --proxy-pool-http-file config/http.proxies.json
    - --proxy-pool-socks5-file config/socks5.proxies.json
    - --switch-to-proxy-on-refused
    - --restore-direct-after-successes 8

Examples
- Periodic refresh + immediate refresh on refusal, no proxies:
  - python subreddit_frontpage_scraper.py --subs r/aww r/funny --traffic-refresh-enabled --traffic-refresh-interval-seconds 300

- Use proxy pool; switch to proxy on refusal; restore direct after 8 healthy successes:
  - python subreddit_frontpage_scraper.py --file retry_subreddits.txt --use-proxy-pool --proxy-pool-http-file config/http.proxies.json --proxy-pool-socks5-file config/socks5.proxies.json --switch-to-proxy-on-refused --restore-direct-after-successes 8 --overwrite

Docs updated
- Added a new section explaining refresh + proxy pool: [doc/Traffic Pattern Refresh and Proxy Pool (New)](doc/Subreddit Front Page Scraper.md:1)
  - Cross-references: [python.SubredditFrontPageScraper._traffic_pattern_refresh()](subreddit_frontpage_scraper.py:669), [python.SubredditFrontPageScraper._load_proxy_pool()](subreddit_frontpage_scraper.py:696), [python.SubredditFrontPageScraper._apply_proxy_change()](subreddit_frontpage_scraper.py:736), [python.SubredditFrontPageScraper._switch_to_next_proxy()](subreddit_frontpage_scraper.py:784), [python.SubredditFrontPageScraper._maybe_restore_direct()](subreddit_frontpage_scraper.py:801)

Notes
- The refresh uses lightweight requests (ipify/httpbin/google 204) and a brief visit to example.com; images remain blocked by default to minimize bandwidth.
- When switching proxy, Playwright is safely restarted with the new proxy at context/browser creation; persistent session semantics are preserved.
- Global cooldown and quiet refusal handling remain intact; the refresh complements cooldown to recover instantly when the ISP has temporarily blocked the single-destination pattern.

Files modified
- [subreddit_frontpage_scraper.py](subreddit_frontpage_scraper.py:1) — new config fields, refresh/proxy-pool logic and CLI flags; refusal detection extended
- [doc/Subreddit Front Page Scraper.md](doc/Subreddit Front Page Scraper.md:1) — documentation for refresh & proxy pool

---

Defaults are now wired in—no CLI flags required:

What is on by default (zero-args)
- Traffic pattern refresh
  - Periodic refresh every 300s to vary traffic.
  - Immediate refresh when a refusal episode is detected.
  - Config defaults: traffic_refresh_enabled=True, traffic_refresh_interval_seconds=300.0, traffic_refresh_on_refused=True
  - Code: [python.SubredditFrontPageScraper._traffic_pattern_refresh()](subreddit_frontpage_scraper.py:669), invoked at start of scrape and post‑cooldown [python.SubredditFrontPageScraper.scrape_frontpage()](subreddit_frontpage_scraper.py:1021), and immediately on refusal [python.SubredditFrontPageScraper.scrape_frontpage()](subreddit_frontpage_scraper.py:1180)

- Proxy pool auto-wired (HTTP + SOCKS5)
  - use_proxy_pool=True by default.
  - switch_to_proxy_on_refused=True by default (auto-rotate to next proxy when refusal hits).
  - restore_direct_after_successes=8 by default (return to direct after 8 clean successes while on proxy).
  - Default discovery of files:
    - HTTP: config/http.proxies.json
    - SOCKS5: config/socks5.proxies.json
  - If those files exist, pool is loaded automatically even without flags. If not present, scraping proceeds direct.
  - Code: loader [python.SubredditFrontPageScraper._load_proxy_pool()](subreddit_frontpage_scraper.py:696), apply [python.SubredditFrontPageScraper._apply_proxy_change()](subreddit_frontpage_scraper.py:736), rotate [python.SubredditFrontPageScraper._switch_to_next_proxy()](subreddit_frontpage_scraper.py:784), restore [python.SubredditFrontPageScraper._maybe_restore_direct()](subreddit_frontpage_scraper.py:801)
  - Auto-enable if files exist: [python.SubredditFrontPageScraper.__init__()](subreddit_frontpage_scraper.py:162)

- Refusal detection now covers NS_ERROR_CONNECTION_REFUSED across engines
  - Code: [python.SubredditFrontPageScraper._is_connection_refused_error()](subreddit_frontpage_scraper.py:557)

CLI behavior (overrides if needed)
- Flags exist to disable/change, but you don’t need to pass any for defaults:
  - --no-traffic-refresh to disable periodic refresh
  - --traffic-refresh-interval-seconds 600 to change cadence
  - --no-use-proxy-pool to disable pool usage
  - --no-switch-to-proxy-on-refused to keep direct IP during refusal episodes
  - Files can be overridden with:
    - --proxy-pool-http-file
    - --proxy-pool-socks5-file
  - Parser defaults set accordingly in [python.__main__ argparser](subreddit_frontpage_scraper.py:1831)

Docs updated
- New section: “Traffic Pattern Refresh and Proxy Pool (New)” with defaults and examples
  - [markdown.section()](doc/Subreddit Front Page Scraper.md:1)

Result
- With no arguments, the scraper will:
  - Periodically and on-demand refresh traffic patterns.
  - Auto-detect proxy pool files under config/*.proxies.json and enable pool rotation by default.
  - Switch to a proxy automatically on refusal episodes and gently restore to direct after stable successes.

You can run:
- python subreddit_frontpage_scraper.py --subs r/aww r/funny
And get the new default behaviors without any additional flags.