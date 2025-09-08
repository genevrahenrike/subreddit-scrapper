#!/usr/bin/env python3
"""
Quick parser test for discovery_scraper_local using an existing saved HTML.
Validates the parsing logic without needing to actually scrape pages.
"""

import os
from discovery_scraper_local import CommunityRankingScraper


def test_parse_saved_html():
    sample_path = os.path.join("output", "reddit_page_500.html")
    if not os.path.exists(sample_path):
        print("No saved HTML found at output/reddit_page_500.html; skipping.")
        return

    with open(sample_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Initialize scraper (no browser needed for parsing)
    scraper = CommunityRankingScraper()
    subs = scraper.parse_subreddit_data(html, page_number=500)
    print(f"Parsed {len(subs)} communities from saved HTML")
    if subs[:3]:
        for s in subs[:3]:
            print({k: s[k] for k in ["name", "subscribers_count", "url"]})


if __name__ == "__main__":
    test_parse_saved_html()
