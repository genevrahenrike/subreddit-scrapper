#!/usr/bin/env python3
"""
Split existing monolithic outputs into per-page files under output/pages.
This avoids re-scraping and sets up the new per-page format.

It will process:
- output/reddit_communities_complete.json (if present)
- all output/reddit_communities_progress_page_*.json

It writes:
- output/pages/page_<N>.json for each page with embedded metadata
- output/manifest.json with last_page, pages_done, total
"""
from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

OUT_DIR = Path("output")
PAGES_DIR = OUT_DIR / "pages"
COMPLETE = OUT_DIR / "reddit_communities_complete.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_page(page: int, subs: List[Dict]):
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "page": page,
        "count": len(subs),
        "subreddits": subs,
        "scraped_at": datetime.now().isoformat(),
    }
    with (PAGES_DIR / f"page_{page}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def record_manifest(pages_done: List[int], total: int, last_page: int):
    manifest = {
        "last_page": last_page,
        "pages_done": sorted(pages_done),
        "total": total,
        "updated_at": datetime.now().isoformat(),
        "format": "per-page",
        "source": "migration",
    }
    with (OUT_DIR / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    PAGES_DIR.mkdir(exist_ok=True)

    page_to_records: Dict[int, List[Dict]] = defaultdict(list)
    total = 0

    # 1) Migrate complete.json if present
    if COMPLETE.exists():
        data = load_json(COMPLETE)
        for item in data:
            p = int(item.get("page") or 0)
            if p <= 0:
                continue
            page_to_records[p].append(item)
            total += 1

    # 2) Migrate all progress files
    for path in glob.glob(str(OUT_DIR / "reddit_communities_progress_page_*.json")):
        try:
            data = load_json(Path(path))
        except Exception:
            continue
        for item in data:
            p = int(item.get("page") or 0)
            if p <= 0:
                continue
            page_to_records[p].append(item)
            total += 1

    # Write per-page files (dedup within page by community_id)
    pages_done = []
    for p, records in page_to_records.items():
        seen = set()
        subs = []
        for r in records:
            key = r.get("community_id") or (r.get("name"), r.get("url"))
            if key in seen:
                continue
            seen.add(key)
            subs.append(r)
        write_page(p, subs)
        pages_done.append(p)

    if pages_done:
        record_manifest(pages_done, total, last_page=max(pages_done))
        print(f"Migrated pages: {len(pages_done)} -> {sorted(pages_done)[:5]} ...")
    else:
        print("No pages migrated. Nothing to do.")


if __name__ == "__main__":
    main()
