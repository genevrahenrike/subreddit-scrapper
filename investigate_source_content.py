#!/usr/bin/env python3
"""
Cross-check specific keyword issues with their source frontpage content.
This will help understand the root causes of quality problems.
"""

import json
import glob
from pathlib import Path

def check_source_content(issue_term, subreddit_name, expected_content_pattern=None):
    """Find and analyze the source content that generated problematic keywords."""
    
    # Find the subreddit's frontpage file
    frontpage_pattern = f"/Users/markzhu/Git/subreddit-scrapper/output/subreddits/{subreddit_name}/frontpage.json"
    
    try:
        with open(frontpage_pattern, 'r') as f:
            frontpage_data = json.load(f)
            
        print(f"\n🔍 SOURCE ANALYSIS: {subreddit_name} -> '{issue_term}'")
        print("="*60)
        
        # Look for posts that might have generated this term
        matching_posts = []
        for post in frontpage_data.get('posts', []):
            title = post.get('title', '').lower()
            if any(word in title for word in issue_term.lower().split()):
                matching_posts.append(post)
        
        if matching_posts:
            print(f"Found {len(matching_posts)} potentially relevant posts:")
            for i, post in enumerate(matching_posts[:5]):  # Show top 5
                score = post.get('score', 0)
                comments = post.get('num_comments', 0)
                title = post.get('title', '')
                print(f"\n  Post {i+1}: (score: {score}, comments: {comments})")
                print(f"    Title: \"{title}\"")
                
                # Check if this might be promotional content
                if any(promo in title.lower() for promo in [
                    'season 3', 'only in theaters', 'marvel rivals', 
                    'store.steampowered', 'nintendo.com'
                ]):
                    print(f"    ⚠️  PROMOTIONAL CONTENT DETECTED")
                
                # Check for URL fragments
                if any(tech in title.lower() for tech in [
                    'http', '.com', 'steampowered', 'www.'
                ]):
                    print(f"    ⚠️  TECHNICAL ARTIFACTS DETECTED")
                    
        else:
            print("No directly matching posts found. Checking for partial matches...")
            # Try broader search
            term_words = issue_term.lower().split()
            for word in term_words:
                if len(word) > 3:  # Skip short words
                    partial_matches = []
                    for post in frontpage_data.get('posts', []):
                        title = post.get('title', '').lower()
                        if word in title:
                            partial_matches.append(post)
                    
                    if partial_matches:
                        print(f"\n  Found {len(partial_matches)} posts containing '{word}':")
                        for post in partial_matches[:3]:
                            print(f"    \"{post.get('title', '')}\" (score: {post.get('score', 0)})")
        
        return True
        
    except FileNotFoundError:
        print(f"❌ Frontpage not found for {subreddit_name}")
        print(f"   Looked for: {frontpage_pattern}")
        return False
    except Exception as e:
        print(f"❌ Error analyzing {subreddit_name}: {e}")
        return False

def investigate_specific_cases():
    """Investigate specific problematic cases identified in the analysis."""
    
    cases_to_investigate = [
        # Word repetition cases
        ("r/funny", "surviving surströmming surströmming"),
        
        # Mechanical composition
        ("r/funny", "funny happens die black"),
        ("r/worldnews", "World News enemies hit"),
        
        # Promotional content
        ("r/gaming", "nintendo com store"),
        ("r/worldnews", "marvel rivals season"),
        
        # Technical artifacts
        ("r/gaming", "https store steampowered"),
        
    ]
    
    print("DETAILED SOURCE CONTENT INVESTIGATION")
    print("="*80)
    
    for subreddit, term in cases_to_investigate:
        success = check_source_content(term, subreddit)
        if not success:
            print(f"Skipping {subreddit} due to access issues")

if __name__ == "__main__":
    investigate_specific_cases()
