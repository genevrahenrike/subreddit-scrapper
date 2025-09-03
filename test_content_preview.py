#!/usr/bin/env python3
"""
Test script to verify content preview extraction is working.
"""
import json
from pathlib import Path
from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig

def test_content_preview():
    """Test content preview extraction on a few subreddits."""
    print("Testing content preview extraction...")
    
    # Test with a small subset and visible browser for debugging
    config = FPConfig(
        headless=False,  # Set to True for production
        min_posts=5,     # Just get a few posts for testing
        max_page_seconds=30.0  # Shorter timeout for testing
    )
    
    test_subreddits = [
        "r/AskReddit",     # Usually has text posts
        "r/funny",         # Mix of content types
        "r/todayilearned"  # Text posts
    ]
    
    scraper = SubredditFrontPageScraper(config)
    scraper._start()
    
    try:
        for sub in test_subreddits:
            print(f"\n=== Testing {sub} ===")
            data = scraper.scrape_frontpage(sub)
            
            posts_with_preview = 0
            total_posts = len(data.get("posts", []))
            
            print(f"Total posts found: {total_posts}")
            
            for i, post in enumerate(data.get("posts", [])[:10]):  # Check first 10 posts
                title = post.get("title", "")[:60] + "..." if len(post.get("title", "")) > 60 else post.get("title", "")
                preview = post.get("content_preview", "")
                
                if preview:
                    posts_with_preview += 1
                    preview_snippet = preview[:100] + "..." if len(preview) > 100 else preview
                    print(f"  Post {i+1}: {title}")
                    print(f"    Preview: {preview_snippet}")
                else:
                    print(f"  Post {i+1}: {title} [NO PREVIEW]")
            
            print(f"\nSummary for {sub}:")
            print(f"  Posts with content preview: {posts_with_preview}/{total_posts}")
            if total_posts > 0:
                print(f"  Success rate: {posts_with_preview/total_posts*100:.1f}%")
            
            # Save the test results
            test_output_dir = Path("output/test_results")
            test_output_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_output_dir / f"{data['subreddit']}_content_preview_test.json"
            with test_file.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"  Saved test results to: {test_file}")
    
    finally:
        scraper._stop()
    
    print("\n=== Test completed ===")

if __name__ == "__main__":
    test_content_preview()
