#!/usr/bin/env python3
"""
analyze_discovery_trends.py

Week-over-week (WoW) trend analysis for Reddit community ranking discovery outputs.

This CLI compares the current week's discovery results in "output/pages/"
against a selected previous week archived under:
  - output/historical/community_ranking/YYYY-WW/

It produces a JSON report under:
  - output/reports/weekly_comparison/{PREV}_to_{CURR}.json

Primary usage:
  - Auto-compare (latest archived week → current pages):
      python3 analyze_discovery_trends.py --auto-compare

  - Compare specific weeks:
      python3 analyze_discovery_trends.py --weeks 2024-W45 2024-W46

  - List available archived weeks:
      python3 analyze_discovery_trends.py --list-weeks
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

# We rely on discovery_scraper_local.CommunityRankingScraper for robust loading + comparison
try:
    from discovery_scraper_local import CommunityRankingScraper  # type: ignore
except Exception as e:  # pragma: no cover
    CommunityRankingScraper = None  # type: ignore


HISTORICAL_ROOT = Path("output") / "historical" / "community_ranking"
CURRENT_PAGES_DIR = Path("output") / "pages"
REPORTS_DIR = Path("output") / "reports" / "weekly_comparison"


def _iso_week_id(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def list_available_weeks() -> List[str]:
    if not HISTORICAL_ROOT.exists():
        return []
    weeks = []
    for child in HISTORICAL_ROOT.iterdir():
        if child.is_dir():
            name = child.name
            # basic validation: "YYYY-WWW"
            if len(name) == 8 and name[4] == "-" and name[5] == "W" and name[:4].isdigit() and name[6:8].isdigit():
                weeks.append(name)
    weeks.sort()
    return weeks


def get_latest_two_weeks() -> Tuple[Optional[str], Optional[str]]:
    weeks = list_available_weeks()
    if not weeks:
        return None, None
    if len(weeks) == 1:
        return weeks[-1], None
    return weeks[-2], weeks[-1]


def compare_weeks(previous_week: str, current_week: Optional[str]) -> dict:
    if CommunityRankingScraper is None:
        raise RuntimeError("discovery_scraper_local.CommunityRankingScraper is not importable. Ensure the repository is intact and dependencies are installed.")

    scraper = CommunityRankingScraper()
    # When current_week is None, the scraper will compute it itself from the system clock.
    return scraper.generate_weekly_comparison_report(current_week=current_week, previous_week=previous_week)


def auto_compare() -> Tuple[Optional[str], Optional[str], dict]:
    """
    Compare the latest archived week → current pages.
    Returns (previous_week, current_week, report_dict).
    """
    prev, _ = get_latest_two_weeks()
    if not prev:
        print("❌ No archived weeks found in output/historical/community_ranking")
        return None, None, {}
    current_week = _iso_week_id(datetime.now(timezone.utc))
    report = compare_weeks(prev, current_week)
    return prev, current_week, report


def main():
    ap = argparse.ArgumentParser(description="Week-over-week trend analysis for discovery outputs")
    ap.add_argument("--list-weeks", action="store_true", help="List available archived week IDs")
    ap.add_argument("--auto-compare", action="store_true", help="Compare latest archived week to current pages")
    ap.add_argument("--weeks", nargs=2, metavar=("PREVIOUS_WEEK", "CURRENT_WEEK"), help="Compare specific weeks, e.g. 2024-W45 2024-W46")
    ap.add_argument("--report-path", type=str, default="", help="Optional explicit report output path (.json). Default uses reports/weekly_comparison/")
    args = ap.parse_args()

    if args.list_weeks:
        weeks = list_available_weeks()
        if not weeks:
            print("No archived weeks found.")
            return
        print("Archived weeks:")
        for w in weeks:
            print(f"  - {w}")
        return

    if args.weeks:
        previous_week, current_week = args.weeks
        print(f"📊 Comparing archived week → current: {previous_week} → {current_week}")
        try:
            report = compare_weeks(previous_week, current_week)
        except Exception as e:
            print(f"❌ Failed to generate comparison: {e}")
            return
    elif args.auto_compare:
        print("📊 Auto-comparing latest archived week to current pages...")
        previous_week, current_week, report = auto_compare()
        if not report:
            return
    else:
        # If no action specified, default to auto-compare to be user-friendly
        print("📊 No mode selected, defaulting to --auto-compare")
        previous_week, current_week, report = auto_compare()
        if not report:
            return

    # Persist report path if requested override, else rely on internal writer in CommunityRankingScraper
    # The underlying generate_weekly_comparison_report already writes to:
    # output/reports/weekly_comparison/{previous}_to_{current}.json
    # Here we only handle custom --report-path
    if args.report_path:
        try:
            out_path = Path(args.report_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"📄 Custom comparison report saved to {out_path}")
        except Exception as e:
            print(f"⚠️ Warning: Failed to write custom report path: {e}")

    # Print a compact summary
    summary = report.get("summary", {})
    comp = report.get("comparison_period", {})
    print("")
    print("==== WoW Summary ====")
    print(f"Previous week: {comp.get('previous_week', previous_week)}")
    print(f"Current week : {comp.get('current_week', current_week)}")
    print(f"Total subs (prev → curr): {summary.get('total_previous', 0)} → {summary.get('total_current', 0)}")
    print(f"New subreddits: {summary.get('new_subreddits', 0)}")
    print(f"Disappeared subreddits: {summary.get('disappeared_subreddits', 0)}")
    print(f"Ranking changes: {summary.get('ranking_changes', 0)}")
    print(f"Significant subscriber changes: {summary.get('significant_subscriber_changes', 0)}")


if __name__ == "__main__":
    main()