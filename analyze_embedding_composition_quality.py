#!/usr/bin/env python3
"""
Analysis script to determine if embedding reranking helps filter out 
mechanical/unnatural composed phrases.
"""

import json
import re
from pathlib import Path
from collections import defaultdict

def analyze_composition_quality_with_embeddings(base_dir):
    """Compare composition quality between v22 and v22_embed versions."""
    
    # Find common pages between both versions
    v22_dir = Path(f"{base_dir}/keywords_10k_v22")
    embed_dir = Path(f"{base_dir}/keywords_10k_v22_embed")
    
    v22_files = {f.name for f in v22_dir.glob("*.jsonl") if f.stat().st_size > 0}
    embed_files = {f.name for f in embed_dir.glob("*.jsonl") if f.stat().st_size > 0}
    common_files = v22_files.intersection(embed_files)
    
    print(f"📊 EMBEDDING IMPACT ON COMPOSITION QUALITY")
    print("=" * 60)
    print(f"Common files to analyze: {len(common_files)}")
    
    # Patterns for detecting mechanical compositions
    mechanical_patterns = [
        # Disconnected fragments (3+ words with no clear relationship)
        r'^[a-zA-Z]+ [a-zA-Z]+ [a-zA-Z]+ [a-zA-Z]+.*',
        # URL-like compositions
        r'.*https?.*|.*\.com.*|.*www.*',
        # Number/code combinations
        r'.*\d+.*[a-zA-Z]+.*\d+.*',
        # Repetitive words
        r'\b(\w+)\s+\1\b',
    ]
    
    mechanical_improvements = []
    mechanical_degradations = []
    total_comparisons = 0
    
    for filename in sorted(list(common_files))[:20]:  # Sample first 20 files
        v22_data = load_jsonl_data(v22_dir / filename)
        embed_data = load_jsonl_data(embed_dir / filename)
        
        # Create lookup by subreddit name
        embed_lookup = {item['name']: item for item in embed_data}
        
        for v22_item in v22_data:
            subreddit_name = v22_item['name']
            if subreddit_name not in embed_lookup:
                continue
                
            embed_item = embed_lookup[subreddit_name]
            total_comparisons += 1
            
            # Get composed keywords from both versions (top 10)
            v22_composed = [kw for kw in v22_item['keywords'][:10] 
                           if 'composed' in kw.get('source', '')]
            embed_composed = [kw for kw in embed_item['keywords'][:10] 
                             if 'composed' in kw.get('source', '')]
            
            # Identify mechanical phrases
            v22_mechanical = identify_mechanical_phrases(v22_composed, mechanical_patterns)
            embed_mechanical = identify_mechanical_phrases(embed_composed, mechanical_patterns)
            
            # Check for improvements (mechanical phrases filtered out)
            if v22_mechanical and len(embed_mechanical) < len(v22_mechanical):
                mechanical_improvements.append({
                    'subreddit': subreddit_name,
                    'v22_mechanical': v22_mechanical,
                    'embed_mechanical': embed_mechanical,
                    'improvement_type': 'filtered_out'
                })
            
            # Check for degradations (new mechanical phrases appearing)
            if embed_mechanical and len(embed_mechanical) > len(v22_mechanical):
                mechanical_degradations.append({
                    'subreddit': subreddit_name,
                    'v22_mechanical': v22_mechanical,
                    'embed_mechanical': embed_mechanical,
                    'degradation_type': 'new_mechanical'
                })
    
    print(f"\n🔍 MECHANICAL PHRASE ANALYSIS:")
    print(f"Total subreddits compared: {total_comparisons}")
    print(f"Improvements (mechanical phrases filtered): {len(mechanical_improvements)}")
    print(f"Degradations (new mechanical phrases): {len(mechanical_degradations)}")
    
    # Show examples of improvements
    if mechanical_improvements:
        print(f"\n✅ EMBEDDING IMPROVEMENTS (filtering mechanical phrases):")
        for example in mechanical_improvements[:5]:
            print(f"\n  {example['subreddit']}:")
            print(f"    V22 mechanical: {[p['term'] for p in example['v22_mechanical']]}")
            print(f"    Embed filtered: {[p['term'] for p in example['embed_mechanical']]}")
    
    # Show examples of degradations
    if mechanical_degradations:
        print(f"\n❌ EMBEDDING DEGRADATIONS (new mechanical phrases):")
        for example in mechanical_degradations[:3]:
            print(f"\n  {example['subreddit']}:")
            print(f"    V22: {[p['term'] for p in example['v22_mechanical']]}")
            print(f"    Embed added: {[p['term'] for p in example['embed_mechanical']]}")
    
    # Analyze rank changes for mechanical phrases
    rank_improvements = analyze_mechanical_rank_changes(v22_data, embed_data, mechanical_patterns)
    
    return {
        'total_comparisons': total_comparisons,
        'improvements': len(mechanical_improvements),
        'degradations': len(mechanical_degradations),
        'rank_changes': rank_improvements
    }

