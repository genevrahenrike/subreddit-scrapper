#!/usr/bin/env python3
"""
Analyze scraping results and identify failed subreddits for retry.
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict, Counter

def analyze_results():
    """Analyze scraping results and categorize errors."""
    
    subreddits_dir = Path("output/subreddits")
    if not subreddits_dir.exists():
        print("No output/subreddits directory found")
        return
    
    stats = {
        "total": 0,
        "success": 0,
        "errors": 0,
        "no_posts": 0,
        "error_types": Counter(),
        "failed_subs": []
    }
    
    for sub_dir in subreddits_dir.iterdir():
        if not sub_dir.is_dir():
            continue
            
        frontpage_file = sub_dir / "frontpage.json"
        if not frontpage_file.exists():
            continue
            
        stats["total"] += 1
        
        try:
            with open(frontpage_file, 'r') as f:
                data = json.load(f)
                
            if data.get("error"):
                stats["errors"] += 1
                error_msg = data.get("error", "")
                
                # Categorize error types
                if "ERR_CONNECTION_REFUSED" in error_msg:
                    error_type = "CONNECTION_REFUSED"
                elif "ERR_CONNECTION_RESET" in error_msg:
                    error_type = "CONNECTION_RESET"
                elif "TimeoutError" in error_msg or "ERR_TIMED_OUT" in error_msg:
                    error_type = "TIMEOUT"
                elif "503" in error_msg:
                    error_type = "SERVICE_UNAVAILABLE"
                elif "502" in error_msg:
                    error_type = "BAD_GATEWAY"
                elif "404" in error_msg:
                    error_type = "NOT_FOUND"
                else:
                    error_type = "OTHER"
                
                stats["error_types"][error_type] += 1
                stats["failed_subs"].append({
                    "name": data.get("subreddit", sub_dir.name),
                    "error_type": error_type,
                    "error": error_msg[:200],
                    "scraped_at": data.get("scraped_at", "")
                })
                
            elif len(data.get("posts", [])) == 0:
                stats["no_posts"] += 1
                stats["failed_subs"].append({
                    "name": data.get("subreddit", sub_dir.name),
                    "error_type": "NO_POSTS",
                    "error": "No posts found",
                    "scraped_at": data.get("scraped_at", "")
                })
            else:
                stats["success"] += 1
                
        except Exception as e:
            print(f"Error reading {frontpage_file}: {e}")
            continue
    
    return stats

def generate_retry_list(stats, error_types=None, output_file="retry_subreddits.txt"):
    """Generate list of subreddits to retry."""
    
    if error_types is None:
        error_types = ["CONNECTION_REFUSED", "CONNECTION_RESET", "TIMEOUT", "SERVICE_UNAVAILABLE", "BAD_GATEWAY"]
    
    retry_subs = []
    for failed in stats["failed_subs"]:
        if failed["error_type"] in error_types:
            retry_subs.append(failed["name"])
    
    output_path = Path(output_file)
    with open(output_path, 'w') as f:
        for sub in sorted(retry_subs):
            f.write(f"r/{sub}\n")
    
    print(f"Written {len(retry_subs)} subreddits to retry to {output_path}")
    return retry_subs

def main():
    parser = argparse.ArgumentParser(description="Analyze scraping results")
    parser.add_argument("--generate-retry", action="store_true", help="Generate retry list")
    parser.add_argument("--retry-file", default="retry_subreddits.txt", help="Output file for retry list")
    parser.add_argument("--error-types", nargs="+", 
                       choices=["CONNECTION_REFUSED", "CONNECTION_RESET", "TIMEOUT", "SERVICE_UNAVAILABLE", "BAD_GATEWAY", "NO_POSTS", "OTHER"],
                       help="Error types to include in retry list")
    
    args = parser.parse_args()
    
    print("Analyzing scraping results...")
    stats = analyze_results()
    
    if stats["total"] == 0:
        print("No results found.")
        return
    
    # Print summary
    print(f"\n=== SCRAPING RESULTS SUMMARY ===")
    print(f"Total subreddits: {stats['total']:,}")
    print(f"Successful: {stats['success']:,} ({100 * stats['success'] / stats['total']:.1f}%)")
    print(f"With errors: {stats['errors']:,} ({100 * stats['errors'] / stats['total']:.1f}%)")
    print(f"No posts found: {stats['no_posts']:,} ({100 * stats['no_posts'] / stats['total']:.1f}%)")
    
    print(f"\n=== ERROR BREAKDOWN ===")
    for error_type, count in stats["error_types"].most_common():
        print(f"{error_type:20}: {count:6,} ({100 * count / stats['total']:.1f}%)")
    
    if args.generate_retry:
        retry_subs = generate_retry_list(stats, args.error_types, args.retry_file)
        print(f"\nGenerated retry list with {len(retry_subs)} subreddits")
        
        if retry_subs:
            print(f"\nTo retry these subreddits, run:")
            print(f"python subreddit_frontpage_scraper.py --file {args.retry_file}")

if __name__ == "__main__":
    main()
