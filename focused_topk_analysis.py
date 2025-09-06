#!/usr/bin/env python3
"""
Targeted Analysis for TopK Optimization and Quality Patterns

This script focuses specifically on answering:
1. Is topK=40 optimal or should we go higher/lower?
2. What are the quality patterns at different score ranges?
3. Are there clear quality tiers we can use for filtering?
"""

import json
import glob
import random
import numpy as np
from collections import defaultdict, Counter
from pathlib import Path
import sys
import re

def analyze_score_quality_patterns(data, score_ranges=None):
    """Deep dive into score-based quality patterns."""
    if score_ranges is None:
        score_ranges = [(0, 5), (5, 10), (10, 20), (20, 50), (50, float('inf'))]
    
    print("\n=== SCORE-BASED QUALITY ANALYSIS ===")
    
    # Collect all keywords with their scores and positions
    all_keywords = []
    for item in data:
        subreddit = item['subreddit']
        for i, kw in enumerate(item['keywords']):
            all_keywords.append({
                'subreddit': subreddit,
                'term': kw.get('term', ''),
                'score': kw.get('score', 0),
                'weight': kw.get('weight', 0),
                'source': kw.get('source', ''),
                'rank': i + 1
            })
    
    print(f"Analyzing {len(all_keywords):,} keywords across {len(data)} subreddits")
    
    # Analyze by score ranges
    for min_score, max_score in score_ranges:
        range_keywords = [kw for kw in all_keywords 
                         if min_score <= kw['score'] < max_score]
        
        if not range_keywords:
            continue
            
        print(f"\nScore Range {min_score}-{max_score if max_score != float('inf') else '∞'}:")
        print(f"  Count: {len(range_keywords):,} ({len(range_keywords)/len(all_keywords)*100:.1f}%)")
        
        # Source distribution in this range
        source_dist = Counter(kw['source'] for kw in range_keywords)
        top_sources = source_dist.most_common(3)
        print(f"  Top sources: {', '.join([f'{s}({c})' for s, c in top_sources])}")
        
        # Average rank in this score range
        avg_rank = np.mean([kw['rank'] for kw in range_keywords])
        print(f"  Average rank: {avg_rank:.1f}")
        
        # Sample keywords in this range
        sample_keywords = random.sample(range_keywords, min(5, len(range_keywords)))
        print(f"  Sample keywords:")
        for kw in sample_keywords:
            print(f"    {kw['term'][:50]:<50} (r/{kw['subreddit']}, rank {kw['rank']}, score {kw['score']:.1f})")
    
    return all_keywords

def analyze_rank_degradation_patterns(data):
    """Analyze quality degradation by rank to find optimal cutoff."""
    print("\n=== RANK DEGRADATION ANALYSIS ===")
    
    # Group keywords by rank across all subreddits
    rank_scores = defaultdict(list)
    rank_sources = defaultdict(Counter)
    
    for item in data:
        for i, kw in enumerate(item['keywords']):
            rank = i + 1
            score = kw.get('score', 0)
            source = kw.get('source', '')
            
            rank_scores[rank].append(score)
            rank_sources[rank][source] += 1
    
    # Calculate degradation metrics
    print("Rank-by-rank analysis:")
    print(f"{'Rank':<5} {'Count':<6} {'Mean':<8} {'Median':<8} {'Drop%':<8} {'Top Source':<20}")
    print("-" * 70)
    
    previous_mean = None
    quality_drops = []
    
    for rank in sorted(rank_scores.keys())[:40]:  # Focus on top 40
        scores = rank_scores[rank]
        if len(scores) < 10:  # Skip ranks with too few data points
            continue
            
        mean_score = np.mean(scores)
        median_score = np.median(scores)
        top_source = rank_sources[rank].most_common(1)[0][0] if rank_sources[rank] else 'none'
        
        drop_pct = ""
        if previous_mean is not None and previous_mean > 0:
            drop = (previous_mean - mean_score) / previous_mean * 100
            drop_pct = f"{drop:.1f}%"
            quality_drops.append((rank, drop))
        
        print(f"{rank:<5} {len(scores):<6} {mean_score:<8.2f} {median_score:<8.2f} {drop_pct:<8} {top_source[:19]:<20}")
        previous_mean = mean_score
    
    # Identify steepest drops
    quality_drops.sort(key=lambda x: x[1], reverse=True)
    print(f"\nSteepest quality drops:")
    for rank, drop in quality_drops[:5]:
        print(f"  Rank {rank}: {drop:.1f}% drop from previous rank")
    
    # Recommend cutoff points
    significant_drops = [rank for rank, drop in quality_drops if drop > 15]
    print(f"\nPotential cutoff points (>15% drop): {significant_drops[:5]}")
    
    return quality_drops

