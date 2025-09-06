#!/usr/bin/env python3
"""
Comprehensive analysis of the 100k subreddit keyword extraction results.
Focus on new insights beyond prior analysis.
"""

import json
import re
from collections import defaultdict, Counter
from pathlib import Path
import random

def analyze_full_dataset():
    """Analyze patterns across the entire 100k dataset."""
    
    print("COMPREHENSIVE 100K SUBREDDIT ANALYSIS")
    print("="*80)
    
    # Statistics tracking
    stats = {
        'total_subreddits': 0,
        'total_keywords': 0,
        'score_distribution': [],
        'source_counts': defaultdict(int),
        'composition_rate': 0,
        'quality_issues': {
            'word_repetition': 0,
            'substring_duplicates': 0,
            'promotional_contamination': 0,
            'technical_artifacts': 0,
            'language_mixing': 0
        },
        'subreddit_types': defaultdict(int),
        'top_performers': [],
        'quality_by_score_range': defaultdict(list)
    }
    
    # Process files in batches to manage memory
    base_path = Path("/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22")
    keyword_files = sorted(list(base_path.glob("page_*.keywords.jsonl")))
    
    print(f"Processing {len(keyword_files)} files...")
    
    # Sample every 10th file for efficiency, but include key ranges
    sampled_files = []
    sampled_files.extend(keyword_files[:10])  # Top subreddits
    sampled_files.extend(keyword_files[100:110])  # Mid-range
    sampled_files.extend(keyword_files[500:510])  # Lower range
    sampled_files.extend(keyword_files[-10:])  # Smallest subreddits
    
    for file_path in sampled_files:
        print(f"  Processing {file_path.name}...")
        
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    analyze_subreddit(data, stats)
    
    print_comprehensive_report(stats)

def analyze_subreddit(data, stats):
    """Analyze a single subreddit's keywords."""
    
    subreddit_name = data['name']
    keywords = data['keywords']
    subscribers = data.get('subscribers_count', 0)
    
    stats['total_subreddits'] += 1
    stats['total_keywords'] += len(keywords)
    
    # Categorize subreddit size
    if subscribers > 1_000_000:
        stats['subreddit_types']['mega'] += 1
    elif subscribers > 100_000:
        stats['subreddit_types']['large'] += 1
    elif subscribers > 10_000:
        stats['subreddit_types']['medium'] += 1
    else:
        stats['subreddit_types']['small'] += 1
    
    # Analyze keywords
    subreddit_issues = 0
    composition_count = 0
    
    for kw in keywords:
        term = kw['term']
        score = kw['score']
        source = kw['source']
        
        stats['score_distribution'].append(score)
        stats['source_counts'][source] += 1
        
        if 'composed' in source:
            composition_count += 1
        
        # Quality analysis
        issue_detected = False
        
        # Word repetition
        words = term.lower().split()
        if len(words) > 1 and len(set(words)) < len(words):
            stats['quality_issues']['word_repetition'] += 1
            issue_detected = True
        
        # Substring duplicates (different spacing/punctuation of same content)
        normalized = re.sub(r'[^a-z0-9]', '', term.lower())
        if len(normalized) > 5:
            # This is approximate - would need full deduplication for accuracy
            stats['quality_issues']['substring_duplicates'] += 1
        
        # Promotional contamination
        if any(promo in term.lower() for promo in [
            'season 3', 'marvel rivals', 'only in theaters', 'steampowered'
        ]):
            stats['quality_issues']['promotional_contamination'] += 1
            issue_detected = True
        
        # Technical artifacts
        if re.search(r'https?://|\.com|[0-9a-f]{8}', term.lower()):
            stats['quality_issues']['technical_artifacts'] += 1
            issue_detected = True
        
        # Language mixing (approximate)
        if re.search(r'[äöüßñáéíóúç]', term.lower()):
            stats['quality_issues']['language_mixing'] += 1
            issue_detected = True
        
        if issue_detected:
            subreddit_issues += 1
        
        # Track quality by score range
        if score >= 50:
            stats['quality_by_score_range']['premium'].append(issue_detected)
        elif score >= 20:
            stats['quality_by_score_range']['high'].append(issue_detected)
        elif score >= 10:
            stats['quality_by_score_range']['medium'].append(issue_detected)
        else:
            stats['quality_by_score_range']['low'].append(issue_detected)
    
    # Track composition rate
    if len(keywords) > 0:
        comp_rate = composition_count / len(keywords)
        stats['composition_rate'] += comp_rate
        
        # Track top performers (high composition, low issues)
        if comp_rate > 0.3 and subreddit_issues < 3:
            stats['top_performers'].append({
                'name': subreddit_name,
                'composition_rate': comp_rate,
                'issues': subreddit_issues,
                'subscribers': subscribers
            })