def identify_mechanical_phrases(composed_keywords, patterns):
    """Identify mechanical/unnatural phrases using pattern matching."""
    mechanical = []
    
    for kw in composed_keywords:
        term = kw['term']
        
        # Check against patterns
        for pattern in patterns:
            if re.match(pattern, term, re.IGNORECASE):
                mechanical.append(kw)
                break
        
        # Additional heuristics for mechanical phrases
        words = term.split()
        if len(words) >= 4:
            # Check for disconnected fragments (low word relationship)
            coherence_score = calculate_phrase_coherence(words)
            if coherence_score < 0.3:  # Low coherence threshold
                mechanical.append(kw)
    
    return mechanical

def calculate_phrase_coherence(words):
    """Calculate coherence score for a phrase (0-1, higher = more coherent)."""
    if len(words) < 2:
        return 1.0
    
    coherence_signals = 0
    total_pairs = len(words) - 1
    
    for i in range(len(words) - 1):
        word1, word2 = words[i].lower(), words[i + 1].lower()
        
        # Similar length (suggests related concepts)
        if abs(len(word1) - len(word2)) <= 2:
            coherence_signals += 0.3
        
        # Shared characters (suggests related words)
        shared_chars = len(set(word1) & set(word2))
        if shared_chars >= 3:
            coherence_signals += 0.4
        
        # Common endings/prefixes
        if (word1.endswith(word2[-2:]) or word2.endswith(word1[-2:])) and len(word1) > 3:
            coherence_signals += 0.5
    
    return min(1.0, coherence_signals / total_pairs)

def analyze_mechanical_rank_changes(v22_data, embed_data, patterns):
    """Analyze if mechanical phrases get demoted in ranking."""
    rank_improvements = 0
    total_mechanical = 0
    
    embed_lookup = {item['name']: item for item in embed_data}
    
    for v22_item in v22_data:
        if v22_item['name'] not in embed_lookup:
            continue
            
        embed_item = embed_lookup[v22_item['name']]
        
        # Find mechanical phrases in v22 and check their embed ranking
        v22_terms = {kw['term']: i for i, kw in enumerate(v22_item['keywords'])}
        embed_terms = {kw['term']: i for i, kw in enumerate(embed_item['keywords'])}
        
        for term, v22_rank in v22_terms.items():
            if term in embed_terms:
                embed_rank = embed_terms[term]
                
                # Check if this is a mechanical phrase
                if is_mechanical_phrase(term, patterns):
                    total_mechanical += 1
                    if embed_rank > v22_rank:  # Demoted in embed version
                        rank_improvements += 1
    
    return {
        'total_mechanical_phrases': total_mechanical,
        'rank_improvements': rank_improvements,
        'improvement_rate': rank_improvements / total_mechanical if total_mechanical > 0 else 0
    }

def is_mechanical_phrase(term, patterns):
    """Check if a phrase appears mechanical using patterns."""
    for pattern in patterns:
        if re.match(pattern, term, re.IGNORECASE):
            return True
    
    words = term.split()
    if len(words) >= 4:
        coherence = calculate_phrase_coherence(words)
        if coherence < 0.3:
            return True
    
    return False

def load_jsonl_data(file_path):
    """Load JSONL data from file."""
    data = []
    with open(file_path, 'r') as f:
        for line in f:
            data.append(json.loads(line.strip()))
    return data