def analyze_composition_quality(data, sample_size=200):
    """Deep dive into composed keyword quality."""
    print("\n=== COMPOSITION QUALITY ANALYSIS ===")
    
    composed_keywords = []
    for item in data:
        subreddit = item['subreddit']
        for i, kw in enumerate(item['keywords']):
            if 'composed' in kw.get('source', ''):
                composed_keywords.append({
                    'subreddit': subreddit,
                    'term': kw.get('term', ''),
                    'score': kw.get('score', 0),
                    'rank': i + 1,
                    'source': kw.get('source', '')
                })
    
    print(f"Found {len(composed_keywords):,} composed keywords")
    
    if not composed_keywords:
        print("No composed keywords found.")
        return
    
    # Score distribution of composed keywords
    scores = [kw['score'] for kw in composed_keywords]
    print(f"Composed keyword scores:")
    print(f"  Mean: {np.mean(scores):.2f}")
    print(f"  Median: {np.median(scores):.2f}")
    print(f"  Range: {min(scores):.2f} - {max(scores):.2f}")
    
    # Quality patterns in composed keywords
    print(f"\nComposed keyword quality assessment:")
    
    # Sample for manual quality assessment
    sample = random.sample(composed_keywords, min(sample_size, len(composed_keywords)))
    
    quality_categories = {
        'high_quality': [],  # Coherent, meaningful phrases
        'medium_quality': [], # Understandable but mechanical
        'low_quality': [],   # Fragmented or nonsensical
        'promotional': []    # Spam/promotional content
    }
    
    # Simple heuristics for quality assessment
    for kw in sample:
        term = kw['term'].lower()
        words = term.split()
        
        # Quality indicators
        has_repetition = len(words) != len(set(words))
        has_brand_context = any(brand in term for brand in ['reddit', 'ask', 'gaming', 'funny'])
        has_promotional = any(promo in term for promo in ['buy', 'sale', 'deal', 'promo', 'discount'])
        is_fragmented = len(words) > 3 and len([w for w in words if len(w) > 2]) < len(words) * 0.6
        
        if has_promotional:
            quality_categories['promotional'].append(kw)
        elif has_repetition or is_fragmented:
            quality_categories['low_quality'].append(kw)
        elif has_brand_context and len(words) >= 3:
            quality_categories['high_quality'].append(kw)
        else:
            quality_categories['medium_quality'].append(kw)
    
    for category, keywords in quality_categories.items():
        pct = len(keywords) / len(sample) * 100
        print(f"  {category.replace('_', ' ').title()}: {pct:.1f}% ({len(keywords)} of {len(sample)})")
        if keywords:
            print(f"    Examples: {', '.join([kw['term'][:30] for kw in keywords[:3]])}")
    
    return quality_categories

def recommend_topk_optimization(degradation_data, composition_data, dataset_stats):
    """Provide specific topK recommendations based on analysis."""
    print("\n=== TOPK OPTIMIZATION RECOMMENDATIONS ===")
    
    current_topk = 40
    hit_limit_pct = dataset_stats.get('hit_limit_pct', 0)
    
    print(f"Current topK: {current_topk}")
    print(f"Subreddits hitting limit: {hit_limit_pct:.1f}%")
    
    # Find first major quality cliff
    major_cliffs = [rank for rank, drop in degradation_data if drop > 20]
    
    recommendations = []
    
    if hit_limit_pct > 90:  # Most subreddits hit the limit
        if major_cliffs and major_cliffs[0] > current_topk:
            # There's a quality cliff beyond current limit
            new_topk = min(major_cliffs[0] - 2, 60)  # Don't go crazy high
            recommendations.append({
                'action': 'INCREASE',
                'new_topk': new_topk,
                'reason': f'{hit_limit_pct:.1f}% hit limit, quality cliff at rank {major_cliffs[0]}',
                'priority': 'HIGH'
            })
        else:
            # No major cliff, moderate increase
            recommendations.append({
                'action': 'INCREASE',
                'new_topk': 50,
                'reason': f'{hit_limit_pct:.1f}% hit limit, no major quality cliff detected',
                'priority': 'MEDIUM'
            })
    
    elif hit_limit_pct < 50:  # Few subreddits hit the limit
        if major_cliffs and major_cliffs[0] < current_topk:
            # There's a quality cliff before current limit
            new_topk = max(major_cliffs[0] - 2, 20)  # Don't go too low
            recommendations.append({
                'action': 'DECREASE',
                'new_topk': new_topk,
                'reason': f'Only {hit_limit_pct:.1f}% hit limit, quality cliff at rank {major_cliffs[0]}',
                'priority': 'MEDIUM'
            })
    
    # Quality-based filtering recommendations
    if composition_data:
        low_quality_pct = len(composition_data.get('low_quality', []))
        promotional_pct = len(composition_data.get('promotional', []))
        total_sample = sum(len(v) for v in composition_data.values())
        
        if total_sample > 0:
            low_q_rate = low_quality_pct / total_sample
            promo_rate = promotional_pct / total_sample
            
            if low_q_rate > 0.3:  # >30% low quality
                recommendations.append({
                    'action': 'ADD_QUALITY_FILTER',
                    'filter_type': 'composition_quality',
                    'reason': f'{low_q_rate*100:.1f}% of composed keywords are low quality',
                    'priority': 'HIGH'
                })
            
            if promo_rate > 0.1:  # >10% promotional
                recommendations.append({
                    'action': 'ADD_SPAM_FILTER',
                    'filter_type': 'promotional_content',
                    'reason': f'{promo_rate*100:.1f}% of keywords appear promotional',
                    'priority': 'HIGH'
                })
    
    print(f"Generated {len(recommendations)} recommendations:")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec['action']} [{rec['priority']}]")
        if 'new_topk' in rec:
            print(f"   Recommended topK: {rec['new_topk']}")
        print(f"   Reason: {rec['reason']}")
    
    return recommendations

