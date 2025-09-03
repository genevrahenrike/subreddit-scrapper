#!/usr/bin/env python3
"""
Test TIL specifically to understand the URL vs text content issue.
"""
from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig

def test_til_specifically():
    """Test TIL to understand URL vs text content in previews."""
    print("Testing r/todayilearned content preview extraction...")
    
    config = FPConfig(
        headless=True,  
        min_posts=5,     
        max_page_seconds=25.0
    )
    
    scraper = SubredditFrontPageScraper(config)
    scraper._start()
    
    try:
        print("Scraping r/todayilearned...")
        data = scraper.scrape_frontpage("r/todayilearned")
        
        print(f"Found {len(data.get('posts', []))} posts")
        
        for i, post in enumerate(data.get("posts", [])[:5]):
            print(f"\n=== Post {i+1} ===")
            print(f"Title: {post.get('title', 'NO TITLE')[:80]}...")
            print(f"Post Type: {post.get('post_type', 'UNKNOWN')}")
            print(f"Domain: {post.get('domain', 'NO DOMAIN')}")
            print(f"Content Href: {post.get('content_href', 'NO HREF')}")
            
            preview = post.get('content_preview', '')
            if preview:
                print(f"Content Preview: {preview[:150]}{'...' if len(preview) > 150 else ''}")
                # Check if the preview is just the URL
                if preview == post.get('content_href', ''):
                    print("  ^ WARNING: Content preview is just the URL!")
                elif preview.startswith(('http://', 'https://')):
                    print("  ^ WARNING: Content preview appears to be a URL!")
                else:
                    print("  ^ Good: Content preview is actual text content")
            else:
                print("Content Preview: [EMPTY]")
                
    finally:
        scraper._stop()

if __name__ == "__main__":
    test_til_specifically()
