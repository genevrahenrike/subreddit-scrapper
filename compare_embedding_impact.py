#!/usr/bin/env python3
"""
Compare embedding vs non-embedding results to see impact on quality issues.
"""

import json
from pathlib import Path
import re
from collections import defaultdict

def load_subreddit_keywords(file_path, subreddit_name):
    """Load keywords for a specific subreddit from a JSONL file."""
    with open(file_path, 'r') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                if data['name'] == subreddit_name:
                    return data['keywords']
    return None

def analyze_embedding_impact():
    """Compare specific problematic cases between v22 and v22_embed."""
    
    test_cases = [
        ("r/funny", "page_1"),
        ("r/worldnews", "page_1"), 
        ("r/gaming", "page_1"),
    ]
    
    print("EMBEDDING IMPACT ANALYSIS")
    print("="*60)
    
    for subreddit, page in test_cases:
        print(f"\n🔍 ANALYZING: {subreddit}")
        
        # Load both versions
        v22_path = f"/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22/{page}.keywords.jsonl"
        embed_path = f"/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22_embed/{page}.keywords.jsonl"
        
        v22_keywords = load_subreddit_keywords(v22_path, subreddit)
        embed_keywords = load_subreddit_keywords(embed_path, subreddit)
        
        if not v22_keywords or not embed_keywords:
            print(f"  ❌ Could not load keywords for {subreddit}")
            continue
        
        # Extract top-15 terms for comparison
        v22_terms = [kw['term'] for kw in v22_keywords[:15]]
        embed_terms = [kw['term'] for kw in embed_keywords[:15]]
        
        print(f"\n  📊 TOP-15 COMPARISON:")
        
        # Check for quality issues in both
        v22_issues = count_quality_issues(v22_terms)
        embed_issues = count_quality_issues(embed_terms)
        
        print(f"    V22 issues: {v22_issues}")
        print(f"    Embed issues: {embed_issues}")
        print(f"    Improvement: {v22_issues - embed_issues} issues reduced")
        
        # Show specific problematic terms
        v22_problems = identify_problem_terms(v22_terms)
        embed_problems = identify_problem_terms(embed_terms)
        
        if v22_problems:
            print(f"\n    V22 problem terms:")
            for term in v22_problems[:3]:
                print(f"      • \"{term}\"")
        
        if embed_problems:
            print(f"\n    Embed problem terms:")
            for term in embed_problems[:3]:
                print(f"      • \"{term}\"")
        
        # Check if specific bad terms were filtered
        specific_checks = [
            "surviving surströmming surströmming",
            "funny happens die black", 
            "World News enemies hit",
            "marvel rivals season",
            "https store steampowered"
        ]
        
        for check_term in specific_checks:
            in_v22 = check_term in v22_terms
            in_embed = check_term in embed_terms
            
            if in_v22 and not in_embed:
                print(f"    ✅ Filtered out: \"{check_term}\"")
            elif in_v22 and in_embed:
                print(f"    ⚠️  Still present: \"{check_term}\"")

def count_quality_issues(terms):
    """Count various quality issues in a list of terms."""
    issues = 0
    
    for term in terms:
        # Word repetition
        words = term.lower().split()
        if len(set(words)) < len(words):
            issues += 1
            continue
            
        # Mechanical composition
        if any(pattern in term.lower() for pattern in [
            'happens die', 'enemies hit', 'artwork dentist'
        ]):
            issues += 1
            continue
            
        # Promotional content
        if any(pattern in term.lower() for pattern in [
            'marvel rivals', 'season 3', 'nintendo com', 'steampowered'
        ]):
            issues += 1
            continue
            
        # Technical artifacts
        if re.search(r'https?://|\.com|[0-9a-f]{8}', term.lower()):
            issues += 1
            continue
    
    return issues

def identify_problem_terms(terms):
    """Identify specific problematic terms."""
    problems = []
    
    for term in terms:
        # Word repetition
        words = term.lower().split()
        if len(set(words)) < len(words):
            problems.append(term)
            continue
            
        # Mechanical composition
        if any(pattern in term.lower() for pattern in [
            'happens die', 'enemies hit', 'artwork dentist', 'splash evil'
        ]):
            problems.append(term)
            continue
            
        # Promotional content
        if any(pattern in term.lower() for pattern in [
            'marvel rivals', 'season 3', 'nintendo com', 'steampowered'
        ]):
            problems.append(term)
            continue
    
    return problems

if __name__ == "__main__":
    analyze_embedding_impact()
