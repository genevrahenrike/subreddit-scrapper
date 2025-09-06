#!/usr/bin/env python3
"""
Analyze the effectiveness of stopword filtering in keyword extraction results.
"""

import json
import re
from pathlib import Path
from collections import Counter, defaultdict

def load_stopwords():
    """Load all configured stopwords."""
    base_dir = Path("/Users/markzhu/Git/subreddit-scrapper")
    
    # Load phrase stoplist
    phrase_stoplist = set()
    phrase_file = base_dir / "config" / "posts_phrase_stoplist.txt"
    if phrase_file.exists():
        with open(phrase_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    phrase_stoplist.add(line.lower())
    
    # Load extra stopwords
    extra_stopwords = set()
    extra_file = base_dir / "config" / "posts_stopwords_extra.txt"
    if extra_file.exists():
        with open(extra_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Handle comma/space separated words
                    words = re.split(r'[,\s]+', line)
                    extra_stopwords.update(word.lower() for word in words if word)
    
    return phrase_stoplist, extra_stopwords

def analyze_stopword_effectiveness(keywords_dir, sample_size=50):
    """Analyze how well stopwords are filtering out low-value terms."""
    
    phrase_stoplist, extra_stopwords = load_stopwords()
    
    # Common low-value terms we'd expect to be filtered
    expected_low_value = {
        'generic_conversation': ['guys', 'thing', 'stuff', 'things', 'something', 'someone', 'anything'],
        'time_references': ['today', 'yesterday', 'tomorrow', 'now', 'then', 'recently'],
        'vague_quantifiers': ['lot', 'much', 'many', 'some', 'few', 'little', 'bit'],
        'generic_actions': ['doing', 'getting', 'going', 'coming', 'looking', 'trying'],
        'informal_language': ['lol', 'lmao', 'tbh', 'imo', 'btw', 'omg'],
        'discourse_markers': ['like', 'just', 'really', 'pretty', 'quite', 'very'],
        'promotional': ['check', 'click', 'visit', 'subscribe', 'follow', 'buy']
    }
    
    # Track what got through
    leaked_terms = defaultdict(list)
    leaked_phrases = defaultdict(list)
    
    # Track what was properly filtered (absence analysis)
    processed_subreddits = 0
    total_keywords = 0
    
    files_checked = 0
    for file_path in sorted(Path(keywords_dir).glob("*.jsonl"))[:sample_size]:
        if file_path.stat().st_size == 0:
            continue
            
        files_checked += 1
        with open(file_path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                processed_subreddits += 1
                subreddit_name = data['name']
                
                for kw in data['keywords']:
                    total_keywords += 1
                    term = kw['term'].lower()
                    source = kw['source']
                    score = kw['score']
                    
                    # Check for leaked low-value terms
                    for category, terms in expected_low_value.items():
                        for low_val_term in terms:
                            if low_val_term in term:
                                leaked_terms[category].append({
                                    'subreddit': subreddit_name,
                                    'term': kw['term'],
                                    'score': score,
                                    'source': source
                                })
                    
                    # Check for leaked phrases that should be in stoplist
                    if len(term.split()) >= 2:  # Phrases only
                        for phrase in phrase_stoplist:
                            if phrase in term:
                                leaked_phrases['phrase_stoplist'].append({
                                    'subreddit': subreddit_name,
                                    'term': kw['term'],
                                    'score': score,
                                    'source': source,
                                    'matched_phrase': phrase
                                })
                    
                    # Check for leaked extra stopwords
                    words = set(term.split())
                    leaked_stopwords = words.intersection(extra_stopwords)
                    if leaked_stopwords:
                        leaked_terms['extra_stopwords'].append({
                            'subreddit': subreddit_name,
                            'term': kw['term'],
                            'score': score,
                            'source': source,
                            'leaked_words': list(leaked_stopwords)
                        })
    
    print(f"🔍 STOPWORD FILTERING EFFECTIVENESS ANALYSIS")
    print("=" * 60)
    print(f"📊 Dataset: {files_checked} files, {processed_subreddits} subreddits, {total_keywords:,} keywords")
    
    print(f"\n📋 CONFIGURED STOPWORDS:")
    print(f"  Phrase stoplist entries: {len(phrase_stoplist)}")
    print(f"  Extra stopword entries: {len(extra_stopwords)}")
    
    print(f"\n🚨 LEAKED LOW-VALUE TERMS:")
    total_leaks = 0
    for category, leaks in leaked_terms.items():
        if leaks:
            total_leaks += len(leaks)
            print(f"\n❌ {category.upper().replace('_', ' ')} ({len(leaks)} cases):")
            # Show worst offenders (highest scores)
            worst_leaks = sorted(leaks, key=lambda x: x['score'], reverse=True)[:3]
            for leak in worst_leaks:
                print(f"  {leak['subreddit']}: '{leak['term']}' (score: {leak['score']:.1f}, source: {leak['source']})")
                if 'leaked_words' in leak:
                    print(f"    ↳ Contains stopwords: {leak['leaked_words']}")
    
    print(f"\n🚨 LEAKED PHRASE STOPLIST TERMS:")
    if leaked_phrases['phrase_stoplist']:
        print(f"❌ PHRASE STOPLIST LEAKS ({len(leaked_phrases['phrase_stoplist'])} cases):")
        worst_phrase_leaks = sorted(leaked_phrases['phrase_stoplist'], key=lambda x: x['score'], reverse=True)[:5]
        for leak in worst_phrase_leaks:
            print(f"  {leak['subreddit']}: '{leak['term']}' (score: {leak['score']:.1f})")
            print(f"    ↳ Contains stoplist phrase: '{leak['matched_phrase']}'")
    
    # Calculate effectiveness metrics
    leak_rate = total_leaks / total_keywords if total_keywords > 0 else 0
    
    print(f"\n📊 EFFECTIVENESS METRICS:")
    print(f"  Total leak incidents: {total_leaks:,}")
    print(f"  Leak rate: {leak_rate:.3%} of all keywords")
    
    if leak_rate < 0.001:  # Less than 0.1%
        grade = "A+ (Excellent)"
    elif leak_rate < 0.005:  # Less than 0.5%
        grade = "A (Very Good)"
    elif leak_rate < 0.01:  # Less than 1%
        grade = "B+ (Good)"
    elif leak_rate < 0.02:  # Less than 2%
        grade = "B (Acceptable)"
    else:
        grade = "C (Needs Improvement)"
    
    print(f"  Stopword filtering grade: {grade}")
    
    return leaked_terms, leaked_phrases, {
        'total_keywords': total_keywords,
        'total_leaks': total_leaks,
        'leak_rate': leak_rate,
        'grade': grade
    }

def analyze_df_based_filtering(keywords_dir, sample_size=20):
    """Analyze how well DF-based filtering removes generic terms."""
    
    # These should be filtered by high DF (document frequency)
    generic_terms = [
        'like', 'just', 'get', 'really', 'think', 'know', 'want', 'good', 'time', 'people',
        'make', 'see', 'use', 'way', 'new', 'first', 'work', 'need', 'find', 'help'
    ]
    
    generic_survival = Counter()
    source_analysis = defaultdict(Counter)
    
    files_checked = 0
    for file_path in sorted(Path(keywords_dir).glob("*.jsonl"))[:sample_size]:
        if file_path.stat().st_size == 0:
            continue
            
        files_checked += 1
        with open(file_path, 'r') as f:
            for line in f:
                data = json.loads(line.strip())
                
                for kw in data['keywords'][:20]:  # Top 20 only
                    term_words = set(kw['term'].lower().split())
                    for generic in generic_terms:
                        if generic in term_words:
                            generic_survival[generic] += 1
                            source_analysis[generic][kw['source']] += 1
    
    print(f"\n🔬 DF-BASED FILTERING ANALYSIS (top-20 keywords from {files_checked} files):")
    print("=" * 60)
    
    if generic_survival:
        print(f"❌ HIGH-DF TERMS THAT SURVIVED:")
        for term, count in generic_survival.most_common(10):
            print(f"  '{term}': appeared {count} times")
            sources = source_analysis[term]
            main_source = sources.most_common(1)[0] if sources else ("unknown", 0)
            print(f"    ↳ Mainly from: {main_source[0]} ({main_source[1]} times)")
    else:
        print(f"✅ NO HIGH-DF GENERIC TERMS found in top-20 keywords!")
        print("    This suggests DF filtering is working well.")

def main():
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    print("🎯 STOPWORD FILTERING EFFECTIVENESS EVALUATION")
    print("=" * 60)
    
    # Analyze v22 baseline
    leaked_terms, leaked_phrases, metrics = analyze_stopword_effectiveness(f"{base_dir}/keywords_10k_v22")
    
    # Analyze DF-based filtering
    analyze_df_based_filtering(f"{base_dir}/keywords_10k_v22")
    
    print(f"\n🎯 SUMMARY & RECOMMENDATIONS:")
    print("=" * 60)
    
    if metrics['leak_rate'] < 0.005:
        print("✅ Stopword filtering is working VERY WELL")
        print("   - Low leak rate indicates effective filtering")
        print("   - Current configuration appears well-tuned")
    elif metrics['leak_rate'] < 0.02:
        print("⚠️  Stopword filtering is working REASONABLY WELL")
        print("   - Some leaks but within acceptable range")
        print("   - Consider adding the most frequent leaked terms to stoplist")
    else:
        print("❌ Stopword filtering needs IMPROVEMENT")
        print("   - Significant leaks affecting keyword quality")
        print("   - Recommend expanding stopword lists")
    
    return metrics

if __name__ == "__main__":
    main()
