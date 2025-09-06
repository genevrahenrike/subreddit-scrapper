# Throughput Review and Tuning for Subreddit Front Page Scraper

Date: 2025-09-05

Overview

I reviewed the batch orchestration and front page scraper for artificial throughput gating and added safe, configurable reductions in pacing where they were limiting throughput.

Files touched

- [batch_scrape_subreddits.py](batch_scrape_subreddits.py)
- [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh)
- [doc/Subreddit Front Page Scraper.md](doc/Subreddit Front Page Scraper.md)

Key findings (gating points)

- Worker ramp-up scheduling used a main-thread sleep between starting each worker. Kept but reduced default ramp-up from 5s to 2s and kept per-worker jitter small.
- Per-item pacing inside each worker used a 0.5–1.2s sleep between subreddits. Tightened to 0.15–0.45s with CLI control.
- The frontpage loader uses conservative scroll waits (scroll_wait_ms=900) and a relatively high min_posts (50). These are now overridable from the batch runner to trade completeness for speed per your needs.
- Retry backoff, max_page_seconds, and image blocking were left as-is for reliability; they’re now exposed for easy adjustment when throughput is prioritized.

What changed

- Added CLI flags in [batch_scrape_subreddits.py](batch_scrape_subreddits.py):
  - --per-item-sleep-min, --per-item-sleep-max (default 0.15–0.45s)
  - --min-posts, --scroll-wait-ms, --max-page-seconds
  - --include-promoted / --exclude-promoted
- Propagated those overrides into worker FPConfig instances, and into the sequential code path as well.
- Reduced defaults in [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh):
  - INITIAL_JITTER_S=0.75 (was 2.0)
  - RAMP_UP_S=2.0 (was 5.0)
  - New env passthroughs: PER_ITEM_SLEEP_MIN, PER_ITEM_SLEEP_MAX, MIN_POSTS, SCROLL_WAIT_MS, MAX_PAGE_SECONDS, INCLUDE_PROMOTED
- Documentation updated in [doc/Subreddit Front Page Scraper.md](doc/Subreddit Front Page Scraper.md) to describe the new knobs and defaults.

New CLI knobs (batch)

- --per-item-sleep-min FLOAT  Minimum sleep between subreddits within a worker (default 0.15)
- --per-item-sleep-max FLOAT  Maximum sleep between subreddits within a worker (default 0.45)
- --min-posts INT             Override FPConfig.min_posts (default 50 if not overridden)
- --scroll-wait-ms INT        Override FPConfig.scroll_wait_ms (default 900 if not overridden)
- --max-page-seconds FLOAT    Override FPConfig.max_page_seconds (default 75.0 if not overridden)
- --include-promoted / --exclude-promoted

Shell wrapper passthroughs

You can set these env vars before calling [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh) and they will be forwarded automatically:

- PER_ITEM_SLEEP_MIN, PER_ITEM_SLEEP_MAX
- MIN_POSTS, SCROLL_WAIT_MS, MAX_PAGE_SECONDS
- INCLUDE_PROMOTED=true|false

Recommended starting points

For higher throughput while keeping reasonable success rates:

- Light speed-up
  - PER_ITEM_SLEEP_MIN=0.15 PER_ITEM_SLEEP_MAX=0.45
  - MIN_POSTS=35
  - SCROLL_WAIT_MS=700
  - MAX_PAGE_SECONDS=60
- Aggressive speed-up (higher risk of partial loads on slow subs/networks)
  - PER_ITEM_SLEEP_MIN=0.10 PER_ITEM_SLEEP_MAX=0.30
  - MIN_POSTS=25
  - SCROLL_WAIT_MS=600
  - MAX_PAGE_SECONDS=45

Example runs

- Two workers, faster ramp-up, mild speed-up
  - CONCURRENCY=2 RAMP_UP_S=2 INITIAL_JITTER_S=0.75 \
    PER_ITEM_SLEEP_MIN=0.15 PER_ITEM_SLEEP_MAX=0.45 \
    MIN_POSTS=35 SCROLL_WAIT_MS=700 MAX_PAGE_SECONDS=60 \
    ./scripts/run_frontpage_batch.sh --start 0 --limit 200
- Higher parallelism with overrides passed via CLI
  - ./scripts/run_frontpage_batch.sh --start 80000 --limit 1000 \
    --concurrency 6 --per-item-sleep-min 0.15 --per-item-sleep-max 0.45 \
    --min-posts 30 --scroll-wait-ms 650 --max-page-seconds 50

Trade-offs and notes

- Lower min_posts and scroll_wait_ms reduce per-subreddit dwell time but may miss late-loading posts on heavy subs or slow networks.
- Reducing max_page_seconds trims long-tail cases (good for throughput), but increases chance of “posts: []” responses on slow subs.
- Lower per-item sleep increases request rate. Keep CONCURRENCY conservative unless you have sufficient IP capacity and robust proxies.
- Keep images disabled (default) to minimize bandwidth without sacrificing metadata quality.

What I verified

- Static validation:
  - Script syntax check passed.
  - CLI help reflects new flags.
- Safe runtime behavior:
  - Worker code applies overrides only if provided; defaults remain unchanged for scraping semantics.
  - Parallel scheduler still supports ramp-up, now with lower defaults to reduce artificial gating.

Future optimizations to consider