def detailed_phrase_analysis(base_dir):
    """Detailed analysis of specific mechanical phrases and embedding impact."""
    
    print(f"\n🔬 DETAILED PHRASE ANALYSIS:")
    print("=" * 60)
    
    # Look at specific problematic cases we identified earlier
    target_cases = [
        ('r/funny', 'funny happens die black'),
        ('r/worldnews', 'World News enemies hit'),
        ('r/gaming', 'r/gaming https store'),
    ]
    
    for subreddit, phrase_fragment in target_cases:
        print(f"\n🎯 Analyzing: {subreddit} - phrases containing '{phrase_fragment}'")
        
        # Find the page containing this subreddit
        v22_result = find_subreddit_keywords(f"{base_dir}/keywords_10k_v22", subreddit)
        embed_result = find_subreddit_keywords(f"{base_dir}/keywords_10k_v22_embed", subreddit)
        
        if v22_result and embed_result:
            v22_keywords, embed_keywords = v22_result, embed_result
            
            # Find matching phrases
            v22_matches = [kw for kw in v22_keywords if phrase_fragment.lower() in kw['term'].lower()]
            embed_matches = [kw for kw in embed_keywords if phrase_fragment.lower() in kw['term'].lower()]
            
            print(f"  V22 matches: {len(v22_matches)}")
            for kw in v22_matches[:3]:
                print(f"    '{kw['term']}' (score: {kw['score']:.2f}, rank: {v22_keywords.index(kw)+1})")
            
            print(f"  Embed matches: {len(embed_matches)}")
            for kw in embed_matches[:3]:
                print(f"    '{kw['term']}' (score: {kw['score']:.2f}, rank: {embed_keywords.index(kw)+1})")
            
            # Calculate rank changes
            for v22_kw in v22_matches:
                v22_rank = v22_keywords.index(v22_kw) + 1
                embed_match = next((kw for kw in embed_matches if kw['term'] == v22_kw['term']), None)
                if embed_match:
                    embed_rank = embed_keywords.index(embed_match) + 1
                    rank_change = embed_rank - v22_rank
                    direction = "⬇️ demoted" if rank_change > 0 else "⬆️ promoted" if rank_change < 0 else "↔️ same"
                    print(f"    Rank change: {v22_rank} → {embed_rank} ({direction})")

def find_subreddit_keywords(keywords_dir, subreddit_name):
    """Find keywords for a specific subreddit across all pages."""
    for file_path in Path(keywords_dir).glob("*.jsonl"):
        if file_path.stat().st_size == 0:
            continue
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    data = json.loads(line.strip())
                    if data['name'].lower() == subreddit_name.lower():
                        return data['keywords']
        except (json.JSONDecodeError, KeyError):
            continue
    return None

def main():
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    # Main analysis
    results = analyze_composition_quality_with_embeddings(base_dir)
    
    # Detailed analysis of specific cases
    detailed_phrase_analysis(base_dir)
    
    # Summary
    print(f"\n📋 SUMMARY - EMBEDDING IMPACT ON MECHANICAL COMPOSITIONS:")
    print("=" * 60)
    print(f"Total comparisons made: {results['total_comparisons']}")
    print(f"Mechanical phrases filtered out: {results['improvements']}")
    print(f"New mechanical phrases introduced: {results['degradations']}")
    
    if results['rank_changes']['total_mechanical_phrases'] > 0:
        improvement_rate = results['rank_changes']['improvement_rate']
        print(f"Mechanical phrases demoted in ranking: {improvement_rate:.1%}")
    
    # Conclusion
    print(f"\n🎯 CONCLUSION:")
    if results['improvements'] > results['degradations']:
        print("✅ Embedding reranking DOES help filter out mechanical compositions")
        print("   Recommendation: Use embedding reranking as a quality filter")
    elif results['improvements'] == results['degradations']:
        print("🤷 Embedding reranking has MIXED impact on mechanical compositions")
        print("   Recommendation: Consider other approaches for filtering")
    else:
        print("❌ Embedding reranking does NOT significantly help with mechanical compositions")
        print("   Recommendation: Implement rule-based filtering instead")

if __name__ == "__main__":
    main()
