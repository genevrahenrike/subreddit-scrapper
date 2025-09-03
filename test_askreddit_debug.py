#!/usr/bin/env python3
"""
Simple test to debug AskReddit content preview extraction.
"""
from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig

def test_askreddit_specifically():
    """Test specifically AskReddit to debug content preview extraction."""
    print("Testing AskReddit content preview extraction...")
    
    config = FPConfig(
        headless=True,  
        min_posts=3,     # Just get a few posts for testing
        max_page_seconds=20.0,  # Shorter timeout for testing
        save_debug_html=True  # Enable debug HTML saving
    )
    
    scraper = SubredditFrontPageScraper(config)
    scraper._start()
    
    try:
        print("Scraping r/AskReddit...")
        data = scraper.scrape_frontpage("r/AskReddit")
        
        print(f"Found {len(data.get('posts', []))} posts")
        
        for i, post in enumerate(data.get("posts", [])[:5]):
            print(f"\n=== Post {i+1} ===")
            print(f"Title: {post.get('title', 'NO TITLE')}")
            print(f"Post Type: {post.get('post_type', 'UNKNOWN')}")
            print(f"Domain: {post.get('domain', 'NO DOMAIN')}")
            preview = post.get('content_preview', '')
            if preview:
                print(f"Content Preview: {preview[:200]}{'...' if len(preview) > 200 else ''}")
            else:
                print("Content Preview: [EMPTY]")
                
            # Let's also check what the content_href is
            print(f"Content Href: {post.get('content_href', 'NO HREF')}")
        
        # Also test a subreddit known to have text content
        print("\n\n=== Testing a subreddit with text content ===")
        data2 = scraper.scrape_frontpage("r/offmychest")
        
        print(f"Found {len(data2.get('posts', []))} posts in r/offmychest")
        
        for i, post in enumerate(data2.get("posts", [])[:3]):
            print(f"\n=== Post {i+1} ===")
            print(f"Title: {post.get('title', 'NO TITLE')[:80]}...")
            print(f"Post Type: {post.get('post_type', 'UNKNOWN')}")
            preview = post.get('content_preview', '')
            if preview:
                print(f"Content Preview: {preview[:200]}{'...' if len(preview) > 200 else ''}")
            else:
                print("Content Preview: [EMPTY]")
                
    finally:
        scraper._stop()

if __name__ == "__main__":
    test_askreddit_specifically()
