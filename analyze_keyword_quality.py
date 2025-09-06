#!/usr/bin/env python3
"""
Comprehensive keyword quality analysis for the 100k subreddit extraction results.
Focuses on finding redundancy patterns, quality issues, and improvement opportunities.
"""

import json
import re
from collections import defaultdict, Counter
from pathlib import Path
import sys

def load_sample_keywords(keywords_dir, max_files=10):
    """Load keywords from a sample of files for analysis."""
    keywords_data = []
    files = list(Path(keywords_dir).glob("page_*.keywords.jsonl"))[:max_files]
    
    for file_path in files:
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line.strip())
                        keywords_data.append(data)
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    
    return keywords_data

def analyze_redundancy_patterns(keywords_data):
    """Analyze different types of redundancy patterns."""
    
    print("🔍 REDUNDANCY PATTERN ANALYSIS")
    print("=" * 60)
    
    patterns = {
        'word_repetition': [],      # "word word phrase"
        'spacing_variants': [],     # "word phrase" vs "wordphrase"  
        'punctuation_variants': [], # "Ask Reddit..." vs "AskReddit"
        'substring_duplicates': [], # "phrase" vs "longer phrase"
        'mechanical_compositions': [] # disconnected word fragments
    }
    
    total_subreddits = len(keywords_data)
    total_keywords = sum(len(sub['keywords']) for sub in keywords_data)
    
    print(f"📊 Analyzing {total_keywords:,} keywords from {total_subreddits} subreddits")
    
    for sub_data in keywords_data:
        subreddit = sub_data['name']
        keywords = [kw['term'] for kw in sub_data['keywords'][:15]]  # Top 15 for analysis
        
        # Find word repetitions
        word_reps = find_word_repetitions(keywords)
        if word_reps:
            patterns['word_repetition'].extend([(subreddit, term) for term in word_reps])
        
        # Find spacing variants
        spacing_vars = find_spacing_variants(keywords)
        if spacing_vars:
            patterns['spacing_variants'].extend([(subreddit, vars) for vars in spacing_vars])
        
        # Find punctuation variants
        punct_vars = find_punctuation_variants(keywords)
        if punct_vars:
            patterns['punctuation_variants'].extend([(subreddit, vars) for vars in punct_vars])
            
        # Find substring duplicates
        substring_dups = find_substring_duplicates(keywords)
        if substring_dups:
            patterns['substring_duplicates'].extend([(subreddit, dups) for dups in substring_dups])
            
        # Find mechanical compositions
        mechanical = find_mechanical_compositions(keywords)
        if mechanical:
            patterns['mechanical_compositions'].extend([(subreddit, term) for term in mechanical])
    
    # Report findings
    for pattern_type, examples in patterns.items():
        if examples:
            print(f"\n⚠️  {pattern_type.upper().replace('_', ' ')} ({len(examples)} cases):")
            for i, example in enumerate(examples[:5]):  # Show top 5 examples
                if pattern_type in ['spacing_variants', 'punctuation_variants', 'substring_duplicates']:
                    subreddit, variants = example
                    print(f"  {i+1}. {subreddit}: {variants}")
                else:
                    subreddit, term = example
                    print(f"  {i+1}. {subreddit}: '{term}'")
            if len(examples) > 5:
                print(f"  ... and {len(examples) - 5} more cases")
    
    return patterns

def find_word_repetitions(terms):
    """Find terms with repeated words."""
    repeated = []
    for term in terms:
        words = term.lower().split()
        if len(set(words)) < len(words):
            # Check if it's a meaningful repetition (not just articles/prepositions)
            word_counts = Counter(words)
            meaningful_reps = [word for word, count in word_counts.items() 
                             if count > 1 and len(word) > 2 and word not in ['the', 'and', 'or', 'of', 'in', 'to']]
            if meaningful_reps:
                repeated.append(term)
    return repeated

def find_spacing_variants(terms):
    """Find terms that are similar except for spacing."""
    variants = []
    normalized_to_terms = defaultdict(list)
    
    for term in terms:
        # Create normalized version (remove spaces, lowercase)
        normalized = re.sub(r'\s+', '', term.lower())
        normalized_to_terms[normalized].append(term)
    
    for normalized, term_list in normalized_to_terms.items():
        if len(term_list) > 1:
            variants.append(term_list)
    
    return variants

