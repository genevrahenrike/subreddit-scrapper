#!/usr/bin/env python3
"""
Batch-scrape subreddit front pages using Playwright, based on per-page community outputs.

Reads: output/pages/page_<N>.json
Writes: output/subreddits/<name>/frontpage.json
Skips subreddits already scraped unless --overwrite is provided.

Respects PROXY_SERVER env for outbound proxy.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import sys
import signal
import atexit

from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig

PAGES_DIR = Path("output/pages")
SUB_DIR = Path("output/subreddits")

# Global reference to executor for cleanup
_executor = None
_workers_started = False

def _cleanup_workers():
    """Clean up any running workers on exit."""
    global _executor, _workers_started
    if _executor and _workers_started:
        print("\n[cleanup] Terminating workers...")
        try:
            _executor.shutdown(wait=False)
        except Exception:
            pass
        _workers_started = False

def _signal_handler(signum, frame):
    """Handle Ctrl+C and other signals."""
    print(f"\n[signal] Received signal {signum}, cleaning up...")
    _cleanup_workers()
    sys.exit(1)

# Register cleanup handlers
atexit.register(_cleanup_workers)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _init_worker():
    """Initialize worker process with clean environment for Playwright."""
    import asyncio
    import signal
    
    # Handle signals in worker processes - terminate cleanly on SIGINT/SIGTERM
    def worker_signal_handler(signum, frame):
        print(f"[worker-{os.getpid()}] Received signal {signum}, exiting...")
        sys.exit(1)
    
    signal.signal(signal.SIGINT, worker_signal_handler)
    signal.signal(signal.SIGTERM, worker_signal_handler)
    
    # Ensure no asyncio loop interference
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.close()
    except Exception:
        pass
    
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


def load_subs_with_rank() -> List[Tuple[str, int]]:
    """Return list of (subreddit_name, min_rank_seen) across all ranking pages.
    If rank missing, default to a large sentinel for stable ordering.
    """
    best_rank: Dict[str, int] = {}
    if not PAGES_DIR.exists():
        return []
    for pp in sorted(PAGES_DIR.glob("page_*.json")):
        try:
            data = json.load(pp.open("r", encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("subreddits", []):
            nm = canonical_sub_name(item.get("name") or "") or canonical_sub_name(item.get("url") or "")
            if not nm:
                continue
            r = item.get("rank")
            try:
                r = int(r) if r is not None else None
            except Exception:
                r = None
            cur = best_rank.get(nm)
            if r is None:
                # if we never saw a rank for this sub, set a large sentinel only if missing
                if cur is None:
                    best_rank[nm] = 10**12
            else:
                best_rank[nm] = min(cur, r) if cur is not None else r
    # Convert to list
    items = list(best_rank.items())
    return items


def canonical_sub_name(name_or_url: str) -> str:
    s = (name_or_url or "").strip()
    if not s:
        return ""
    # strip url pieces
    if s.startswith("http"):
        # expect .../r/<name>/...
        parts = s.split("/r/")
        if len(parts) > 1:
            s = parts[1]
    s = s.strip("/")
    if s.startswith("r/"):
        s = s[2:]
    # subreddit names are typically lowercase; normalize
    return s


def already_scraped(name: str, skip_failed: bool = True) -> bool:
    """Check if subreddit already scraped successfully."""
    frontpage_file = SUB_DIR / name / "frontpage.json"
    if not frontpage_file.exists():
        return False
    
    if not skip_failed:
        # Old behavior: skip if file exists regardless of content
        return True
    
    try:
        with open(frontpage_file, 'r') as f:
            data = json.load(f)
        # Consider it scraped ONLY if no error (regardless of posts count)
        return not data.get("error")
    except Exception:
        # If we can't read the file, consider it not scraped
        return False


def save_manifest(done: int, total: int, last_index: int, last_name: str):
    manifest = {
        "done": done,
        "total": total,
        "last_index": last_index,
        "last_name": last_name,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    SUB_DIR.mkdir(parents=True, exist_ok=True)
    with (SUB_DIR / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def _worker_process(
    worker_id: int,
    targets: List[Tuple[int, str]],
    chunk_size: int,
    overwrite: bool,
    proxy: Optional[str],
    jitter_s: float,
    skip_failed: bool = True,
    multi_profile: bool = False,
    persistent_session: bool = False,
    browser_engine: str = "chromium",
    user_data_dir: Optional[str] = None,
    per_item_sleep_min: float = 0.15,
    per_item_sleep_max: float = 0.45,
    min_posts_override: Optional[int] = None,
    scroll_wait_ms_override: Optional[int] = None,
    max_page_seconds_override: Optional[float] = None,
    include_promoted_override: Optional[bool] = None,
    adaptive_chunking: bool = False,
    min_chunk_size: int = 5,
):
    """Worker that processes a list of (index, subreddit) sequentially with one
    browser per chunk, returning stats for progress tracking.

    Returns a dict: { 'worker_id': int, 'done': int, 'last_index': int, 'last_name': str, 'errors': int }
    """
    import asyncio
    
    print(f"[w{worker_id}] Starting worker with {len(targets)} targets")
    
    # Ensure clean asyncio environment in worker process to prevent Playwright conflicts
    try:
        # Close any existing event loop that might exist
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.close()
    except Exception:
        pass
    
    # Set a new event loop for this worker
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
    
    # Light stagger so workers don't slam at once
    try:
        time.sleep(random.uniform(0, max(0.0, float(jitter_s))))
    except Exception:
        pass

    cfg = FPConfig(
        headless=True,
        proxy_server=proxy,
        multi_profile=multi_profile,
        persistent_session=persistent_session,
        browser_engine=browser_engine,
        user_data_dir=user_data_dir,
        worker_id=worker_id,  # Add worker ID for profile isolation
    )
    # Apply FPConfig overrides if provided
    try:
        if min_posts_override is not None:
            cfg.min_posts = int(min_posts_override)
        if scroll_wait_ms_override is not None:
            cfg.scroll_wait_ms = int(scroll_wait_ms_override)
        if max_page_seconds_override is not None:
            cfg.max_page_seconds = float(max_page_seconds_override)
        if include_promoted_override is not None:
            cfg.include_promoted = bool(include_promoted_override)
    except Exception:
        pass
    done = 0
    errors = 0
    last_index = -1
    last_name = ""
    scraper = None

    # Process in chunks to periodically recycle the browser/context
    total_targets = len(targets)
    processed_count = 0
    
    # Adaptive chunking: use smaller chunks for workers with fewer items
    if adaptive_chunking and total_targets > 0:
        # For workers with fewer items, use smaller chunks to reduce browser recycling overhead
        if total_targets <= chunk_size:
            # Single chunk for small workloads
            effective_chunk_size = total_targets
        elif total_targets <= chunk_size * 2:
            # Split into 2-3 smaller chunks for medium workloads
            effective_chunk_size = max(min_chunk_size, total_targets // 2)
        else:
            # Use standard chunking for large workloads
            effective_chunk_size = chunk_size
        
        print(f"[w{worker_id}] Adaptive chunking: {total_targets} items, using chunk size {effective_chunk_size} (standard: {chunk_size})")
    else:
        effective_chunk_size = chunk_size
    
    for start in range(0, len(targets), max(1, int(effective_chunk_size))):
        batch = targets[start : start + effective_chunk_size]
        remaining = total_targets - processed_count
        
        # Attempt to create scraper with retries for this chunk
        chunk_retries = 2
        for retry in range(chunk_retries):
            try:
                if scraper:
                    try:
                        scraper._stop()
                    except Exception:
                        pass
                    scraper = None
                
                scraper = SubredditFrontPageScraper(cfg)
                scraper._start()
                chunk_num = start // effective_chunk_size + 1
                total_chunks = (total_targets + effective_chunk_size - 1) // effective_chunk_size
                print(f"[w{worker_id}] Started scraper for chunk {chunk_num}/{total_chunks}, processing items {start+1}-{min(start+len(batch), total_targets)} of {total_targets} (remaining: {remaining})")
                break
                
            except Exception as e:
                error_msg = str(e)[:100]
                if retry < chunk_retries - 1:
                    print(f"[w{worker_id}] Scraper start failed (retry {retry + 1}/{chunk_retries}): {error_msg}")
                    time.sleep(2.0 * (retry + 1))  # Exponential backoff
                else:
                    print(f"[w{worker_id}] Scraper start failed permanently: {error_msg}")
                    # Return partial results even if we can't finish
                    return {
                        "worker_id": worker_id,
                        "done": done,
                        "errors": errors + 1,
                        "last_index": last_index,
                        "last_name": last_name,
                        "fatal_error": error_msg,
                    }
        
        if not scraper:
            print(f"[w{worker_id}] Could not create scraper, aborting worker")
            break
            
        # Process this chunk
        try:
            for batch_idx, (idx, name) in enumerate(batch):
                try:
                    if (not overwrite) and already_scraped(name, skip_failed):
                        print(f"[w{worker_id} skip] {name}")
                        processed_count += 1
                        continue
                    data = scraper.scrape_frontpage(name)
                    scraper.save_frontpage(data["subreddit"], data)
                    done += 1
                    processed_count += 1
                    last_index = idx
                    last_name = name
                    posts_n = len(data.get("posts", []))
                    
                    # Enhanced progress tracking with remaining count
                    remaining_in_worker = total_targets - processed_count
                    
                    # Enhanced error logging
                    if data.get("error"):
                        errors += 1
                        error_msg = data.get("error", "")
                        if "ERR_CONNECTION_REFUSED" in error_msg or "ERR_CONNECTION_RESET" in error_msg:
                            print(f"[w{worker_id} conn-error] {name} idx={idx} posts={posts_n} remaining={remaining_in_worker} error={error_msg[:100]}...")
                        elif "TimeoutError" in error_msg or "ERR_TIMED_OUT" in error_msg:
                            print(f"[w{worker_id} timeout] {name} idx={idx} posts={posts_n} remaining={remaining_in_worker} error={error_msg[:100]}...")
                        else:
                            print(f"[w{worker_id} error] {name} idx={idx} posts={posts_n} remaining={remaining_in_worker} error={error_msg[:100]}...")
                    else:
                        print(f"[w{worker_id} saved] {name} idx={idx} posts={posts_n} remaining={remaining_in_worker}")
                    
                    # gentle pacing per worker
                    time.sleep(random.uniform(per_item_sleep_min, per_item_sleep_max))
                except Exception as e:
                    errors += 1
                    processed_count += 1
                    print(f"[w{worker_id} exception] {name} idx={idx} - {str(e)[:100]}")
                    # Best-effort: continue to next subreddit in this worker
                    continue
        except Exception as e:
            print(f"[w{worker_id} chunk-error] Failed processing chunk {start}-{start+len(batch)}: {str(e)[:100]}")
            errors += 1
        finally:
            if scraper:
                try:
                    scraper._stop()
                except Exception as e:
                    print(f"[w{worker_id} cleanup-error] {str(e)[:50]}")

    print(f"[w{worker_id}] Worker completed: done={done}, errors={errors}")
    return {
        "worker_id": worker_id,
        "done": done,
        "errors": errors,
        "last_index": last_index,
        "last_name": last_name,
    }


def main():
    """
    Enhanced batch scraper with intelligent work allocation and load balancing.
    
    Improvements for "last leg" problem:
    1. Pre-filtering: Only allocate unprocessed items to workers
    2. Smart allocation: Use interleaved distribution for large workloads, 
       block allocation for small sweep-ups
    3. Adaptive chunking: Smaller chunks for workers with fewer items
    4. Progress tracking: Show remaining work count for better visibility
    5. Work imbalance detection: Warn when load distribution is poor
    6. Auto-adaptive for retries: Enable adaptive chunking for failed worker recovery
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0, help="Start index in the unique subreddit list")
    ap.add_argument("--limit", type=int, default=200, help="Max subreddits to process this run (0 for all)")
    ap.add_argument("--chunk-size", type=int, default=50, help="Restart browser after this many subreddits")
    ap.add_argument("--adaptive-chunking", action="store_true", help="Use smaller chunks for workers with fewer items (better load balancing)")
    ap.add_argument("--min-chunk-size", type=int, default=5, help="Minimum chunk size when using adaptive chunking")
    ap.add_argument("--overwrite", action="store_true", help="Re-scrape even if frontpage.json exists")
    ap.add_argument("--order", choices=["rank", "alpha"], default="rank", help="Ordering of subreddits: by original rank or alphabetically")
    ap.add_argument("--concurrency", type=int, default=2, help="Number of parallel browser processes (safe: 1-3)")
    ap.add_argument("--max-workers", type=int, default=12, help="Maximum number of workers allowed (safety cap)")
    ap.add_argument("--initial-jitter-s", type=float, default=0.75, help="Max random stagger per worker at start (seconds)")
    ap.add_argument("--ramp-up-s", type=float, default=2.0, help="Ramp-up period to gradually start workers (seconds)")
    ap.add_argument("--per-item-sleep-min", type=float, default=0.15, help="Minimum sleep between subreddits within a worker (seconds)")
    ap.add_argument("--per-item-sleep-max", type=float, default=0.45, help="Maximum sleep between subreddits within a worker (seconds)")
    ap.add_argument("--skip-failed", action="store_true", default=True, help="Only skip successfully scraped subreddits (default)")
    ap.add_argument("--skip-all", dest="skip_failed", action="store_false", help="Skip any existing output files, even failed ones")
    ap.add_argument("--file", type=str, help="File containing list of subreddit names (one per line)")
    ap.add_argument("--retry-failed-workers", action="store_true", help="Automatically retry from all failed worker files")
    
    # Browser fingerprinting and profile options
    ap.add_argument("--browser-engine", choices=["chromium", "webkit", "firefox"], default="chromium",
                    help="Browser engine to use (default: chromium)")
    ap.add_argument("--persistent-session", action="store_true",
                    help="Use persistent browser session with cookies and cache")
    ap.add_argument("--multi-profile", action="store_true",
                    help="Rotate between different browser profiles for better fingerprint diversity")
    ap.add_argument("--user-data-dir", type=str,
                    help="Custom directory for persistent browser user data")

    # Throughput tuning (forwarded to FPConfig where applicable)
    ap.add_argument("--min-posts", type=int, default=None, help="Override target number of posts to load before stopping")
    ap.add_argument("--scroll-wait-ms", type=int, default=None, help="Override wait after each scroll (ms)")
    ap.add_argument("--max-page-seconds", type=float, default=None, help="Override per-page time budget (seconds)")
    ap.add_argument("--include-promoted", dest="include_promoted", action="store_true", help="Include promoted/ad posts")
    ap.add_argument("--exclude-promoted", dest="include_promoted", action="store_false", help="Exclude promoted/ad posts")
    ap.set_defaults(include_promoted=None)

    args = ap.parse_args()

    # Safer for Playwright + multiprocessing on macOS/Linux
    # Force spawn method to avoid asyncio conflicts
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        # Start method already set by parent; that's okay
        pass

    pairs = load_subs_with_rank()
    if args.order == "rank":
        # Sort by min rank asc; if sentinel present, they go to the end
        pairs.sort(key=lambda x: (x[1], x[0].lower()))
    else:
        pairs.sort(key=lambda x: x[0].lower())
    subs = [name for name, _ in pairs]
    
        # Handle different input sources
    if args.retry_failed_workers:
        # Load from failed worker files
        print("Loading targets from failed worker files...")
        failed_files = list(Path().glob("output/subreddits/failed_worker_*_targets.json"))
        if not failed_files:
            print("No failed worker files found.")
            return
        
        retry_targets = []
        for file_path in failed_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                targets_list = data.get("unfinished_targets", [])
                retry_targets.extend([item["subreddit"] for item in targets_list])
                print(f"Loaded {len(targets_list)} targets from {file_path}")
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
        
        # Remove duplicates and use for processing
        subs = list(set(retry_targets))
        print(f"Total unique retry targets: {len(subs)}")
        
        # Auto-enable adaptive chunking for retry runs (usually smaller, fragmented workloads)
        if not args.adaptive_chunking:
            print("[batch] Auto-enabling adaptive chunking for retry run")
            args.adaptive_chunking = True
        
    elif args.file:
        # Load from specified file
        try:
            with open(args.file, 'r') as f:
                subs = [line.strip() for line in f if line.strip()]
            print(f"Loaded {len(subs)} subreddits from {args.file}")
        except Exception as e:
            print(f"Error reading file {args.file}: {e}")
            return
    
    total = len(subs)
    if total == 0:
        print("No subreddits found to process")
        return
    # Apply start/limit only for ranked processing (not for file/retry modes)
    if not args.file and not args.retry_failed_workers:
        start = max(0, args.start)
        end = total if args.limit in (0, None) else min(total, start + args.limit)
        print(f"Total unique subs: {total}. Processing range [{start}, {end})")
        subs = subs[start:end]
    else:
        start = 0
        end = len(subs)
        if args.retry_failed_workers:
            print(f"Processing {end} failed worker retry targets")
        else:
            print(f"Processing {end} targets from file")

    proxy = os.getenv("PROXY_SERVER") or None

    # Prepare targets with indices for progress tracking and uniqueness already ensured
    if args.file or args.retry_failed_workers:
        # For file/retry mode, create simple sequential indices
        targets = [(i, subs[i]) for i in range(len(subs))]
    else:
        # For ranked mode, use original indices for tracking
        targets = [(start + i, subs[i]) for i in range(len(subs))]
    if args.concurrency <= 1:
        # Preserve original sequential behavior
        cfg = FPConfig(
            headless=True,
            proxy_server=proxy,
            multi_profile=args.multi_profile,
            persistent_session=args.persistent_session,
            browser_engine=args.browser_engine,
            user_data_dir=args.user_data_dir,
            worker_id=0,  # Single worker gets ID 0
        )
        # Apply FPConfig overrides from CLI if provided
        try:
            if args.min_posts is not None:
                cfg.min_posts = int(args.min_posts)
            if args.scroll_wait_ms is not None:
                cfg.scroll_wait_ms = int(args.scroll_wait_ms)
            if args.max_page_seconds is not None:
                cfg.max_page_seconds = float(args.max_page_seconds)
            if args.include_promoted is not None:
                cfg.include_promoted = bool(args.include_promoted)
        except Exception:
            pass
        scraper = SubredditFrontPageScraper(cfg)
        idx = start
        done = 0
        while idx < end:
            chunk_end = min(end, idx + args.chunk_size)
            print(f"[batch] Chunk {idx}..{chunk_end-1}")
            scraper._start()
            try:
                for i in range(idx, chunk_end):
                    name = subs[i]
                    if not args.overwrite and already_scraped(name, args.skip_failed):
                        print(f"[skip] {name} (exists)")
                        continue
                    data = scraper.scrape_frontpage(name)
                    scraper.save_frontpage(data["subreddit"], data)
                    done += 1
                    save_manifest(done, total, i, name)
                    time.sleep(random.uniform(args.per_item_sleep_min, args.per_item_sleep_max))
            finally:
                scraper._stop()
            idx = chunk_end
        print("[batch] Completed.")
        return

    # Parallel: intelligently allocate work based on what actually needs processing
    workers = max(1, int(args.concurrency))
    max_workers_cap = args.max_workers  # The cap from argument
    if workers > max_workers_cap:
        print(f"[batch] Warning: Requested {workers} workers exceeds safety cap of {max_workers_cap}, using {max_workers_cap}")
        workers = max_workers_cap
    elif workers > 8:
        print(f"[batch] Warning: Using {workers} workers (>8). Monitor system resources and network limits.")
    
    # Filter targets to only include those that actually need processing
    # This prevents workers from getting mostly-completed slices
    unprocessed_targets = []
    skipped_count = 0
    for idx, name in targets:
        if args.overwrite or not already_scraped(name, args.skip_failed):
            unprocessed_targets.append((idx, name))
        else:
            skipped_count += 1
    
    print(f"[batch] Pre-filtering: {len(unprocessed_targets)} need processing, {skipped_count} already complete")
    
    if not unprocessed_targets:
        print("[batch] All targets already processed. Use --overwrite to re-process.")
        return
    
    # Use more balanced allocation strategies based on remaining work
    slices: List[List[Tuple[int, str]]] = [[] for _ in range(workers)]
    
    if len(unprocessed_targets) >= workers * 2:
        # For larger workloads: use interleaved allocation for better load balancing
        # This spreads both "easy" and "hard" targets across workers more evenly
        for n, item in enumerate(unprocessed_targets):
            slices[n % workers].append(item)
    else:
        # For smaller workloads (sweep-ups): use block allocation to minimize overhead
        # Fewer chunks means less browser recycling and setup overhead
        chunk_size = len(unprocessed_targets) // workers
        remainder = len(unprocessed_targets) % workers
        
        start_idx = 0
        for w in range(workers):
            # Give earlier workers one extra item from remainder to balance load
            worker_chunk_size = chunk_size + (1 if w < remainder else 0)
            if worker_chunk_size > 0:
                slices[w] = unprocessed_targets[start_idx:start_idx + worker_chunk_size]
                start_idx += worker_chunk_size

    print(f"[batch] Parallel start: workers={workers}, unprocessed={len(unprocessed_targets)}, chunk-size={args.chunk_size}, ramp-up={args.ramp_up_s}s, sleep=[{args.per_item_sleep_min},{args.per_item_sleep_max}]s")
    
    # Show workload distribution for transparency
    active_workers = [i for i, sl in enumerate(slices) if sl]
    if active_workers:
        workload_summary = ", ".join([f"w{i}:{len(slices[i])}" for i in active_workers])
        print(f"[batch] Workload distribution: {workload_summary}")
    
    # Track progress as futures complete
    done_total = 0
    failed_workers = []
    successful_workers = []
    futures = []
    future_to_worker = {}  # Map futures to worker info for better error tracking
    completed_workers = []  # Track which workers have finished
    active_futures = set()  # Track active futures for work rebalancing
    
    # Implement ramp-up phase: gradually start workers over the ramp-up period
    worker_start_times = []
    if workers > 1 and args.ramp_up_s > 0:
        # Distribute worker starts evenly across the ramp-up period
        # For faster ramp-up: use shorter intervals and calculate delays more efficiently
        ramp_interval = args.ramp_up_s / max(1, workers - 1) if workers > 1 else 0
        for i in range(workers):
            start_delay = min(i * ramp_interval, args.ramp_up_s)  # Cap at ramp_up_s
            worker_start_times.append(start_delay)
        print(f"[batch] Worker ramp-up schedule: {[f'{i:.1f}s' for i in worker_start_times]}")
    else:
        # No ramp-up, start all immediately (but still with jitter)
        worker_start_times = [0.0] * workers
    
    start_time = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as ex:
        global _executor, _workers_started
        _executor = ex
        _workers_started = True
        
        try:
            for wid, sl in enumerate(slices):
                if not sl:
                    continue
                
                # Calculate and apply ramp-up delay more efficiently
                target_start_time = start_time + worker_start_times[wid]
                current_time = time.time()
                delay_needed = max(0, target_start_time - current_time)
                
                if delay_needed > 0:
                    print(f"[batch] Scheduling worker {wid} to start in {delay_needed:.1f}s")
                    time.sleep(delay_needed)
                
                fut = ex.submit(
                    _worker_process,
                    wid,
                    sl,
                    args.chunk_size,
                    args.overwrite,
                    proxy,
                    float(args.initial_jitter_s),
                    args.skip_failed,
                    args.multi_profile,
                    args.persistent_session,
                    args.browser_engine,
                    args.user_data_dir,
                    args.per_item_sleep_min,
                    args.per_item_sleep_max,
                    args.min_posts,
                    args.scroll_wait_ms,
                    args.max_page_seconds,
                    args.include_promoted,
                    args.adaptive_chunking,
                    args.min_chunk_size,
                )
                futures.append(fut)
                future_to_worker[fut] = {"worker_id": wid, "targets": sl}
                active_futures.add(fut)

            # Track remaining work for potential rebalancing
            remaining_work = dict(future_to_worker)  # Copy for tracking
            
            for fut in as_completed(futures):
                active_futures.discard(fut)  # Remove completed future
                worker_info = future_to_worker.get(fut, {})
                worker_id = worker_info.get("worker_id", "unknown")
                worker_targets = worker_info.get("targets", [])
                
                try:
                    res = fut.result()
                    # Worker completed successfully
                    successful_workers.append(worker_id)
                    completed_workers.append(worker_id)
                    done_total += int(res.get("done", 0))
                    error_count = res.get("errors", 0)
                    last_i = int(res.get("last_index", -1))
                    last_n = str(res.get("last_name", ""))
                    if last_i >= 0 and last_n:
                        save_manifest(done_total, total, last_i, last_n)
                    
                    # Check if we should trigger work rebalancing for remaining workers
                    remaining_futures = len(active_futures)
                    if remaining_futures > 0 and remaining_futures <= len(completed_workers):
                        # More workers have completed than are still running - potential rebalancing opportunity
                        estimated_remaining = sum(len(remaining_work.get(af, {}).get("targets", [])) for af in active_futures)
                        if estimated_remaining > remaining_futures * 20:  # Threshold: >20 items per remaining worker
                            print(f"[batch] Work imbalance detected: ~{estimated_remaining} items for {remaining_futures} workers")
                            print(f"[batch] Consider using smaller chunks or more workers for better load distribution")
                    
                    status = f"completed: done={res.get('done',0)}, errors={error_count}"
                    if res.get("fatal_error"):
                        status += f", fatal_error={res.get('fatal_error')[:50]}..."
                    print(f"[worker {worker_id}] {status}, last={last_n}#{last_i}")
                    
                except Exception as e:
                    # Worker failed catastrophically
                    failed_workers.append(worker_id)
                    error_msg = str(e)[:200]  # Truncate very long error messages
                    print(f"[worker-error] Worker {worker_id} failed catastrophically: {error_msg}")
                    
                    # Save the failed targets for potential retry
                    if worker_targets and len(worker_targets) > 0:
                        unfinished_count = len(worker_targets)
                        print(f"[worker-recovery] Worker {worker_id} had {unfinished_count} unfinished subreddits")
                        
                        try:
                            failed_targets_file = SUB_DIR / f"failed_worker_{worker_id}_targets.json"
                            SUB_DIR.mkdir(parents=True, exist_ok=True)
                            with open(failed_targets_file, 'w') as f:
                                json.dump({
                                    "worker_id": worker_id,
                                    "error": error_msg,
                                    "failed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "unfinished_targets": [{"index": idx, "subreddit": name} for idx, name in worker_targets]
                                }, f, indent=2)
                            print(f"[worker-recovery] Saved failed targets to {failed_targets_file}")
                        except Exception as save_error:
                            print(f"[worker-recovery] Could not save failed targets: {save_error}")
                    
                    continue
        
        except KeyboardInterrupt:
            print("\n[interrupt] Keyboard interrupt received, shutting down workers...")
            _cleanup_workers()
            raise
        except Exception as e:
            print(f"\n[error] Unexpected error: {e}")
            _cleanup_workers()
            raise
        finally:
            _workers_started = False

    # Summary of worker performance
    total_workers = len(successful_workers) + len(failed_workers)
    if total_workers > 0:
        success_rate = len(successful_workers) / total_workers * 100
        print(f"[batch] Worker summary: {len(successful_workers)}/{total_workers} successful ({success_rate:.1f}%)")
        if failed_workers:
            print(f"[batch] Failed workers: {failed_workers}")
            print(f"[batch] Check output/subreddits/failed_worker_*_targets.json for recovery options")
    
    print("[batch] Parallel completed.")


if __name__ == "__main__":
    main()
