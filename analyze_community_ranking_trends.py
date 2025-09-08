#!/usr/bin/env python3
"""
Community Ranking Trends Analyzer

Analyzes week-over-week changes in Reddit community rankings to identify:
- Fastest growing subreddits by subscribers
- Biggest ranking movements (up/down)
- New communities entering the rankings
- Communities that dropped out of rankings

Usage:
    python analyze_community_ranking_trends.py
    python analyze_community_ranking_trends.py --weeks 2024-W45 2024-W46
    python analyze_community_ranking_trends.py --auto-compare
"""

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from community_ranking_scraper_local import CommunityRankingScraper, LocalScraperConfig


def list_available_weeks() -> List[str]:
    """List all available weeks in the historical archive"""
    historical_dir = os.path.join("output", "historical", "community_ranking")
    if not os.path.exists(historical_dir):
        return []
    
    weeks = []
    for item in os.listdir(historical_dir):
        if item.startswith("20") and "-W" in item:
            weeks.append(item)
    
    return sorted(weeks)


def find_latest_weeks(count: int = 2) -> List[str]:
    """Find the latest N weeks of data"""
    weeks = list_available_weeks()
    
    # Include current week if data exists
    current_pages = os.path.join("output", "pages")
    if os.path.exists(current_pages) and os.listdir(current_pages):
        scraper = CommunityRankingScraper()
        current_week = scraper._get_current_week_id()
        if current_week not in weeks:
            weeks.append(current_week)
    
    return sorted(weeks, reverse=True)[:count]


def print_trend_summary(comparison: Dict):
    """Print a human-readable summary of trends"""
    summary = comparison.get("summary", {})
    
    print("\n🔍 WEEKLY COMMUNITY RANKING TRENDS")
    print("=" * 50)
    print(f"Period: {comparison['comparison_period']['previous_week']} → {comparison['comparison_period']['current_week']}")
    print(f"Total communities: {summary.get('total_previous', 0)} → {summary.get('total_current', 0)}")
    print(f"New communities: {summary.get('new_subreddits', 0)}")
    print(f"Disappeared: {summary.get('disappeared_subreddits', 0)}")
    print(f"Ranking changes: {summary.get('ranking_changes', 0)}")
    print(f"Significant subscriber changes: {summary.get('significant_subscriber_changes', 0)}")
    
    # Top ranking improvements
    ranking_changes = comparison.get("ranking_changes", [])
    if ranking_changes:
        print("\n📈 BIGGEST RANKING IMPROVEMENTS")
        print("-" * 30)
        for i, change in enumerate(ranking_changes[:10]):
            if change["rank_change"] > 0:
                print(f"{i+1:2d}. r/{change['name']} ↗️  #{change['current_rank']} (was #{change['previous_rank']}, +{change['rank_change']} positions)")
        
        print("\n📉 BIGGEST RANKING DROPS")
        print("-" * 25)
        drops = [c for c in ranking_changes if c["rank_change"] < 0]
        for i, change in enumerate(drops[:10]):
            print(f"{i+1:2d}. r/{change['name']} ↘️  #{change['current_rank']} (was #{change['previous_rank']}, {change['rank_change']} positions)")
    
    # Top subscriber growth
    subscriber_changes = comparison.get("subscriber_changes", [])
    if subscriber_changes:
        print("\n🚀 FASTEST GROWING COMMUNITIES")
        print("-" * 32)
        growth = [c for c in subscriber_changes if c["subscribers_change"] > 0]
        for i, change in enumerate(growth[:10]):
            growth_rate = change.get("growth_rate", 0)
            print(f"{i+1:2d}. r/{change['name']} +{change['subscribers_change']:,} subscribers ({growth_rate:+.1f}%) - #{change['current_rank']}")
        
        print("\n⏬ BIGGEST SUBSCRIBER LOSSES")
        print("-" * 29)
        losses = [c for c in subscriber_changes if c["subscribers_change"] < 0]
        for i, change in enumerate(losses[:10]):
            growth_rate = change.get("growth_rate", 0)
            print(f"{i+1:2d}. r/{change['name']} {change['subscribers_change']:,} subscribers ({growth_rate:.1f}%) - #{change['current_rank']}")
    
    # New communities
    new_subs = comparison.get("new_subreddits", [])
    if new_subs:
        print("\n🆕 NEW COMMUNITIES IN RANKINGS")
        print("-" * 33)
        for i, sub in enumerate(new_subs[:15]):
            desc = sub.get("description", "")[:60] + "..." if len(sub.get("description", "")) > 60 else sub.get("description", "")
            print(f"{i+1:2d}. r/{sub['name']} - #{sub['rank']} ({sub['subscribers']:,} subscribers)")
            if desc:
                print(f"    {desc}")
    
    # Disappeared communities
    disappeared = comparison.get("disappeared_subreddits", [])
    if disappeared:
        print("\n👋 COMMUNITIES NO LONGER IN TOP RANKINGS")
        print("-" * 45)
        for i, sub in enumerate(disappeared[:10]):
            print(f"{i+1:2d}. r/{sub['name']} (was #{sub['previous_rank']}, {sub['previous_subscribers']:,} subscribers)")


def main():
    parser = argparse.ArgumentParser(description="Analyze community ranking trends week-over-week")
    parser.add_argument("--weeks", nargs=2, metavar=("PREV_WEEK", "CURR_WEEK"),
                       help="Compare specific weeks (format: 2024-W45)")
    parser.add_argument("--auto-compare", action="store_true",
                       help="Auto-compare the two most recent weeks")
    parser.add_argument("--list-weeks", action="store_true",
                       help="List all available weeks")
    parser.add_argument("--generate-report", action="store_true",
                       help="Generate and save a detailed JSON report")
    
    args = parser.parse_args()
    
    if args.list_weeks:
        weeks = list_available_weeks()
        print("Available weeks in archive:")
        for week in weeks:
            print(f"  {week}")
        return
    
    scraper = CommunityRankingScraper()
    
    if args.weeks:
        prev_week, curr_week = args.weeks
        comparison = scraper.generate_weekly_comparison_report(curr_week, prev_week)
    elif args.auto_compare:
        latest_weeks = find_latest_weeks(2)
        if len(latest_weeks) < 2:
            print("❌ Need at least 2 weeks of data for comparison")
            print("Available weeks:", latest_weeks)
            return
        curr_week, prev_week = latest_weeks[0], latest_weeks[1]
        comparison = scraper.generate_weekly_comparison_report(curr_week, prev_week)
    else:
        # Default: compare current week with most recent archived week
        comparison = scraper.generate_weekly_comparison_report()
    
    if comparison:
        print_trend_summary(comparison)
        
        if args.generate_report:
            print(f"\n📄 Detailed report saved to output/reports/weekly_comparison/")
    else:
        print("❌ No comparison data available")


if __name__ == "__main__":
    main()
