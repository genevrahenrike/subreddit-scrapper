#!/usr/bin/env python3
"""
Analyze keyword extraction quality from the 100k subreddit run.
Focus on finding new insights not covered in prior analysis.
"""

import json
import re
from collections import defaultdict, Counter
from pathlib import Path
import random

def load_keywords_sample(base_dir, max_pages=20):
    """Load a representative sample of keyword files."""
    base_path = Path(base_dir)
    keyword_files = sorted(list(base_path.glob("page_*.keywords.jsonl")))
    
    # Sample across different ranges for diversity
    sampled_files = []
    total_files = len(keyword_files)
    
    # Always include first few pages (popular subs)
    sampled_files.extend(keyword_files[:3])
    
    # Sample from middle ranges
    if total_files > 100:
        mid_start = total_files // 3
        mid_end = 2 * total_files // 3
        sampled_files.extend(keyword_files[mid_start:mid_start+5])
    
    # Sample from end ranges (smaller subs)
    if total_files > 50:
        sampled_files.extend(keyword_files[-5:])
    
    # Random sample from remaining
    remaining = set(keyword_files) - set(sampled_files)
    if remaining and len(sampled_files) < max_pages:
        additional = min(max_pages - len(sampled_files), len(remaining))
        sampled_files.extend(random.sample(list(remaining), additional))
    
    return sampled_files[:max_pages]

def analyze_keyword_issues(keyword_files):
    """Analyze various quality issues in keywords."""
    
    issues = {
        'word_repetition': [],
        'mechanical_composition': [],
        'promotional_content': [],
        'technical_artifacts': [],
        'language_mixing': [],
        'redundant_variants': [],
        'source_distribution': defaultdict(int),
        'score_ranges': []
    }
    
    all_keywords = []
    
    for file_path in keyword_files:
        print(f"Processing {file_path}")
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    subreddit_name = data['name']
                    keywords = data['keywords']
                    
                    for kw in keywords:
                        term = kw['term']
                        score = kw['score']
                        source = kw['source']
                        weight = kw['weight']
                        
                        all_keywords.append(kw)
                        issues['source_distribution'][source] += 1
                        issues['score_ranges'].append(score)
                        
                        # Check for word repetition
                        words = term.lower().split()
                        if len(words) > 1:
                            word_counts = Counter(words)
                            repeated_words = [w for w, c in word_counts.items() if c > 1]
                            if repeated_words:
                                issues['word_repetition'].append({
                                    'subreddit': subreddit_name,
                                    'term': term,
                                    'score': score,
                                    'source': source,
                                    'repeated_words': repeated_words
                                })
                        
                        # Check for mechanical composition patterns
                        if source == 'posts_composed':
                            # Look for disconnected fragments
                            if any(pattern in term.lower() for pattern in [
                                'happens die', 'enemies hit', 'artwork dentist', 
                                'think happens', 'black phone', 'splash evil'
                            ]):
                                issues['mechanical_composition'].append({
                                    'subreddit': subreddit_name,
                                    'term': term,
                                    'score': score
                                })
                        
                        # Check for promotional/marketing content
                        if any(pattern in term.lower() for pattern in [
                            'marvel rivals', 'season 3', 'only in theaters',
                            'store steampowered', 'nintendo com'
                        ]):
                            issues['promotional_content'].append({
                                'subreddit': subreddit_name,
                                'term': term,
                                'score': score,
                                'source': source
                            })
                        
                        # Check for technical artifacts
                        if re.search(r'https?://|\.com|steampowered|[0-9a-f]{8}', term.lower()):
                            issues['technical_artifacts'].append({
                                'subreddit': subreddit_name,
                                'term': term,
                                'score': score,
                                'source': source
                            })
                        
                        # Check for potential non-English content
                        if re.search(r'[äöüß]|ç|ñ|á|é|í|ó|ú', term.lower()):
                            issues['language_mixing'].append({
                                'subreddit': subreddit_name,
                                'term': term,
                                'score': score,
                                'source': source
                            })
    
    # Find redundant variants (spacing/punctuation differences)
    term_variants = defaultdict(list)
    for kw in all_keywords:
        # Normalize for comparison: remove spaces, punctuation, case
        normalized = re.sub(r'[^a-z0-9]', '', kw['term'].lower())
        if len(normalized) > 3:  # Skip very short terms
            term_variants[normalized].append(kw)
    
    for normalized, variants in term_variants.items():
        if len(variants) > 1:
            # Group by actual term text
            unique_texts = set(v['term'] for v in variants)
            if len(unique_texts) > 1:
                issues['redundant_variants'].append({
                    'normalized': normalized,
                    'variants': list(unique_texts),
                    'count': len(variants)
                })
    
    return issues