def find_punctuation_variants(terms):
    """Find terms that differ only in punctuation."""
    variants = []
    normalized_to_terms = defaultdict(list)
    
    for term in terms:
        # Remove punctuation and normalize spacing
        normalized = re.sub(r'[^\w\s]', '', term.lower())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        normalized_to_terms[normalized].append(term)
    
    for normalized, term_list in normalized_to_terms.items():
        if len(term_list) > 1:
            variants.append(term_list)
    
    return variants

def find_substring_duplicates(terms):
    """Find terms where one is a substring of another."""
    duplicates = []
    
    for i, term1 in enumerate(terms):
        for j, term2 in enumerate(terms[i+1:], i+1):
            # Normalize for comparison
            norm1 = term1.lower().strip()
            norm2 = term2.lower().strip()
            
            if norm1 in norm2 or norm2 in norm1:
                # Check if it's a meaningful containment (not just single character)
                if abs(len(norm1) - len(norm2)) > 2:
                    duplicates.append([term1, term2])
    
    return duplicates

def find_mechanical_compositions(terms):
    """Find mechanically composed phrases that lack semantic coherence."""
    mechanical = []
    
    for term in terms:
        # Look for signs of mechanical composition
        words = term.split()
        
        # Too many unrelated words
        if len(words) >= 4:
            # Check for coherence indicators
            has_brand = any(word.lower() in ['reddit', 'ask', 'funny', 'gaming'] for word in words)
            has_connecting_words = any(word.lower() in ['the', 'and', 'of', 'in', 'to', 'for', 'with'] for word in words)
            
            # If it's a long phrase without clear semantic connection
            if not has_connecting_words and len(set(words)) == len(words):
                # Additional checks for randomness
                if has_random_word_combination(words):
                    mechanical.append(term)
    
    return mechanical

def has_random_word_combination(words):
    """Check if words seem randomly combined."""
    # Simple heuristic: look for unlikely word combinations
    random_indicators = [
        # Mixed categories (food + tech + emotions)
        len(set(['food', 'tech', 'emotion', 'place', 'action']).intersection(categorize_words(words))) > 2,
        # Contains both very common and very specific terms
        has_mix_of_common_and_specific(words)
    ]
    
    return any(random_indicators)

def categorize_words(words):
    """Simple word categorization."""
    categories = set()
    food_words = ['pizza', 'food', 'chicken', 'meat', 'eating', 'restaurant']
    tech_words = ['app', 'phone', 'computer', 'software', 'programming', 'reddit']
    emotion_words = ['happy', 'sad', 'angry', 'funny', 'scared', 'die', 'cry']
    place_words = ['office', 'house', 'school', 'hospital', 'store']
    action_words = ['running', 'eating', 'sleeping', 'working', 'playing']
    
    for word in words:
        word_lower = word.lower()
        if any(fw in word_lower for fw in food_words):
            categories.add('food')
        if any(tw in word_lower for tw in tech_words):
            categories.add('tech')
        if any(ew in word_lower for ew in emotion_words):
            categories.add('emotion')
        if any(pw in word_lower for pw in place_words):
            categories.add('place')
        if any(aw in word_lower for aw in action_words):
            categories.add('action')
    
    return categories

def has_mix_of_common_and_specific(words):
    """Check for mix of very common and very specific terms."""
    common_words = ['the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']
    specific_words = [w for w in words if len(w) > 6 and w.lower() not in common_words]
    
    return len(specific_words) >= 2 and any(w.lower() in common_words for w in words)

def analyze_source_quality(keywords_data):
    """Analyze quality patterns by source type."""
    
    print(f"\n📈 SOURCE QUALITY ANALYSIS")
    print("=" * 60)
    
    source_stats = defaultdict(lambda: {'count': 0, 'avg_score': 0, 'issues': []})
    
    for sub_data in keywords_data:
        subreddit = sub_data['name']
        
        for kw in sub_data['keywords'][:20]:  # Top 20
            source = kw['source']
            score = kw['score']
            term = kw['term']
            
            source_stats[source]['count'] += 1
            source_stats[source]['avg_score'] += score
            
            # Check for quality issues
            if has_word_repetition(term):
                source_stats[source]['issues'].append(f"{subreddit}: '{term}' (word repetition)")
            elif is_mechanical_composition(term):
                source_stats[source]['issues'].append(f"{subreddit}: '{term}' (mechanical)")
    
    # Calculate averages and report
    for source, stats in source_stats.items():
        if stats['count'] > 0:
            avg_score = stats['avg_score'] / stats['count']
            issue_rate = len(stats['issues']) / stats['count'] * 100
            
            print(f"\n📊 {source.upper()}:")
            print(f"  Count: {stats['count']:,}")
            print(f"  Avg Score: {avg_score:.2f}")
            print(f"  Issue Rate: {issue_rate:.1f}%")
            
            if stats['issues']:
                print(f"  Example Issues:")
                for issue in stats['issues'][:3]:
                    print(f"    • {issue}")

