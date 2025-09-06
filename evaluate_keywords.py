#!/usr/bin/env python3
"""
Script to evaluate keyword extraction quality by sampling diverse subreddits
and cross-checking against their source content.
"""

import json
import random
import os
from pathlib import Path

def load_subreddit_keywords(page_file, subreddit_name):
    """Load keywords for a specific subreddit from a page file."""
    try:
        with open(page_file, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                if data['name'].lower() == subreddit_name.lower():
                    return data
    except FileNotFoundError:
        print(f"File not found: {page_file}")
    return None

def get_sample_subreddits(num_samples=20):
    """Get a diverse sample of subreddits for evaluation."""
    
    # Pre-selected interesting subreddits to check from different categories
    interesting_subs = [
        "r/CX5",  # Car-specific - from docs
        "r/AskReddit",  # Q&A
        "r/funny",  # Humor
        "r/gaming",  # Gaming
        "r/programming",  # Technical
        "r/cooking",  # Hobby
        "r/personalfinance",  # Advice
        "r/worldnews",  # News
        "r/MachineLearning",  # Specialized tech
        "r/explainlikeimfive",  # Educational
        "r/DIY",  # Projects
        "r/relationships",  # Advice/social
        "r/science",  # Academic
        "r/AskHistorians",  # Academic moderated
        "r/movies",  # Entertainment
        "r/buildapc",  # Technical/specific
        "r/malefashionadvice",  # Lifestyle
        "r/photography",  # Hobby/technical
        "r/learnpython",  # Learning
        "r/dataisbeautiful"  # Data/viz
    ]
    
    return interesting_subs

def find_subreddit_in_pages(subreddit_name, base_dir):
    """Find which page contains a specific subreddit."""
    pages_dir = Path(base_dir) / "pages"
    
    # Check a few pages to find our subreddit
    for page_file in sorted(pages_dir.glob("page_*.json"))[:50]:  # Check first 50 pages
        try:
            with open(page_file, 'r') as f:
                data = json.load(f)
                for sub in data.get('subreddits', []):
                    if sub['name'].lower() == subreddit_name.lower():
                        return page_file.name, sub
        except (json.JSONDecodeError, FileNotFoundError):
            continue
    return None, None

def load_frontpage_posts(subreddit_name, base_dir):
    """Load frontpage posts for a subreddit."""
    subreddit_dir = Path(base_dir) / "subreddits" / subreddit_name.replace("r/", "")
    frontpage_file = subreddit_dir / "frontpage.json"
    
    if frontpage_file.exists():
        try:
            with open(frontpage_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return None

def evaluate_subreddit(subreddit_name, base_dir):
    """Evaluate keyword extraction for a specific subreddit."""
    print(f"\n{'='*60}")
    print(f"EVALUATING: {subreddit_name}")
    print(f"{'='*60}")
    
    # Find the subreddit in pages
    page_file, subreddit_data = find_subreddit_in_pages(subreddit_name, base_dir)
    if not page_file:
        print(f"❌ Subreddit {subreddit_name} not found in pages")
        return
    
    print(f"📄 Found in: {page_file}")
    print(f"📊 Subscribers: {subreddit_data.get('subscribers_count', 'N/A'):,}")
    print(f"📝 Description: {subreddit_data.get('description', 'N/A')[:200]}...")
    
    # Load keywords from both versions
    v22_file = Path(base_dir) / "keywords_10k_v22" / f"{page_file.replace('.json', '.keywords.jsonl')}"
    embed_file = Path(base_dir) / "keywords_10k_v22_embed" / f"{page_file.replace('.json', '.keywords.jsonl')}"
    
    v22_keywords = load_subreddit_keywords(v22_file, subreddit_name)
    embed_keywords = load_subreddit_keywords(embed_file, subreddit_name)
    
    if not v22_keywords:
        print(f"❌ No v22 keywords found for {subreddit_name}")
        return
    
    # Load frontpage posts
    frontpage_data = load_frontpage_posts(subreddit_name, base_dir)
    post_titles = []
    if frontpage_data:
        post_titles = [post.get('title', '') for post in frontpage_data.get('posts', [])][:10]
    
    print(f"\n🔍 FRONTPAGE POST TITLES (sample):")
    for i, title in enumerate(post_titles[:5], 1):
        print(f"  {i}. {title}")
    
    print(f"\n🏷️  V22 KEYWORDS (top 15):")
    for i, kw in enumerate(v22_keywords['keywords'][:15], 1):
        source_icon = {"name": "🏷️", "description": "📄", "posts": "💬", "posts_composed": "🎯", 
                      "description+name": "📄🏷️"}.get(kw['source'], "❓")
        print(f"  {i:2d}. {source_icon} {kw['term']:<30} (score: {kw['score']:.2f}, source: {kw['source']})")
    
    if embed_keywords:
        print(f"\n🧠 EMBED KEYWORDS (top 15):")
        for i, kw in enumerate(embed_keywords['keywords'][:15], 1):
            source_icon = {"name": "🏷️", "description": "📄", "posts": "💬", "posts_composed": "🎯", 
                          "description+name": "📄🏷️"}.get(kw['source'], "❓")
            print(f"  {i:2d}. {source_icon} {kw['term']:<30} (score: {kw['score']:.2f}, source: {kw['source']})")
    else:
        print(f"\n❌ No embed keywords found for {subreddit_name}")
    
    return v22_keywords, embed_keywords, frontpage_data

def main():
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    # Sample diverse subreddits
    sample_subs = get_sample_subreddits()
    
    print("🔬 KEYWORD EXTRACTION QUALITY EVALUATION")
    print("=" * 60)
    
    results = []
    for subreddit in sample_subs[:10]:  # Evaluate first 10
        try:
            result = evaluate_subreddit(subreddit, base_dir)
            if result:
                results.append((subreddit, result))
        except Exception as e:
            print(f"❌ Error evaluating {subreddit}: {e}")
    
    print(f"\n\n📋 SUMMARY")
    print("=" * 60)
    print(f"✅ Successfully evaluated {len(results)} subreddits")
    
    # Quick quality assessment
    if results:
        print(f"\n🎯 COMPOSITION ANALYSIS:")
        for subreddit, (v22_kw, embed_kw, frontpage) in results:
            if v22_kw:
                composed_count = sum(1 for kw in v22_kw['keywords'][:10] if kw['source'] == 'posts_composed')
                print(f"  {subreddit:<20} - {composed_count}/10 composed phrases in top-10")

if __name__ == "__main__":
    main()
