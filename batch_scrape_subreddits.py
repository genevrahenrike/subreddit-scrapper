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
from typing import Dict, List, Set, Tuple

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0, help="Start index in the unique subreddit list")
    ap.add_argument("--limit", type=int, default=200, help="Max subreddits to process this run (0 for all)")
    ap.add_argument("--chunk-size", type=int, default=50, help="Restart browser after this many subreddits")
    ap.add_argument("--overwrite", action="store_true", help="Re-scrape even if frontpage.json exists")
    ap.add_argument("--order", choices=["rank", "alpha"], default="rank", help="Ordering of subreddits: by original rank or alphabetically")
    args = ap.parse_args()

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

    cfg = FPConfig(headless=True, proxy_server=os.getenv("PROXY_SERVER") or None)
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


if __name__ == "__main__":
    main()