def print_analysis_report(issues):
    """Print a comprehensive analysis report."""
    
    print("\n" + "="*80)
    print("KEYWORD EXTRACTION QUALITY ANALYSIS - 100K SUBREDDITS")
    print("="*80)
    
    # Source distribution
    print(f"\n📊 SOURCE DISTRIBUTION:")
    total_keywords = sum(issues['source_distribution'].values())
    for source, count in sorted(issues['source_distribution'].items(), key=lambda x: x[1], reverse=True):
        pct = (count / total_keywords) * 100
        print(f"  {source}: {count:,} ({pct:.1f}%)")
    
    # Score distribution
    scores = issues['score_ranges']
    if scores:
        print(f"\n📈 SCORE DISTRIBUTION:")
        print(f"  Total keywords: {len(scores):,}")
        print(f"  Min: {min(scores):.2f}")
        print(f"  Max: {max(scores):.2f}")
        print(f"  Mean: {sum(scores)/len(scores):.2f}")
        
        # Percentiles
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        percentiles = [50, 75, 90, 95, 99]
        for p in percentiles:
            idx = int(n * p / 100) - 1
            print(f"  {p}th percentile: {sorted_scores[idx]:.2f}")
    
    print(f"\n🚨 QUALITY ISSUES IDENTIFIED:")
    
    # Word repetition
    if issues['word_repetition']:
        print(f"\n1. WORD REPETITION ({len(issues['word_repetition'])} cases):")
        for i, case in enumerate(issues['word_repetition'][:10]):
            print(f"   • {case['subreddit']}: \"{case['term']}\" (score: {case['score']:.1f})")
            print(f"     Repeated: {case['repeated_words']}")
        if len(issues['word_repetition']) > 10:
            print(f"   ... and {len(issues['word_repetition']) - 10} more cases")
    
    # Mechanical composition
    if issues['mechanical_composition']:
        print(f"\n2. MECHANICAL COMPOSITION ({len(issues['mechanical_composition'])} cases):")
        for i, case in enumerate(issues['mechanical_composition'][:10]):
            print(f"   • {case['subreddit']}: \"{case['term']}\" (score: {case['score']:.1f})")
        if len(issues['mechanical_composition']) > 10:
            print(f"   ... and {len(issues['mechanical_composition']) - 10} more cases")
    
    # Promotional content
    if issues['promotional_content']:
        print(f"\n3. PROMOTIONAL CONTENT ({len(issues['promotional_content'])} cases):")
        for i, case in enumerate(issues['promotional_content'][:10]):
            print(f"   • {case['subreddit']}: \"{case['term']}\" (score: {case['score']:.1f}, {case['source']})")
        if len(issues['promotional_content']) > 10:
            print(f"   ... and {len(issues['promotional_content']) - 10} more cases")
    
    # Technical artifacts
    if issues['technical_artifacts']:
        print(f"\n4. TECHNICAL ARTIFACTS ({len(issues['technical_artifacts'])} cases):")
        for i, case in enumerate(issues['technical_artifacts'][:10]):
            print(f"   • {case['subreddit']}: \"{case['term']}\" (score: {case['score']:.1f}, {case['source']})")
        if len(issues['technical_artifacts']) > 10:
            print(f"   ... and {len(issues['technical_artifacts']) - 10} more cases")
    
    # Language mixing
    if issues['language_mixing']:
        print(f"\n5. LANGUAGE MIXING ({len(issues['language_mixing'])} cases):")
        for i, case in enumerate(issues['language_mixing'][:10]):
            print(f"   • {case['subreddit']}: \"{case['term']}\" (score: {case['score']:.1f}, {case['source']})")
        if len(issues['language_mixing']) > 10:
            print(f"   ... and {len(issues['language_mixing']) - 10} more cases")
    
    # Redundant variants
    high_redundancy = [v for v in issues['redundant_variants'] if v['count'] > 2]
    if high_redundancy:
        print(f"\n6. REDUNDANT VARIANTS ({len(high_redundancy)} groups with 3+ variants):")
        for i, case in enumerate(sorted(high_redundancy, key=lambda x: x['count'], reverse=True)[:10]):
            print(f"   • {case['count']} variants: {', '.join(case['variants'][:3])}")
            if len(case['variants']) > 3:
                print(f"     ... and {len(case['variants']) - 3} more")
    
    print(f"\n💡 INSIGHTS:")
    
    # Source quality correlation
    posts_composed_issues = sum(1 for issue_list in [
        issues['word_repetition'], issues['mechanical_composition']
    ] for case in issue_list if case.get('source') == 'posts_composed')
    
    total_posts_composed = issues['source_distribution']['posts_composed']
    if total_posts_composed > 0:
        posts_composed_issue_rate = (posts_composed_issues / total_posts_composed) * 100
        print(f"  • posts_composed source has {posts_composed_issue_rate:.1f}% issue rate")
    
    # Score correlation with quality
    high_score_issues = sum(1 for issue_list in [
        issues['word_repetition'], issues['mechanical_composition'], 
        issues['promotional_content']
    ] for case in issue_list if case.get('score', 0) > 10)
    
    print(f"  • {high_score_issues} quality issues have scores > 10")
    
    print(f"\n🎯 RECOMMENDATIONS:")
    print(f"  1. Implement word repetition filter for composed terms")
    print(f"  2. Add promotional content detection before keyword extraction")
    print(f"  3. Filter technical artifacts (URLs, domains, hex strings)")
    print(f"  4. Consider language detection for non-English content")
    print(f"  5. Consolidate redundant spacing/punctuation variants")

if __name__ == "__main__":
    # Set random seed for reproducible sampling
    random.seed(42)
    
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22"
    
    print("Loading keyword files...")
    keyword_files = load_keywords_sample(base_dir, max_pages=20)
    print(f"Selected {len(keyword_files)} files for analysis")
    
    print("Analyzing keyword quality issues...")
    issues = analyze_keyword_issues(keyword_files)
    
    print_analysis_report(issues)
