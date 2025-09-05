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

from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig

PAGES_DIR = Path("output/pages")
SUB_DIR = Path("output/subreddits")


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


def already_scraped(name: str) -> bool:
    return (SUB_DIR / name / "frontpage.json").exists()


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
):
    """Worker that processes a list of (index, subreddit) sequentially with one
    browser per chunk, returning stats for progress tracking.

    Returns a dict: { 'worker_id': int, 'done': int, 'last_index': int, 'last_name': str }
    """
    # Light stagger so workers don't slam at once
    try:
        time.sleep(random.uniform(0, max(0.0, float(jitter_s))))
    except Exception:
        pass

    cfg = FPConfig(headless=True, proxy_server=proxy)
    done = 0
    last_index = -1
    last_name = ""

    # Process in chunks to periodically recycle the browser/context
    for start in range(0, len(targets), max(1, int(chunk_size))):
        batch = targets[start : start + chunk_size]
        scraper = SubredditFrontPageScraper(cfg)
        scraper._start()
        try:
            for idx, name in batch:
                try:
                    if (not overwrite) and already_scraped(name):
                        print(f"[w{worker_id} skip] {name}")
                        continue
                    data = scraper.scrape_frontpage(name)
                    scraper.save_frontpage(data["subreddit"], data)
                    done += 1
                    last_index = idx
                    last_name = name
                    posts_n = len(data.get("posts", []))
                    
                    # Enhanced error logging
                    if data.get("error"):
                        error_msg = data.get("error", "")
                        if "ERR_CONNECTION_REFUSED" in error_msg or "ERR_CONNECTION_RESET" in error_msg:
                            print(f"[w{worker_id} conn-error] {name} idx={idx} posts={posts_n} error={error_msg[:100]}...")
                        elif "TimeoutError" in error_msg or "ERR_TIMED_OUT" in error_msg:
                            print(f"[w{worker_id} timeout] {name} idx={idx} posts={posts_n} error={error_msg[:100]}...")
                        else:
                            print(f"[w{worker_id} error] {name} idx={idx} posts={posts_n} error={error_msg[:100]}...")
                    else:
                        print(f"[w{worker_id} saved] {name} idx={idx} posts={posts_n}")
                    
                    # gentle pacing per worker
                    time.sleep(random.uniform(0.5, 1.2))
                except Exception as e:
                    print(f"[w{worker_id} exception] {name} idx={idx} - {str(e)[:100]}")
                    # Best-effort: continue to next subreddit in this worker
                    continue
        finally:
            try:
                scraper._stop()
            except Exception:
                pass

    return {
        "worker_id": worker_id,
        "done": done,
        "last_index": last_index,
        "last_name": last_name,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0, help="Start index in the unique subreddit list")
    ap.add_argument("--limit", type=int, default=200, help="Max subreddits to process this run (0 for all)")
    ap.add_argument("--chunk-size", type=int, default=50, help="Restart browser after this many subreddits")
    ap.add_argument("--overwrite", action="store_true", help="Re-scrape even if frontpage.json exists")
    ap.add_argument("--order", choices=["rank", "alpha"], default="rank", help="Ordering of subreddits: by original rank or alphabetically")
    ap.add_argument("--concurrency", type=int, default=2, help="Number of parallel browser processes (safe: 1-3)")
    ap.add_argument("--initial-jitter-s", type=float, default=2.0, help="Max random stagger per worker at start (seconds)")
    args = ap.parse_args()

    # Safer for Playwright + multiprocessing on macOS/Linux
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
    total = len(subs)
    if total == 0:
        print("No subreddits found in output/pages")
        return
    start = max(0, args.start)
    end = total if args.limit in (0, None) else min(total, start + args.limit)
    print(f"Total unique subs: {total}. Processing range [{start}, {end})")

    proxy = os.getenv("PROXY_SERVER") or None

    # Prepare targets with indices for progress tracking and uniqueness already ensured
    targets = [(i, subs[i]) for i in range(start, end)]
    if args.concurrency <= 1:
        # Preserve original sequential behavior
        cfg = FPConfig(headless=True, proxy_server=proxy)
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
                    if not args.overwrite and already_scraped(name):
                        print(f"[skip] {name} (exists)")
                        continue
                    data = scraper.scrape_frontpage(name)
                    scraper.save_frontpage(data["subreddit"], data)
                    done += 1
                    save_manifest(done, total, i, name)
                    time.sleep(random.uniform(0.5, 1.2))
            finally:
                scraper._stop()
            idx = chunk_end
        print("[batch] Completed.")
        return

    # Parallel: split targets into roughly even round-robin slices per worker
    workers = max(1, int(args.concurrency))
    if workers > 8:
        workers = 8  # guardrail
    slices: List[List[Tuple[int, str]]] = [[] for _ in range(workers)]
    for n, item in enumerate(targets):
        slices[n % workers].append(item)

    print(f"[batch] Parallel start: workers={workers}, range=[{start}, {end}), chunk-size={args.chunk_size}")
    # Track progress as futures complete
    done_total = 0
    futures = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for wid, sl in enumerate(slices):
            if not sl:
                continue
            fut = ex.submit(
                _worker_process,
                wid,
                sl,
                args.chunk_size,
                args.overwrite,
                proxy,
                float(args.initial_jitter_s),
            )
            futures.append(fut)

        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                print(f"[worker-error] {e}")
                continue
            done_total += int(res.get("done", 0))
            last_i = int(res.get("last_index", -1))
            last_n = str(res.get("last_name", ""))
            if last_i >= 0 and last_n:
                save_manifest(done_total, total, last_i, last_n)
            print(f"[worker {res.get('worker_id')}] done={res.get('done',0)} last={last_n}#{last_i}")

    print("[batch] Parallel completed.")


if __name__ == "__main__":
    main()