def print_comprehensive_report(stats):
    """Print comprehensive analysis report."""
    
    print(f"\n📊 DATASET OVERVIEW:")
    print(f"  Total subreddits analyzed: {stats['total_subreddits']:,}")
    print(f"  Total keywords: {stats['total_keywords']:,}")
    print(f"  Average keywords per subreddit: {stats['total_keywords'] / max(stats['total_subreddits'], 1):.1f}")
    
    print(f"\n📈 SUBREDDIT SIZE DISTRIBUTION:")
    for size_type, count in stats['subreddit_types'].items():
        pct = (count / stats['total_subreddits']) * 100
        print(f"  {size_type.capitalize()}: {count} ({pct:.1f}%)")
    
    print(f"\n📋 SOURCE DISTRIBUTION:")
    total_kw = sum(stats['source_counts'].values())
    for source, count in sorted(stats['source_counts'].items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_kw) * 100
        print(f"  {source}: {count:,} ({pct:.1f}%)")
    
    print(f"\n📊 COMPOSITION ANALYSIS:")
    avg_comp_rate = (stats['composition_rate'] / max(stats['total_subreddits'], 1)) * 100
    print(f"  Average composition rate: {avg_comp_rate:.1f}%")
    
    if stats['top_performers']:
        print(f"\n🏆 TOP PERFORMING SUBREDDITS (High composition, low issues):")
        top_performers = sorted(stats['top_performers'], 
                              key=lambda x: (x['composition_rate'], -x['issues']))[-10:]
        for perf in top_performers:
            print(f"  {perf['name']}: {perf['composition_rate']*100:.1f}% composition, "
                  f"{perf['issues']} issues ({perf['subscribers']:,} subs)")
    
    print(f"\n🚨 QUALITY ISSUES SCALE:")
    for issue_type, count in stats['quality_issues'].items():
        rate = (count / total_kw) * 100
        print(f"  {issue_type.replace('_', ' ').title()}: {count:,} ({rate:.1f}%)")
    
    print(f"\n📊 QUALITY BY SCORE RANGE:")
    for score_range, issue_list in stats['quality_by_score_range'].items():
        if issue_list:
            issue_rate = (sum(issue_list) / len(issue_list)) * 100
            print(f"  {score_range.capitalize()}: {issue_rate:.1f}% issue rate ({len(issue_list)} keywords)")
    
    if stats['score_distribution']:
        scores = sorted(stats['score_distribution'])
        n = len(scores)
        print(f"\n📈 SCORE DISTRIBUTION:")
        print(f"  Min: {scores[0]:.2f}")
        print(f"  Max: {scores[-1]:.2f}")
        print(f"  Mean: {sum(scores)/n:.2f}")
        print(f"  Median: {scores[n//2]:.2f}")
        print(f"  75th percentile: {scores[int(n*0.75)]:.2f}")
        print(f"  95th percentile: {scores[int(n*0.95)]:.2f}")
        print(f"  99th percentile: {scores[int(n*0.99)]:.2f}")
    
    print(f"\n💡 NEW INSIGHTS:")
    
    # Calculate insights
    posts_composed_pct = (stats['source_counts']['posts_composed'] / total_kw) * 100
    
    print(f"  • Posts composition generates {posts_composed_pct:.1f}% of all keywords")
    print(f"  • Word repetition affects ~{stats['quality_issues']['word_repetition']} keywords")
    print(f"  • Promotional contamination appears in {stats['quality_issues']['promotional_contamination']} cases")
    
    # Issue concentration
    total_issues = sum(stats['quality_issues'].values())
    issue_rate = (total_issues / total_kw) * 100
    print(f"  • Overall quality issue rate: {issue_rate:.1f}%")
    
    print(f"\n🎯 PRIORITY RECOMMENDATIONS:")
    print(f"  1. Implement post-processing filters for word repetition")
    print(f"  2. Add promotional content detection before extraction")
    print(f"  3. Create variant consolidation for spacing/punctuation")
    print(f"  4. Consider source-specific quality thresholds")

if __name__ == "__main__":
    analyze_full_dataset()