def main():
    keyword_dir = "output/keywords_10k_v22"
    
    print(f"=== FOCUSED TOPK & QUALITY ANALYSIS ===")
    print(f"Dataset: {keyword_dir}")
    
    # Load larger sample for better statistical power
    all_files = list(glob.glob(f"{keyword_dir}/page_*.keywords.jsonl"))
    print(f"Found {len(all_files)} page files")
    
    # Sample 500 pages (about 30-40% of dataset) for robust analysis
    sampled_files = random.sample(all_files, min(500, len(all_files)))
    
    data = []
    for page_file in sampled_files:
        try:
            with open(page_file, 'r') as f:
                for line in f:
                    try:
                        item = json.loads(line.strip())
                        data.append({
                            'subreddit': item.get('name', item.get('subreddit', 'unknown')),
                            'keywords': item['keywords']
                        })
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            continue
    
    print(f"Loaded {len(data):,} subreddits for analysis")
    
    # Calculate basic stats
    keyword_counts = [len(item['keywords']) for item in data]
    hit_limit_pct = sum(1 for count in keyword_counts if count == 40) / len(keyword_counts) * 100
    
    dataset_stats = {
        'hit_limit_pct': hit_limit_pct,
        'mean_keywords': np.mean(keyword_counts),
        'median_keywords': np.median(keyword_counts)
    }
    
    print(f"\nDataset Overview:")
    print(f"  Subreddits hitting 40-keyword limit: {hit_limit_pct:.1f}%")
    print(f"  Average keywords per subreddit: {dataset_stats['mean_keywords']:.1f}")
    print(f"  Median keywords per subreddit: {dataset_stats['median_keywords']:.1f}")
    
    # Run focused analyses
    all_keywords = analyze_score_quality_patterns(data)
    degradation_data = analyze_rank_degradation_patterns(data)
    composition_data = analyze_composition_quality(data, sample_size=500)
    
    # Generate recommendations
    recommendations = recommend_topk_optimization(degradation_data, composition_data, dataset_stats)
    
    print(f"\n=== FINAL ASSESSMENT ===")
    print(f"Current topK=40 assessment:")
    if hit_limit_pct > 90:
        print(f"  🔴 TOO LOW: {hit_limit_pct:.1f}% of subreddits hit the limit")
    elif hit_limit_pct > 70:
        print(f"  🟡 BORDERLINE: {hit_limit_pct:.1f}% hit limit, consider increasing")
    else:
        print(f"  🟢 REASONABLE: {hit_limit_pct:.1f}% hit limit")
    
    # Score distribution summary
    scores = [kw['score'] for kw in all_keywords]
    score_percentiles = [np.percentile(scores, p) for p in [50, 75, 90, 95, 99]]
    print(f"  Score percentiles (50/75/90/95/99): {[f'{p:.1f}' for p in score_percentiles]}")
    
    print(f"\nRecommended actions: {len(recommendations)}")

if __name__ == "__main__":
    main()