- Page-parallelism per browser: multiple pages per browser process (careful: higher detection risk).
- Adaptive pacing: dynamically shorten sleeps when success rate is high, lengthen on error spikes.
- Smart fallbacks: reduce selector wait timeouts sooner when historical success on a sub is high.

Quick reference to gating controls in code

- Batch worker pacing and ramp-up: [batch_scrape_subreddits.py](batch_scrape_subreddits.py)
- Front page scroll pacing and target depth: [subreddit_frontpage_scraper.py](subreddit_frontpage_scraper.py)
- Shell defaults and env passthroughs: [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh)

---

Implemented throughput improvements, added tuning knobs, updated docs, and validated syntax.

What changed (throughput-impacting)
- Worker pacing and ramp-up:
  - Reduced default worker ramp-up from 5.0s to 2.0s and initial jitter from 2.0s to 0.75s in [batch_scrape_subreddits.py](batch_scrape_subreddits.py) and [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh).
  - Replaced fixed per-item worker sleep 0.5–1.2s with configurable range; defaults tightened to 0.15–0.45s:
    - New CLI: --per-item-sleep-min / --per-item-sleep-max in [batch_scrape_subreddits.py](batch_scrape_subreddits.py).
    - Script env passthrough: PER_ITEM_SLEEP_MIN / PER_ITEM_SLEEP_MAX in [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh).
- Page-load/scroll knobs exposed to batch runner:
  - Added CLI overrides to trade completeness vs speed:
    - --min-posts, --scroll-wait-ms, --max-page-seconds, --include-promoted/--exclude-promoted in [batch_scrape_subreddits.py](batch_scrape_subreddits.py).
  - These propagate into per-worker FPConfig and the sequential path so you can globally tune throughput from the batch entrypoint.
- Documentation:
  - Updated flags and defaults in [doc/Subreddit Front Page Scraper.md](doc/Subreddit Front Page Scraper.md).
  - Added a focused write-up: [doc/Throughput-Review-and-Tuning.md](doc/Throughput-Review-and-Tuning.md) with guidance, examples, and trade-offs.

Key gating now adjustable without code changes
- Per-item worker sleep: --per-item-sleep-min / --per-item-sleep-max (default 0.15–0.45s)
- Worker startup pacing: --initial-jitter-s (default 0.75), --ramp-up-s (default 2.0)
- Scroll/pagination budget: --scroll-wait-ms (default 900 if not overridden), --min-posts (default 50), --max-page-seconds (default 75)
- Promoted posts inclusion: --include-promoted / --exclude-promoted

Shell wrapper passthroughs
- In [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh): PER_ITEM_SLEEP_MIN, PER_ITEM_SLEEP_MAX, MIN_POSTS, SCROLL_WAIT_MS, MAX_PAGE_SECONDS, INCLUDE_PROMOTED (true/false), in addition to CONCURRENCY, INITIAL_JITTER_S, RAMP_UP_S.

Examples (higher throughput presets)
- Moderate speed-up:
  - CONCURRENCY=2 RAMP_UP_S=2 INITIAL_JITTER_S=0.75 \
    PER_ITEM_SLEEP_MIN=0.15 PER_ITEM_SLEEP_MAX=0.45 \
    MIN_POSTS=35 SCROLL_WAIT_MS=700 MAX_PAGE_SECONDS=60 \
    ./scripts/run_frontpage_batch.sh --start 0 --limit 200
- Aggressive speed-up (more risk of partial loads):
  - ./scripts/run_frontpage_batch.sh --start 80000 --limit 1000 \
    --concurrency 6 --per-item-sleep-min 0.15 --per-item-sleep-max 0.45 \
    --min-posts 30 --scroll-wait-ms 650 --max-page-seconds 50

Validation performed
- Static syntax and CLI validation:
  - Parsed Python successfully and confirmed CLI shows new flags for [batch_scrape_subreddits.py](batch_scrape_subreddits.py).
  - Shell script validated with bash -n and updated for macOS bash-3 compatibility in boolean env parsing.
- No change to default scraping completeness (min_posts=50 etc.) unless you override via flags; only ramp-up/jitter/per-item sleep defaults were reduced to ease artificial gating.

Notes and trade-offs
- Lowering min_posts and scroll_wait_ms increases throughput but can miss late-loading posts on heavy subs/slow networks.
- Reducing max_page_seconds trims long-tail stalls but may produce empty posts for tough subs.
- Keep CONCURRENCY conservative unless you have sufficient IP capacity; smaller per-item sleeps increase burst rate per worker.

Future optional enhancements to consider
- Expose the 15s “initial selector wait” (post container) as a config knob.
- Adaptive pacing: tighten sleep dynamically when success rates are high, ease up on spikes in errors.
- Optionally support multiple pages per browser context (higher detection risk, needs careful tuning).

Artifacts
- Implementation and CLI changes: [batch_scrape_subreddits.py](batch_scrape_subreddits.py), [scripts/run_frontpage_batch.sh](scripts/run_frontpage_batch.sh)
- Updated docs: [doc/Subreddit Front Page Scraper.md](doc/Subreddit Front Page Scraper.md)
- Review write-up: [doc/Throughput-Review-and-Tuning.md](doc/Throughput-Review-and-Tuning.md)

These changes reduce artificial gating immediately and provide explicit controls to tune throughput while preserving reliability defaults. The system is ready to run with the new defaults or with override flags/envs to push for more speed as needed.