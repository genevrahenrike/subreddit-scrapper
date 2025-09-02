#!/usr/bin/env python3
"""
Verify scraped subreddit outputs.
- Single JSON file OR per-page directory under output/pages
- Counts and basic field presence
- Uniqueness of community_id and (name,url)
- Simple stats on subscribers_count
"""
import json
import sys
from collections import Counter
from pathlib import Path

REQUIRED_FIELDS = [
    "community_id",
    "name",
    "url",
    "subscribers_count",
]


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def verify(path: Path):
    data = load_json(path)
    n = len(data)
    print(f"File: {path}")
    print(f"Records: {n}")

    # Field presence
    missing_counts = Counter()
    for item in data:
        for f in REQUIRED_FIELDS:
            if f not in item or item[f] in (None, ""):
                missing_counts[f] += 1
    if missing_counts:
        print("Missing/empty fields:")
        for k, v in missing_counts.items():
            print(f"  {k}: {v}")
    else:
        print("All required fields present (non-empty) for all records.")

    # Uniqueness
    cids = [item.get("community_id") for item in data]
    cid_dups = [k for k, c in Counter(cids).items() if c > 1]
    print(f"Unique community_id: {len(set(cids))} (dups: {len(cid_dups)})")

    nk = [(item.get("name"), item.get("url")) for item in data]
    nk_dups = [k for k, c in Counter(nk).items() if c > 1]
    print(f"Unique (name,url): {len(set(nk))} (dups: {len(nk_dups)})")

    # Subscriber stats
    subs = [int(item.get("subscribers_count") or 0) for item in data]
    if subs:
        print(f"Subscribers: min={min(subs):,}, max={max(subs):,}, avg={sum(subs)//len(subs):,}")

    # Sample few
    print("Sample records:")
    for s in data[:3]:
        print({k: s.get(k) for k in ["rank", "page", "name", "subscribers_count", "url"]})
    if n > 3:
        for s in data[-3:]:
            print({k: s.get(k) for k in ["rank", "page", "name", "subscribers_count", "url"]})


def _verify_pages_dir(pages_dir: Path):
    all_items = []
    pages = sorted([pp for pp in pages_dir.glob("page_*.json") if pp.is_file()])
    for pp in pages:
        try:
            data = json.load(pp.open("r", encoding="utf-8"))
            subs = data.get("subreddits", [])
            all_items.extend(subs)
        except Exception as e:
            print(f"Failed to read {pp}: {e}")
    print(f"Loaded {len(pages)} page files from {pages_dir}")
    # write a tiny summary
    verify_temp = Path("/tmp/_verify_combined.json")
    with verify_temp.open("w", encoding="utf-8") as f:
        json.dump(all_items, f)
    verify(verify_temp)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_output.py <path-to-json or pages-dir>")
        sys.exit(1)
    target = Path(sys.argv[1])
    if target.is_dir():
        _verify_pages_dir(target)
    else:
        verify(target)
