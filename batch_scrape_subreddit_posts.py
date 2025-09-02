#!/usr/bin/env python3
"""
Batch Subreddit Posts + Comments Scraper

Reads existing frontpage outputs and scrapes post pages with filters using
`SubredditPostsScraper` in parallel worker processes.

Resume semantics:
  - Maintains global manifest: output/subreddits/posts_batch_manifest.json
  - Each post file existence implies completion; skipped unless --overwrite
  - Can restrict to ranked ordering or alphabetical

Ordering:
  - Default: ranked (lowest rank first) via pages (same logic as frontpage batch)
  - --order alpha for alphabetical

Concurrency:
  - Multiple processes, each maintaining its own browser instance.

Filtering / limits are passed through to underlying scraper.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from subreddit_posts_scraper import (
    SubredditPostsScraper,
    PostScrapeConfig,
    load_ranked_subs,
)

SUB_DIR = Path("output/subreddits")


def load_available_subs() -> List[str]:
    subs = []
    if SUB_DIR.exists():
        for front in SUB_DIR.glob("*/frontpage.json"):
            subs.append(front.parent.name)
    return subs


def compute_order(order: str, ranked_limit: Optional[int]) -> List[str]:
    ranked = load_ranked_subs(limit=None if ranked_limit in (0, None) else ranked_limit)
    existing = set(load_available_subs())
    # Intersect to only include those we have frontpage for
    ranked = [s for s in ranked if s in existing]
    if order == "alpha":
        return sorted(existing)
    return ranked or sorted(existing)


def posts_done(sub: str) -> int:
    pdir = SUB_DIR / sub / "posts"
    if not pdir.exists():
        return 0
    return len(list(pdir.glob("*.json")))


def save_batch_manifest(state: Dict):
    path = SUB_DIR / "posts_batch_manifest.json"
    try:
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception:
        pass


def _worker_process(
    worker_id: int,
    subs: List[str],
    cfg_dict: Dict,
    overwrite: bool,
    jitter: float,
):
    time.sleep(random.uniform(0, max(0.0, jitter)))
    cfg = PostScrapeConfig(**cfg_dict)
    scraper = SubredditPostsScraper(cfg)
    scraper._start()
    done = 0
    last_sub = ""
    try:
        for sub in subs:
            last_sub = sub
            try:
                before = posts_done(sub)
                saved = scraper.scrape_subreddit_posts(sub, overwrite=overwrite)
                after = posts_done(sub)
                delta = after - before
                print(f"[wp{worker_id}] {sub} +{delta} (total {after})")
                done += delta
            except Exception as e:
                print(f"[wp{worker_id} error] {sub}: {e}")
            # Recycle context occasionally to reduce memory / detection
            try:
                scraper._page.close()
            except Exception:
                pass
            scraper._new_context()
    finally:
        try:
            scraper._stop()
        except Exception:
            pass
    return {"worker": worker_id, "subs": len(subs), "posts": done, "last_sub": last_sub}


def main():
    ap = argparse.ArgumentParser(description="Batch scrape posts + comments across subreddits")
    ap.add_argument("--order", choices=["rank", "alpha"], default="rank")
    ap.add_argument("--ranked-limit", type=int, default=0, help="If ranked order, limit to top N (0=all)")
    ap.add_argument("--start", type=int, default=0, help="Start index in ordered list")
    ap.add_argument("--limit", type=int, default=100, help="Max subreddits this run (0=all from start)")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--overwrite", action="store_true")
    # Post-level filters
    ap.add_argument("--min-score", type=int, default=0)
    ap.add_argument("--max-age-hours", type=float, default=None)
    ap.add_argument("--allowed-types", nargs="*", default=None)
    ap.add_argument("--max-posts", type=int, default=10)
    ap.add_argument("--max-comments", type=int, default=150)
    ap.add_argument("--max-depth", type=int, default=5)
    # Infra
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    ap.add_argument("--proxy", type=str, default=os.getenv("PROXY_SERVER") or None)
    ap.add_argument("--initial-jitter-s", type=float, default=2.0)
    args = ap.parse_args()

    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass

    ordered = compute_order(args.order, args.ranked_limit if args.order == "rank" else None)
    total = len(ordered)
    if total == 0:
        print("No subreddits with frontpage data found.")
        return
    start = max(0, args.start)
    end = total if args.limit in (0, None) else min(total, start + args.limit)
    slice_subs = ordered[start:end]
    print(f"Batch posts scrape: order={args.order} range=[{start},{end}) subs={len(slice_subs)} concurrency={args.concurrency}")

    cfg = PostScrapeConfig(
        headless=args.headless,
        proxy_server=args.proxy,
        min_score=args.min_score,
        max_age_hours=args.max_age_hours,
        allowed_post_types=args.allowed_types,
        max_posts_per_subreddit=args.max_posts,
        max_comments_per_post=args.max_comments,
        max_comment_depth=args.max_depth,
    )
    cfg_dict = cfg.__dict__.copy()

    workers = max(1, min(args.concurrency, 8))
    if workers == 1:
        res = _worker_process(0, slice_subs, cfg_dict, args.overwrite, jitter=0)
        save_batch_manifest({"completed_posts": res["posts"], "last_sub": res["last_sub"], "range": [start, end], "updated_at": time.strftime('%Y-%m-%dT%H:%M:%S')})
        return

    # Round-robin split
    buckets: List[List[str]] = [[] for _ in range(workers)]
    for i, s in enumerate(slice_subs):
        buckets[i % workers].append(s)

    futures = []
    completed_posts = 0
    last_sub = ""
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for wid, subs in enumerate(buckets):
            if not subs:
                continue
            fut = ex.submit(_worker_process, wid, subs, cfg_dict, args.overwrite, float(args.initial_jitter_s))
            futures.append(fut)
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as e:
                print(f"[worker error] {e}")
                continue
            completed_posts += int(res.get("posts", 0))
            if res.get("last_sub"):
                last_sub = res["last_sub"]
            save_batch_manifest({
                "completed_posts": completed_posts,
                "last_sub": last_sub,
                "range": [start, end],
                "updated_at": time.strftime('%Y-%m-%dT%H:%M:%S')
            })

    print(f"Done. total_posts={completed_posts}")


if __name__ == "__main__":
    main()
