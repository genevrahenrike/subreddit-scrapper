#!/usr/bin/env python3
"""
Resume local Playwright-based scraping from the last completed page.

Strategy:
- If output/reddit_communities_complete.json exists, load it and find max 'page'
- Else, find the highest output/reddit_communities_progress_page_<N>.json and load it
- Seed LocalRedditCommunitiesScraper with loaded data
- Continue from (max_page + 1) to 1000

Usage:
  source .venv/bin/activate
    python resume_local_scrape.py [--end 1000] [--save-every 25] [--from-page N]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple

from local_reddit_scraper import LocalRedditCommunitiesScraper, LocalScraperConfig

OUT_DIR = Path("output")
COMPLETE = OUT_DIR / "reddit_communities_complete.json"
PAGES_DIR = OUT_DIR / "pages"


def _load_json(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_all_progress() -> List[Path]:
    files = glob.glob(str(OUT_DIR / "reddit_communities_progress_page_*.json"))
    return [Path(p) for p in files]


def _max_page(data: List[Dict]) -> int:
    pages = [int(item.get("page") or 0) for item in data if isinstance(item, dict)]
    return max(pages) if pages else 0

def _best_seed() -> Tuple[List[Dict], int, Path | None]:
    """Pick the dataset with the highest max page among complete, progress files, and per-page files."""
    candidates: List[Tuple[List[Dict], int, Path | None]] = []
    if COMPLETE.exists():
        d = _load_json(COMPLETE)
        candidates.append((d, _max_page(d), COMPLETE))
    for p in _find_all_progress():
        try:
            d = _load_json(p)
            candidates.append((d, _max_page(d), p))
        except Exception:
            continue
    # Consider per-page directory
    if PAGES_DIR.exists():
        pages = sorted([int(pp.stem.split("_")[-1]) for pp in PAGES_DIR.glob("page_*.json") if pp.is_file() and pp.stem.split("_")[-1].isdigit()])
        if pages:
            # synthesize a small data structure with max page for comparison
            last_page = max(pages)
            candidates.append(([], last_page, PAGES_DIR))
    if not candidates:
        return [], 0, None
    # choose highest max_page; if tie, prefer complete.json
    candidates.sort(key=lambda x: (x[1], 1 if x[2] != COMPLETE else 2))
    return candidates[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", type=int, default=1000)
    ap.add_argument("--save-every", type=int, default=25)
    ap.add_argument("--from-page", type=int, default=None, help="Force resume from this page (overrides detection)")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    seed_data, max_seen, source = _best_seed()
    start_page = (args.from_page or (max_seen + 1 if max_seen > 0 else 1))

    print(f"Seeding from: {source if source else 'none'}")
    print(f"Max page seen: {max_seen}")
    print(f"Resuming at page: {start_page} -> {args.end}")

    if start_page > args.end:
        print("Nothing to do: already completed.")
        return

    cfg = LocalScraperConfig(headless=True)
    scraper = LocalRedditCommunitiesScraper(cfg)
    # When per-page files exist, prefer skipping already-done pages to avoid any chance of overwrite.
    done_pages = set()
    if PAGES_DIR.exists():
        for pp in PAGES_DIR.glob("page_*.json"):
            try:
                n = int(pp.stem.split("_")[-1])
                done_pages.add(n)
            except Exception:
                continue

    # Scrape only missing pages
    scraper._start()
    try:
        for p in range(start_page, args.end + 1):
            if p in done_pages:
                print(f"[resume] Skip existing page {p}")
                continue
            scraper.scrape_and_persist_page(p)
            if (p % args.save_every) == 0:
                scraper._write_manifest(last_page=p)
    finally:
        scraper._stop()

    scraper._write_manifest(last_page=args.end)

    # Execute
    scraper.scrape_all_pages(start_page=start_page, end_page=args.end, save_every=args.save_every)


if __name__ == "__main__":
    main()
