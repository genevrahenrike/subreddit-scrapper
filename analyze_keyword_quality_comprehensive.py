#!/usr/bin/env python3
"""
Comprehensive Keyword Quality Analysis for 100k Subreddit Dataset

Analyzes keyword extraction quality focusing on:
1. Score distribution patterns and quality tiers
2. TopK optimization (is 40 too much/little?)
3. Source composition balance  
4. Quality patterns across different subreddit types
5. Potential parameter tuning recommendations
"""

import json
import glob
import random
import numpy as np
from collections import defaultdict, Counter
from pathlib import Path
import sys
import re

def load_sample_data(keyword_dir, sample_pages=50, max_subreddits_per_page=100):
    """Load a statistically representative sample of the keyword data."""
    print(f"Loading sample from {keyword_dir}...")
    
    # Get all available page files
    page_files = list(glob.glob(f"{keyword_dir}/page_*.keywords.jsonl"))
    def extract_page_num(filepath):
        match = re.search(r'page_(\d+)\.keywords\.jsonl', filepath)
        return int(match.group(1)) if match else 0
    page_files.sort(key=extract_page_num)
    
    print(f"Found {len(page_files)} page files")
    
    # Sample across different ranges for diversity
    if len(page_files) > sample_pages:
        # Sample from early, middle, and late pages for diversity
        early = page_files[:len(page_files)//3]
        middle = page_files[len(page_files)//3:2*len(page_files)//3] 
        late = page_files[2*len(page_files)//3:]
        
        sampled = (random.sample(early, min(sample_pages//3, len(early))) +
                  random.sample(middle, min(sample_pages//3, len(middle))) +
                  random.sample(late, min(sample_pages//3, len(late))))
        
        # Fill remainder randomly
        remaining = sample_pages - len(sampled)
        if remaining > 0:
            others = [f for f in page_files if f not in sampled]
            sampled.extend(random.sample(others, min(remaining, len(others))))
    else:
        sampled = page_files
    
    print(f"Sampling from {len(sampled)} pages")
    
    all_data = []
    total_subreddits = 0
    
    for page_file in sampled:
        match = re.search(r'page_(\d+)\.keywords\.jsonl', page_file)
        page_num = int(match.group(1)) if match else 0
        page_subreddits = []
        
        try:
            with open(page_file, 'r') as f:
                subreddit_count = 0
                for line in f:
                    if subreddit_count >= max_subreddits_per_page:
                        break
                    
                try:
                    data = json.loads(line.strip())
                    page_subreddits.append({
                        'page': page_num,
                        'subreddit': data.get('name', data.get('subreddit', 'unknown')),  # Handle both formats
                        'keywords': data['keywords']
                    })
                    subreddit_count += 1
                except json.JSONDecodeError as e:
                    print(f"JSON decode error in {page_file}: {e}")
                    continue
                except KeyError as e:
                    print(f"Missing key {e} in {page_file}")
                    continue
                    
        except Exception as e:
            print(f"Error reading {page_file}: {e}")
            continue
            
        all_data.extend(page_subreddits)
        total_subreddits += len(page_subreddits)
        
    print(f"Loaded {total_subreddits} subreddits from {len(sampled)} pages")
    return all_data

def analyze_score_distributions(data):
    """Analyze score distributions and identify quality tiers."""
    print("\n=== SCORE DISTRIBUTION ANALYSIS ===")
    
    all_scores = []
    all_weights = []
    source_scores = defaultdict(list)
    
    for item in data:
        for kw in item['keywords']:
            score = kw.get('score', 0)  # Changed from raw_score to score
            weight = kw.get('weight', 0)
            source = kw.get('source', 'unknown')
            
            all_scores.append(score)
            all_weights.append(weight)
            source_scores[source].append(score)
    
    scores = np.array(all_scores)
    weights = np.array(all_weights)
    
    print(f"Total keywords analyzed: {len(scores):,}")
    print(f"Score range: {scores.min():.2f} - {scores.max():.2f}")
    print(f"Score statistics:")
    print(f"  Mean: {scores.mean():.2f}")
    print(f"  Median: {np.median(scores):.2f}")
    print(f"  Std Dev: {scores.std():.2f}")
    
    # Quality tier analysis
    percentiles = [50, 75, 90, 95, 99]
    print(f"\nScore percentiles:")
    for p in percentiles:
        val = np.percentile(scores, p)
        print(f"  {p}th percentile: {val:.2f}")
        
    # Weight distribution (normalized scores)
    print(f"\nWeight statistics (normalized):")
    print(f"  Mean: {weights.mean():.4f}")
    print(f"  Median: {np.median(weights):.4f}")
    print(f"  Std Dev: {weights.std():.4f}")
    
    # Source-specific score patterns
    print(f"\nScore patterns by source:")
    for source, source_score_list in source_scores.items():
        if len(source_score_list) > 100:  # Only analyze sources with significant data
            src_scores = np.array(source_score_list)
            print(f"  {source}: mean={src_scores.mean():.2f}, "
                  f"median={np.median(src_scores):.2f}, "
                  f"count={len(src_scores):,}")
    
    return {
        'score_percentiles': {p: np.percentile(scores, p) for p in percentiles},
        'mean_score': scores.mean(),
        'std_score': scores.std(),
        'source_stats': {src: {'mean': np.mean(scores), 'count': len(scores)} 
                        for src, scores in source_scores.items()}
    }

def analyze_topk_effectiveness(data):
    """Analyze whether topK=40 is optimal by examining quality across ranks."""
    print("\n=== TOPK EFFECTIVENESS ANALYSIS ===")
    
    rank_quality = defaultdict(list)
    rank_sources = defaultdict(Counter)
    subreddit_sizes = []
    
    for item in data:
        keywords = item['keywords']
        subreddit_sizes.append(len(keywords))
        
        for i, kw in enumerate(keywords):
            rank = i + 1
            score = kw.get('score', 0)  # Changed from raw_score to score
            source = kw.get('source', 'unknown')
            
            rank_quality[rank].append(score)
            rank_sources[rank][source] += 1
    
    print(f"Subreddit keyword count statistics:")
    sizes = np.array(subreddit_sizes)
    print(f"  Mean keywords per subreddit: {sizes.mean():.1f}")
    print(f"  Median: {np.median(sizes):.1f}")
    print(f"  Range: {sizes.min()} - {sizes.max()}")
    print(f"  % with exactly 40 keywords: {(sizes == 40).mean() * 100:.1f}%")
    print(f"  % with < 40 keywords: {(sizes < 40).mean() * 100:.1f}%")
    
    # Quality degradation by rank
    print(f"\nQuality trends by keyword rank:")
    key_ranks = [1, 5, 10, 20, 30, 40]
    for rank in key_ranks:
        if rank in rank_quality and len(rank_quality[rank]) > 10:
            scores = np.array(rank_quality[rank])
            print(f"  Rank {rank:2d}: mean_score={scores.mean():.2f}, "
                  f"median={np.median(scores):.2f}, count={len(scores):,}")
    
    # Identify quality cliff
    print(f"\nLooking for quality cliff points...")
    score_drops = []
    for rank in range(1, 41):
        if rank in rank_quality and rank+5 in rank_quality:
            current_mean = np.mean(rank_quality[rank])
            next_mean = np.mean(rank_quality[rank+5])
            drop_pct = (current_mean - next_mean) / current_mean * 100
            score_drops.append((rank, drop_pct))
    
    # Find biggest drops
    score_drops.sort(key=lambda x: x[1], reverse=True)
    print(f"  Biggest quality drops (rank, % decrease):")
    for rank, drop in score_drops[:5]:
        print(f"    Rank {rank} -> {rank+5}: {drop:.1f}% drop")
    
    return {
        'avg_keywords_per_subreddit': sizes.mean(),
        'keywords_distribution': {'40': (sizes == 40).mean(), '<40': (sizes < 40).mean()},
        'quality_cliff_candidates': score_drops[:3]
    }

def analyze_source_composition(data):
    """Analyze balance and effectiveness of different keyword sources."""
    print("\n=== SOURCE COMPOSITION ANALYSIS ===")
    
    source_counts = Counter()
    source_quality = defaultdict(list)
    multi_source_patterns = Counter()
    
    for item in data:
        for kw in item['keywords']:
            source = kw.get('source', 'unknown')
            score = kw.get('score', 0)  # Changed from raw_score to score
            
            source_counts[source] += 1
            source_quality[source].append(score)
            
            # Track multi-source patterns
            if '+' in source:
                parts = sorted(source.split('+'))
                multi_source_patterns['+'.join(parts)] += 1
    
    total_keywords = sum(source_counts.values())
    
    print(f"Source distribution across {total_keywords:,} keywords:")
    for source, count in source_counts.most_common():
        pct = count / total_keywords * 100
        if len(source_quality[source]) > 0:
            avg_score = np.mean(source_quality[source])
            print(f"  {source:<25}: {pct:5.1f}% ({count:,} keywords, avg_score={avg_score:.2f})")
    
    print(f"\nMulti-source patterns:")
    for pattern, count in multi_source_patterns.most_common(10):
        pct = count / total_keywords * 100
        print(f"  {pattern:<25}: {pct:5.1f}% ({count:,} keywords)")
    
    # Source effectiveness analysis
    print(f"\nSource effectiveness (score per keyword):")
    source_effectiveness = []
    for source, scores in source_quality.items():
        if len(scores) >= 100:  # Significant sample size
            mean_score = np.mean(scores)
            median_score = np.median(scores)
            std_score = np.std(scores)
            source_effectiveness.append((source, mean_score, median_score, std_score, len(scores)))
    
    source_effectiveness.sort(key=lambda x: x[1], reverse=True)
    print(f"  {'Source':<20} {'Mean':<8} {'Median':<8} {'StdDev':<8} {'Count':<8}")
    for source, mean_s, median_s, std_s, count in source_effectiveness[:10]:
        print(f"  {source:<20} {mean_s:<8.2f} {median_s:<8.2f} {std_s:<8.2f} {count:<8,}")
    
    return {
        'source_distribution': dict(source_counts),
        'source_effectiveness': source_effectiveness,
        'multi_source_usage': dict(multi_source_patterns)
    }

def identify_quality_issues(data, sample_size=200):
    """Identify specific quality issues in the keyword extraction."""
    print("\n=== QUALITY ISSUE IDENTIFICATION ===")
    
    # Sample subreddits for detailed analysis
    sample_subreddits = random.sample(data, min(sample_size, len(data)))
    
    quality_issues = {
        'repetitive_keywords': [],
        'probable_spam': [],
        'low_quality_composition': [],
        'score_anomalies': [],
        'single_source_dominance': []
    }
    
    for item in sample_subreddits:
        subreddit = item['subreddit']
        keywords = item['keywords']
        
        # Check for repetitive patterns
        keyword_texts = [kw.get('term', '') for kw in keywords]
        word_freq = Counter()
        for text in keyword_texts:
            words = text.lower().split()
            word_freq.update(words)
        
        # Find overly repetitive words
        total_words = sum(word_freq.values())
        for word, count in word_freq.most_common(5):
            if count / total_words > 0.3 and count > 3:  # Word appears in >30% of keywords
                quality_issues['repetitive_keywords'].append({
                    'subreddit': subreddit,
                    'word': word,
                    'frequency': count / total_words,
                    'sample_keywords': [t for t in keyword_texts if word in t.lower()][:3]
                })
        
        # Check for probable spam/promotional content
        spam_indicators = ['buy', 'sale', 'discount', 'promo', 'ad', 'sponsored', 'deal']
        spam_count = 0
        for kw in keywords[:10]:  # Check top 10
            text = kw.get('term', '').lower()
            if any(indicator in text for indicator in spam_indicators):
                spam_count += 1
        
        if spam_count >= 3:
            quality_issues['probable_spam'].append({
                'subreddit': subreddit,
                'spam_count': spam_count,
                'sample_keywords': [kw.get('term', '') for kw in keywords[:5]]
            })
        
        # Check for poor composition quality
        composed_keywords = [kw for kw in keywords if 'composed' in kw.get('source', '')]
        if len(composed_keywords) > 0:
            # Look for mechanical/nonsensical compositions
            mechanical_count = 0
            for kw in composed_keywords[:5]:
                text = kw.get('term', '')
                words = text.split()
                if len(words) >= 3:
                    # Heuristic: check for repeated words or very disconnected phrases
                    word_set = set(w.lower() for w in words)
                    if len(word_set) < len(words) * 0.7:  # >30% repeated words
                        mechanical_count += 1
            
            if mechanical_count >= 2:
                quality_issues['low_quality_composition'].append({
                    'subreddit': subreddit,
                    'mechanical_count': mechanical_count,
                    'sample_composed': [kw.get('term', '') for kw in composed_keywords[:3]]
                })
        
        # Check for score anomalies
        scores = [kw.get('score', 0) for kw in keywords]  # Changed from raw_score to score
        if len(scores) > 1:
            score_ratio = max(scores) / (np.mean(scores) + 1e-6)
            if score_ratio > 50:  # One score much higher than average
                quality_issues['score_anomalies'].append({
                    'subreddit': subreddit,
                    'max_score': max(scores),
                    'avg_score': np.mean(scores),
                    'ratio': score_ratio,
                    'top_keyword': keywords[0].get('term', '')
                })
        
        # Check for single source dominance
        sources = [kw.get('source', '') for kw in keywords[:20]]  # Top 20
        source_counts = Counter(sources)
        dominant_source = source_counts.most_common(1)[0]
        if len(keywords) >= 10 and dominant_source[1] / len(sources) > 0.8:
            quality_issues['single_source_dominance'].append({
                'subreddit': subreddit,
                'dominant_source': dominant_source[0],
                'dominance_rate': dominant_source[1] / len(sources),
                'source_breakdown': dict(source_counts.most_common())
            })
    
    # Report findings
    for issue_type, issues in quality_issues.items():
        if issues:
            print(f"\n{issue_type.replace('_', ' ').title()} ({len(issues)} cases):")
            for i, issue in enumerate(issues[:3]):  # Show top 3 examples
                print(f"  {i+1}. r/{issue['subreddit']}: {issue}")
        else:
            print(f"\n{issue_type.replace('_', ' ').title()}: No significant issues found")
    
    return quality_issues

def recommend_parameter_tuning(analysis_results):
    """Provide parameter tuning recommendations based on analysis."""
    print("\n=== PARAMETER TUNING RECOMMENDATIONS ===")
    
    score_stats = analysis_results['score_analysis']
    topk_stats = analysis_results['topk_analysis']
    source_stats = analysis_results['source_analysis']
    quality_issues = analysis_results['quality_issues']
    
    recommendations = []
    
    # TopK recommendations
    avg_keywords = topk_stats['avg_keywords_per_subreddit']
    pct_full_40 = topk_stats['keywords_distribution']['40']
    quality_cliffs = topk_stats['quality_cliff_candidates']
    
    if pct_full_40 > 0.8:  # >80% of subreddits hit the 40 limit
        recommendations.append({
            'parameter': 'topk',
            'current': 40,
            'recommendation': 'Increase to 50-60',
            'reason': f'{pct_full_40*100:.1f}% of subreddits hit the 40-keyword limit',
            'priority': 'HIGH'
        })
    elif pct_full_40 < 0.3:  # <30% hit the limit
        if quality_cliffs and quality_cliffs[0][1] > 30:  # >30% quality drop
            cliff_rank = quality_cliffs[0][0]
            recommendations.append({
                'parameter': 'topk',
                'current': 40,
                'recommendation': f'Reduce to {cliff_rank + 5}',
                'reason': f'Quality cliff at rank {cliff_rank} with {quality_cliffs[0][1]:.1f}% drop',
                'priority': 'MEDIUM'
            })
    
    # Score filtering recommendations
    percentiles = score_stats['score_percentiles']
    if percentiles[95] / percentiles[50] > 10:  # Wide score distribution
        recommendations.append({
            'parameter': 'score_threshold',
            'current': 'None',
            'recommendation': f'Consider filtering below {percentiles[75]:.1f}',
            'reason': 'Wide score distribution suggests quality tiers exist',
            'priority': 'MEDIUM'
        })
    
    # Source balance recommendations
    source_dist = source_stats['source_distribution']
    total_kw = sum(source_dist.values())
    posts_pct = sum(v for k, v in source_dist.items() if 'posts' in k) / total_kw
    
    if posts_pct > 0.7:  # Posts dominate >70%
        recommendations.append({
            'parameter': 'source_weights',
            'current': 'Unknown',
            'recommendation': 'Increase name_weight and desc_weight',
            'reason': f'Posts sources dominate {posts_pct*100:.1f}% of keywords',
            'priority': 'LOW'
        })
    
    # Quality issue recommendations
    repetitive_issues = len(quality_issues.get('repetitive_keywords', []))
    composition_issues = len(quality_issues.get('low_quality_composition', []))
    
    if repetitive_issues > 10:
        recommendations.append({
            'parameter': 'stopwords/filtering',
            'current': 'Current stopword list',
            'recommendation': 'Expand stopword filtering',
            'reason': f'Found {repetitive_issues} cases of repetitive keywords',
            'priority': 'MEDIUM'
        })
    
    if composition_issues > 5:
        recommendations.append({
            'parameter': 'composition_quality',
            'current': 'Current composition settings',
            'recommendation': 'Increase composition threshold or add coherence checks',
            'reason': f'Found {composition_issues} cases of low-quality compositions',
            'priority': 'HIGH'
        })
    
    # Print recommendations
    print(f"Generated {len(recommendations)} recommendations:")
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec['parameter'].upper()} [{rec['priority']}]")
        print(f"   Current: {rec['current']}")
        print(f"   Recommendation: {rec['recommendation']}")
        print(f"   Reason: {rec['reason']}")
    
    return recommendations

def main():
    keyword_dir = "output/keywords_10k_v22"
    
    if len(sys.argv) > 1:
        keyword_dir = sys.argv[1]
    
    print(f"Analyzing keyword quality in: {keyword_dir}")
    
    # Load sample data
    data = load_sample_data(keyword_dir, sample_pages=100, max_subreddits_per_page=50)
    
    if not data:
        print("No data loaded. Exiting.")
        return
    
    # Run analyses
    analysis_results = {}
    
    analysis_results['score_analysis'] = analyze_score_distributions(data)
    analysis_results['topk_analysis'] = analyze_topk_effectiveness(data)
    analysis_results['source_analysis'] = analyze_source_composition(data)
    analysis_results['quality_issues'] = identify_quality_issues(data, sample_size=100)
    
    # Generate recommendations
    recommendations = recommend_parameter_tuning(analysis_results)
    
    print(f"\n=== SUMMARY ===")
    print(f"Analyzed {len(data):,} subreddits from {keyword_dir}")
    print(f"Generated {len(recommendations)} parameter tuning recommendations")
    print(f"Key findings:")
    print(f"  - Average keywords per subreddit: {analysis_results['topk_analysis']['avg_keywords_per_subreddit']:.1f}")
    print(f"  - Score range: {analysis_results['score_analysis']['mean_score']:.1f} ± {analysis_results['score_analysis']['std_score']:.1f}")
    print(f"  - Top source: {max(analysis_results['source_analysis']['source_distribution'].items(), key=lambda x: x[1])}")

if __name__ == "__main__":
    main()