def has_word_repetition(term):
    """Check if term has word repetition."""
    words = term.lower().split()
    return len(set(words)) < len(words)

def is_mechanical_composition(term):
    """Check if term seems mechanically composed."""
    words = term.split()
    if len(words) < 3:
        return False
    
    # Simple heuristics for mechanical composition
    return (
        len(words) >= 4 and 
        not any(word.lower() in ['the', 'and', 'of', 'in', 'to', 'for', 'with', 'a', 'an'] for word in words) and
        len(set(words)) == len(words)  # No repeated words
    )

def check_specific_examples(keywords_data):
    """Check specific problematic examples from the data."""
    
    print(f"\n🎯 SPECIFIC PROBLEM ANALYSIS")
    print("=" * 60)
    
    for sub_data in keywords_data[:5]:  # Check first 5 subreddits
        subreddit = sub_data['name']
        print(f"\n📍 {subreddit} (Top 10 keywords):")
        
        for i, kw in enumerate(sub_data['keywords'][:10], 1):
            term = kw['term']
            score = kw['score']
            source = kw['source']
            
            # Quality indicators
            issues = []
            if has_word_repetition(term):
                issues.append("WORD_REP")
            if is_mechanical_composition(term):
                issues.append("MECHANICAL")
            if len(term.split()) > 5:
                issues.append("TOO_LONG")
            
            issue_str = f" [{', '.join(issues)}]" if issues else ""
            print(f"  {i:2d}. {term:<40} ({score:5.1f}, {source}){issue_str}")

def main():
    """Main analysis function."""
    
    print("🔍 KEYWORD EXTRACTION QUALITY ANALYSIS")
    print("=" * 70)
    print("Analyzing 100k subreddit keyword extraction results...")
    
    # Load sample data from both versions
    print("\n📂 Loading sample data...")
    v22_data = load_sample_keywords("/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22", max_files=15)
    v22_embed_data = load_sample_keywords("/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22_embed", max_files=10)
    
    print(f"✅ Loaded {len(v22_data)} subreddits from v22")
    print(f"✅ Loaded {len(v22_embed_data)} subreddits from v22_embed")
    
    # Analyze v22 baseline
    print(f"\n{'='*70}")
    print("V22 BASELINE ANALYSIS")
    print(f"{'='*70}")
    
    redundancy_patterns = analyze_redundancy_patterns(v22_data)
    analyze_source_quality(v22_data)
    check_specific_examples(v22_data)
    
    # Compare with embedding version if available
    if v22_embed_data:
        print(f"\n{'='*70}")
        print("V22_EMBED COMPARISON")
        print(f"{'='*70}")
        
        embed_patterns = analyze_redundancy_patterns(v22_embed_data)
        
        print(f"\n🔄 EMBEDDING IMPACT SUMMARY:")
        for pattern_type in redundancy_patterns.keys():
            v22_count = len(redundancy_patterns[pattern_type])
            embed_count = len(embed_patterns[pattern_type])
            change = embed_count - v22_count
            change_str = f"({change:+d})" if change != 0 else "(no change)"
            print(f"  {pattern_type}: {v22_count} → {embed_count} {change_str}")
    
    print(f"\n{'='*70}")
    print("🎯 QUALITY IMPROVEMENT RECOMMENDATIONS")
    print(f"{'='*70}")
    
    print("""
1. WORD REPETITION FILTERING (HIGH PRIORITY)
   • Implement deduplication for repeated words
   • Example: "surströmming surströmming splash" → "surströmming splash"
   
2. REDUNDANT VARIANT CONSOLIDATION (HIGH PRIORITY)  
   • Merge spacing/punctuation variants
   • Example: "Ask Reddit..." + "AskReddit" → Keep one preferred form
   
3. MECHANICAL COMPOSITION FILTERING (MEDIUM PRIORITY)
   • Filter semantically incoherent compositions
   • Example: "funny happens die black" → Remove (from ad fragment)
   
4. SUBSTRING DEDUPLICATION (MEDIUM PRIORITY)
   • Remove redundant longer/shorter variants
   • Example: "drug cartels" + "drug cartels near" → Prioritize by relevance
   
5. SOURCE-SPECIFIC TUNING (LOW PRIORITY)
   • Apply different quality thresholds by source
   • Example: Higher bar for posts_composed vs. description terms
    """)

if __name__ == "__main__":
    main()
