#!/usr/bin/env python3
"""
Quantitative analysis of keyword extraction results across the dataset.
"""

import json
import os
from pathlib import Path
import numpy as np
from collections import defaultdict, Counter
import re

def analyze_score_distribution(keywords_dir):
    """Analyze score distributions across all subreddits."""
    scores = []
    sources = Counter()
    composition_rates = []
    
    total_files = 0
    for file_path in Path(keywords_dir).glob("*.jsonl"):
        if file_path.stat().st_size == 0:
            continue
            
        total_files += 1
        with open(file_path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                subreddit_scores = [kw['score'] for kw in data['keywords']]
                scores.extend(subreddit_scores)
                
                # Count sources
                for kw in data['keywords']:
                    sources[kw['source']] += 1
                
                # Composition rate in top-10
                top_10 = data['keywords'][:10]
                composed_count = sum(1 for kw in top_10 if 'composed' in kw['source'])
                composition_rates.append(composed_count / len(top_10))
    
    scores = np.array(scores)
    composition_rates = np.array(composition_rates)
    
    print(f"📊 QUANTITATIVE ANALYSIS ({total_files} processed files)")
    print("=" * 60)
    
    print(f"\n🎯 SCORE DISTRIBUTION:")
    print(f"  Total keywords: {len(scores):,}")
    print(f"  Mean score: {scores.mean():.2f}")
    print(f"  Median score: {np.median(scores):.2f}")
    print(f"  Std deviation: {scores.std():.2f}")
    print(f"  Min/Max: {scores.min():.2f} / {scores.max():.2f}")
    print(f"  75th percentile: {np.percentile(scores, 75):.2f}")
    print(f"  95th percentile: {np.percentile(scores, 95):.2f}")
    print(f"  99th percentile: {np.percentile(scores, 99):.2f}")
    
    print(f"\n📝 SOURCE DISTRIBUTION:")
    total_keywords = sum(sources.values())
    for source, count in sources.most_common():
        percentage = (count / total_keywords) * 100
        print(f"  {source:<20}: {count:>8,} ({percentage:5.1f}%)")
    
    print(f"\n🎯 COMPOSITION ANALYSIS:")
    print(f"  Mean composition rate in top-10: {composition_rates.mean():.1%}")
    print(f"  Median composition rate: {np.median(composition_rates):.1%}")
    print(f"  Subreddits with >50% composition: {(composition_rates > 0.5).sum()}/{len(composition_rates)}")
    print(f"  Subreddits with >80% composition: {(composition_rates > 0.8).sum()}/{len(composition_rates)}")
    
    return scores, sources, composition_rates

def detect_quality_issues(keywords_dir, sample_size=50):
    """Detect common quality issues in keyword extraction."""
    
    url_pattern = re.compile(r'https?://|\.com|\.org|\.net|steampowered|nintendo')
    foreign_pattern = re.compile(r'[^\x00-\x7F]+')  # Non-ASCII characters
    ad_patterns = [
        'tirzepatide', 'skinny', 'healthcare', 'medicare', 'insurance',
        'loan', 'credit score', 'refinance', 'mortgage rate'
    ]
    
    issues = {
        'url_contamination': [],
        'foreign_language': [],
        'potential_ads': [],
        'fragmented_phrases': [],
        'repetitive_composition': []
    }
    
    files_checked = 0
    for file_path in sorted(Path(keywords_dir).glob("*.jsonl"))[:sample_size]:
        if file_path.stat().st_size == 0:
            continue
            
        files_checked += 1
        with open(file_path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                subreddit_name = data['name']
                
                for kw in data['keywords'][:15]:  # Check top 15
                    term = kw['term']
                    
                    # URL contamination
                    if url_pattern.search(term):
                        issues['url_contamination'].append((subreddit_name, term))
                    
                    # Foreign language
                    if foreign_pattern.search(term):
                        issues['foreign_language'].append((subreddit_name, term))
                    
                    # Potential ads
                    if any(ad_word in term.lower() for ad_word in ad_patterns):
                        issues['potential_ads'].append((subreddit_name, term))
                    
                    # Fragmented phrases (long phrases with disconnected words)
                    if len(term.split()) >= 4 and not any(word in term.lower() for word in ['the', 'and', 'or', 'of', 'to', 'in']):
                        word_coherence = 0
                        words = term.lower().split()
                        for i in range(len(words)-1):
                            if words[i] in words[i+1] or words[i+1] in words[i] or abs(len(words[i]) - len(words[i+1])) <= 2:
                                word_coherence += 1
                        if word_coherence < len(words) * 0.3:  # Low coherence threshold
                            issues['fragmented_phrases'].append((subreddit_name, term))
                
                # Check for repetitive composition (multiple similar phrases)
                composed_terms = [kw['term'] for kw in data['keywords'][:10] if 'composed' in kw.get('source', '')]
                if len(composed_terms) >= 3:
                    base_words = set()
                    for term in composed_terms:
                        words = set(term.lower().split())
                        if base_words and len(base_words.intersection(words)) >= 2:
                            issues['repetitive_composition'].append((subreddit_name, composed_terms[:3]))
                            break
                        base_words.update(words)
    
    print(f"\n🚨 QUALITY ISSUES DETECTED (from {files_checked} files):")
    print("=" * 60)
    
    for issue_type, examples in issues.items():
        if examples:
            print(f"\n❌ {issue_type.upper().replace('_', ' ')} ({len(examples)} cases):")
            for subreddit, term in examples[:5]:  # Show top 5 examples
                if isinstance(term, list):
                    term = str(term)
                print(f"  {subreddit}: {term}")
            if len(examples) > 5:
                print(f"  ... and {len(examples) - 5} more")
    
    return issues

def main():
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    print("🔬 COMPREHENSIVE KEYWORD QUALITY ANALYSIS")
    print("=" * 60)
    
    # Analyze v22 baseline
    print("\n📊 V22 BASELINE ANALYSIS:")
    v22_scores, v22_sources, v22_comp_rates = analyze_score_distribution(f"{base_dir}/keywords_10k_v22")
    
    # Analyze v22 embed
    print("\n📊 V22 EMBED ANALYSIS:")
    embed_scores, embed_sources, embed_comp_rates = analyze_score_distribution(f"{base_dir}/keywords_10k_v22_embed")
    
    # Quality issues detection
    print("\n🔍 QUALITY ISSUES DETECTION:")
    issues = detect_quality_issues(f"{base_dir}/keywords_10k_v22")
    
    # Compare versions
    print(f"\n🔄 VERSION COMPARISON:")
    print("=" * 60)
    print(f"V22 files processed: {len(list(Path(f'{base_dir}/keywords_10k_v22').glob('*.jsonl')))}")
    print(f"Embed files processed: {len(list(Path(f'{base_dir}/keywords_10k_v22_embed').glob('*.jsonl')))}")
    print(f"V22 mean score: {v22_scores.mean():.2f}")
    print(f"Embed mean score: {embed_scores.mean():.2f}")
    print(f"V22 mean composition rate: {v22_comp_rates.mean():.1%}")
    print(f"Embed mean composition rate: {embed_comp_rates.mean():.1%}")

if __name__ == "__main__":
    main()
