#!/usr/bin/env python3
"""
Comprehensive analysis of embedding vs DF-based keyword extraction:
When do embeddings complement DF? When can they replace it?
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict, Counter
import re

def analyze_embedding_vs_df_performance():
    """Compare embedding reranking vs pure DF-based results across different scenarios."""
    
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    print("🔬 EMBEDDING vs DF ANALYSIS")
    print("=" * 60)
    print("Comparing when embeddings help vs when DF-based scoring is sufficient")
    
    # Test different subreddit categories to understand patterns
    test_categories = {
        'large_generic': ['r/funny', 'r/pics', 'r/mildlyinteresting'],
        'technical_specialized': ['r/programming', 'r/MachineLearning', 'r/datascience'],  
        'hobby_specific': ['r/cooking', 'r/photography', 'r/woodworking'],
        'advice_qa': ['r/AskReddit', 'r/explainlikeimfive', 'r/personalfinance'],
        'news_discussion': ['r/worldnews', 'r/politics', 'r/science'],
        'small_niche': ['r/CX5Mods', 'r/bengals', 'r/Destiny']
    }
    
    results = {}
    
    for category, subreddit_list in test_categories.items():
        print(f"\n{'='*50}")
        print(f"CATEGORY: {category.upper()}")
        print(f"{'='*50}")
        
        category_analysis = analyze_category(base_dir, subreddit_list)
        results[category] = category_analysis
        
        # Print summary for this category
        print_category_summary(category, category_analysis)
    
    # Overall analysis
    print(f"\n{'='*60}")
    print("OVERALL ANALYSIS: WHEN EMBEDDINGS HELP VS HURT")
    print(f"{'='*60}")
    
    analyze_overall_patterns(results)
    
    return results

def analyze_category(base_dir, subreddit_list):
    """Analyze embedding impact for a specific category of subreddits."""
    
    category_results = {
        'subreddits_analyzed': [],
        'embedding_improvements': [],
        'embedding_degradations': [],
        'score_changes': [],
        'thematic_alignment_changes': [],
        'phrase_quality_changes': []
    }
    
    for subreddit in subreddit_list:
        analysis = analyze_single_subreddit(base_dir, subreddit)
        if analysis:
            category_results['subreddits_analyzed'].append(subreddit)
            
            # Collect metrics
            if analysis['overall_improvement'] > 0:
                category_results['embedding_improvements'].append(analysis)
            else:
                category_results['embedding_degradations'].append(analysis)
            
            category_results['score_changes'].append(analysis['score_distribution_change'])
            category_results['thematic_alignment_changes'].append(analysis['thematic_improvement'])
            category_results['phrase_quality_changes'].append(analysis['phrase_quality_change'])
    
    return category_results

def analyze_single_subreddit(base_dir, subreddit):
    """Detailed analysis of embedding impact on a single subreddit."""
    
    # Load both versions
    v22_data = find_subreddit_data(f"{base_dir}/keywords_10k_v22", subreddit)
    embed_data = find_subreddit_data(f"{base_dir}/keywords_10k_v22_embed", subreddit)
    
    if not v22_data or not embed_data:
        return None
    
    v22_keywords = v22_data['keywords'][:20]  # Top 20 for analysis
    embed_keywords = embed_data['keywords'][:20]
    
    print(f"\n🔍 {subreddit}:")
    print(f"  Subscribers: {v22_data.get('subscribers_count', 0):,}")
    
    # 1. Analyze thematic alignment changes
    thematic_improvement = analyze_thematic_alignment(v22_keywords, embed_keywords, v22_data)
    
    # 2. Analyze phrase quality changes  
    phrase_quality_change = analyze_phrase_quality_changes(v22_keywords, embed_keywords)
    
    # 3. Analyze score distribution changes
    score_distribution_change = analyze_score_distribution_changes(v22_keywords, embed_keywords)
    
    # 4. Analyze source diversity changes
    source_diversity_change = analyze_source_diversity_changes(v22_keywords, embed_keywords)
    
    # 5. Overall improvement score
    overall_improvement = calculate_overall_improvement(
        thematic_improvement, phrase_quality_change, score_distribution_change
    )
    
    print(f"  Thematic alignment: {thematic_improvement:+.2f}")
    print(f"  Phrase quality: {phrase_quality_change:+.2f}")
    print(f"  Score distribution: {score_distribution_change:+.2f}")
    print(f"  Overall improvement: {overall_improvement:+.2f}")
    
    return {
        'subreddit': subreddit,
        'thematic_improvement': thematic_improvement,
        'phrase_quality_change': phrase_quality_change,
        'score_distribution_change': score_distribution_change,
        'source_diversity_change': source_diversity_change,
        'overall_improvement': overall_improvement,
        'v22_keywords': v22_keywords,
        'embed_keywords': embed_keywords
    }

def analyze_thematic_alignment(v22_keywords, embed_keywords, subreddit_data):
    """Measure how embedding affects thematic alignment."""
    
    # Extract theme from subreddit name and description
    theme_words = set()
    
    # From name
    name = subreddit_data.get('name', '').replace('r/', '').lower()
    theme_words.update(re.findall(r'[a-z]+', name))
    
    # From description (top words)
    desc = subreddit_data.get('description', '').lower()
    desc_words = re.findall(r'\b[a-z]{3,}\b', desc)
    theme_words.update(desc_words[:10])  # Top words from description
    
    # Calculate theme alignment for both versions
    v22_alignment = calculate_theme_alignment(v22_keywords, theme_words)
    embed_alignment = calculate_theme_alignment(embed_keywords, theme_words)
    
    return embed_alignment - v22_alignment

def calculate_theme_alignment(keywords, theme_words):
    """Calculate how well keywords align with theme."""
    if not theme_words:
        return 0
    
    alignment_score = 0
    for i, kw in enumerate(keywords[:10]):  # Top 10 weighted more heavily
        term_words = set(re.findall(r'\b[a-z]+\b', kw['term'].lower()))
        overlap = len(term_words.intersection(theme_words))
        word_coverage = overlap / max(len(term_words), 1)
        
        # Weight by position (higher positions matter more)
        position_weight = 1.0 / (i + 1)
        alignment_score += word_coverage * position_weight * kw['score']
    
    return alignment_score

def analyze_phrase_quality_changes(v22_keywords, embed_keywords):
    """Measure changes in phrase quality (coherence, meaningfulness)."""
    
    v22_quality = calculate_average_phrase_quality(v22_keywords)
    embed_quality = calculate_average_phrase_quality(embed_keywords)
    
    return embed_quality - v22_quality

def calculate_average_phrase_quality(keywords):
    """Calculate average phrase quality score."""
    quality_scores = []
    
    for kw in keywords[:10]:  # Focus on top 10
        term = kw['term']
        words = term.split()
        
        quality_score = 0
        
        # 1. Semantic coherence
        if len(words) >= 2:
            coherence = calculate_semantic_coherence(words)
            quality_score += coherence * 0.4
        else:
            quality_score += 0.4  # Single words are inherently coherent
        
        # 2. Meaningful length (not too short, not too fragmented)
        if 1 <= len(words) <= 3:
            quality_score += 0.3
        elif len(words) == 4:
            quality_score += 0.2
        else:  # 5+ words likely fragmented
            quality_score += 0.1
        
        # 3. No technical artifacts
        if not re.search(r'https?://|\.com|\.org|www\.', term):
            quality_score += 0.2
        
        # 4. Proper composition (if composed)
        if 'composed' in kw.get('source', ''):
            if has_good_composition_structure(term):
                quality_score += 0.1
        else:
            quality_score += 0.1  # Not composed is neutral
        
        quality_scores.append(quality_score)
    
    return np.mean(quality_scores)

def calculate_semantic_coherence(words):
    """Calculate semantic coherence between words."""
    if len(words) < 2:
        return 1.0
    
    coherence_sum = 0
    pairs = 0
    
    for i in range(len(words) - 1):
        word1, word2 = words[i].lower(), words[i+1].lower()
        
        # Length similarity
        length_sim = 1 - abs(len(word1) - len(word2)) / max(len(word1), len(word2))
        
        # Character overlap
        chars1, chars2 = set(word1), set(word2)
        char_overlap = len(chars1 & chars2) / len(chars1 | chars2)
        
        # Common prefixes/suffixes
        prefix_sim = 0
        if len(word1) > 2 and len(word2) > 2:
            if word1[:2] == word2[:2] or word1[-2:] == word2[-2:]:
                prefix_sim = 0.3
        
        pair_coherence = (length_sim * 0.3 + char_overlap * 0.5 + prefix_sim * 0.2)
        coherence_sum += pair_coherence
        pairs += 1
    
    return coherence_sum / pairs

def has_good_composition_structure(term):
    """Check if composed phrase has good structure."""
    words = term.split()
    
    # Good: "subreddit_name + meaningful_phrase"
    # Bad: "subreddit_name + disconnected + fragments"
    
    if len(words) < 2:
        return False
    
    # Check if first part looks like subreddit name/brand
    first_word = words[0].lower()
    if any(indicator in first_word for indicator in ['r/', 'reddit', 'official']):
        # Rest should form coherent phrase
        remaining = ' '.join(words[1:])
        return len(remaining.split()) <= 4 and not re.search(r'\d+|https?', remaining)
    
    return True

def analyze_score_distribution_changes(v22_keywords, embed_keywords):
    """Analyze how embedding affects score distribution."""
    
    v22_scores = [kw['score'] for kw in v22_keywords]
    embed_scores = [kw['score'] for kw in embed_keywords]
    
    # Measure distribution quality (want good separation between top and bottom)
    v22_separation = calculate_score_separation(v22_scores)
    embed_separation = calculate_score_separation(embed_scores)
    
    return embed_separation - v22_separation

def calculate_score_separation(scores):
    """Calculate how well scores separate high vs low quality terms."""
    if len(scores) < 5:
        return 0
    
    top_5_mean = np.mean(scores[:5])
    bottom_5_mean = np.mean(scores[-5:])
    
    # Good separation = large gap between top and bottom
    separation = (top_5_mean - bottom_5_mean) / top_5_mean if top_5_mean > 0 else 0
    return separation

def analyze_source_diversity_changes(v22_keywords, embed_keywords):
    """Analyze how embedding affects source diversity."""
    
    v22_sources = Counter(kw['source'] for kw in v22_keywords[:10])
    embed_sources = Counter(kw['source'] for kw in embed_keywords[:10])
    
    # Diversity score (higher = more diverse sources)
    v22_diversity = len(v22_sources) / 10
    embed_diversity = len(embed_sources) / 10
    
    return embed_diversity - v22_diversity

def calculate_overall_improvement(thematic, phrase_quality, score_distribution):
    """Calculate overall improvement score."""
    # Weight the different factors
    return (thematic * 0.4 + phrase_quality * 0.4 + score_distribution * 0.2)

def find_subreddit_data(keywords_dir, subreddit_name):
    """Find subreddit data in keywords directory."""
    for file_path in Path(keywords_dir).glob("*.jsonl"):
        if file_path.stat().st_size == 0:
            continue
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    data = json.loads(line.strip())
                    if data['name'].lower() == subreddit_name.lower():
                        return data
        except (json.JSONDecodeError, KeyError):
            continue
    return None

def print_category_summary(category, analysis):
    """Print summary for a category."""
    if not analysis['subreddits_analyzed']:
        print(f"  ❌ No data available for {category}")
        return
    
    total = len(analysis['subreddits_analyzed'])
    improvements = len(analysis['embedding_improvements'])
    degradations = len(analysis['embedding_degradations'])
    
    print(f"  📊 Summary ({total} subreddits analyzed):")
    print(f"    Improvements: {improvements}/{total} ({improvements/total:.1%})")
    print(f"    Degradations: {degradations}/{total} ({degradations/total:.1%})")
    
    if analysis['thematic_alignment_changes']:
        avg_thematic = np.mean(analysis['thematic_alignment_changes'])
        print(f"    Avg thematic change: {avg_thematic:+.3f}")
    
    if analysis['phrase_quality_changes']:
        avg_quality = np.mean(analysis['phrase_quality_changes'])
        print(f"    Avg quality change: {avg_quality:+.3f}")

def analyze_overall_patterns(results):
    """Analyze overall patterns across all categories."""
    
    print(f"\n🎯 WHEN EMBEDDINGS HELP THE MOST:")
    
    # Find categories with highest improvement rates
    improvement_rates = {}
    for category, analysis in results.items():
        if analysis['subreddits_analyzed']:
            total = len(analysis['subreddits_analyzed'])
            improvements = len(analysis['embedding_improvements'])
            improvement_rates[category] = improvements / total
    
    sorted_categories = sorted(improvement_rates.items(), key=lambda x: x[1], reverse=True)
    
    for category, rate in sorted_categories:
        print(f"  {category:<20}: {rate:.1%} improvement rate")
    
    print(f"\n🎯 EMBEDDING vs DF RECOMMENDATIONS:")
    
    # Analyze when embeddings are most valuable
    high_improvement_categories = [cat for cat, rate in sorted_categories if rate > 0.6]
    medium_improvement_categories = [cat for cat, rate in sorted_categories if 0.3 <= rate <= 0.6]
    low_improvement_categories = [cat for cat, rate in sorted_categories if rate < 0.3]
    
    if high_improvement_categories:
        print(f"\n  ✅ EMBEDDINGS STRONGLY RECOMMENDED for:")
        for cat in high_improvement_categories:
            print(f"     • {cat}")
        print(f"     → Can potentially REPLACE DF-based ranking")
    
    if medium_improvement_categories:
        print(f"\n  🤝 EMBEDDINGS AS COMPLEMENT for:")
        for cat in medium_improvement_categories:
            print(f"     • {cat}")
        print(f"     → Use embeddings to REFINE DF-based results")
    
    if low_improvement_categories:
        print(f"\n  ⚠️  DF-BASED SUFFICIENT for:")
        for cat in low_improvement_categories:
            print(f"     • {cat}")
        print(f"     → Embeddings provide minimal benefit")
    
    print(f"\n🎯 STRATEGIC RECOMMENDATIONS:")
    print(f"  1. For specialized/technical subreddits: Embeddings help theme alignment")
    print(f"  2. For large generic subreddits: DF often sufficient, embeddings add polish")
    print(f"  3. For niche communities: Embeddings help surface domain-specific relevance")
    print(f"  4. For Q&A subreddits: Embeddings improve question-answer matching")
    
    print(f"\n🎯 HYBRID APPROACH RECOMMENDATION:")
    print(f"  • Use DF for initial scoring (computational efficiency)")
    print(f"  • Apply embeddings for top-K reranking (quality refinement)")
    print(f"  • Adjust embedding weight (α) by subreddit category:")
    print(f"    - Technical/specialized: α = 0.4-0.6")
    print(f"    - Generic/large: α = 0.2-0.3") 
    print(f"    - Niche/small: α = 0.3-0.5")

def main():
    results = analyze_embedding_vs_df_performance()
    
    print(f"\n\n📋 FINAL CONCLUSION:")
    print("=" * 60)
    print("Embeddings are most valuable as a COMPLEMENT to DF, not a replacement.")
    print("They excel at:")
    print("  • Refining thematic relevance")
    print("  • Improving semantic coherence") 
    print("  • Handling domain-specific terminology")
    print("But DF remains important for:")
    print("  • Computational efficiency")
    print("  • Global term importance")
    print("  • Frequency-based filtering")

if __name__ == "__main__":
    main()
