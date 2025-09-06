#!/usr/bin/env python3
"""
Direct comparison between v22 and v22_embed to quantify embedding impact.
"""

import json
from pathlib import Path
from collections import defaultdict

def compare_versions():
    """Compare v22 vs v22_embed for identical subreddits."""
    
    print("🔄 V22 vs V22_EMBED DIRECT COMPARISON")
    print("=" * 60)
    
    # Load matching files from both versions
    v22_dir = Path("/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22")
    embed_dir = Path("/Users/markzhu/Git/subreddit-scrapper/output/keywords_10k_v22_embed")
    
    # Find common files
    v22_files = {f.name for f in v22_dir.glob("*.jsonl")}
    embed_files = {f.name for f in embed_dir.glob("*.jsonl")}
    common_files = v22_files & embed_files
    
    print(f"📊 Comparing {len(common_files)} common files...")
    
    improvements = []
    degradations = []
    no_change = 0
    
    for filename in list(common_files)[:10]:  # Sample first 10 files
        v22_data = load_file(v22_dir / filename)
        embed_data = load_file(embed_dir / filename)
        
        # Compare subreddits that exist in both
        for v22_sub in v22_data:
            embed_sub = find_matching_subreddit(embed_data, v22_sub['name'])
            if embed_sub:
                comparison = compare_subreddit_keywords(v22_sub, embed_sub)
                if comparison['improvement_score'] > 0.1:
                    improvements.append(comparison)
                elif comparison['improvement_score'] < -0.1:
                    degradations.append(comparison)
                else:
                    no_change += 1
    
    print(f"\n📈 EMBEDDING IMPACT SUMMARY:")
    print(f"  Improvements: {len(improvements)}")
    print(f"  Degradations: {len(degradations)}")
    print(f"  No significant change: {no_change}")
    
    if improvements:
        print(f"\n✅ TOP IMPROVEMENTS:")
        for imp in improvements[:5]:
            print(f"  • {imp['subreddit']}: {imp['improvement_score']:+.2f}")
            print(f"    Filtered out: {', '.join(imp['filtered_issues'][:3])}")
    
    if degradations:
        print(f"\n❌ TOP DEGRADATIONS:")
        for deg in degradations[:3]:
            print(f"  • {deg['subreddit']}: {deg['improvement_score']:+.2f}")

def load_file(filepath):
    """Load JSONL file."""
    data = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line.strip()))
    except:
        pass
    return data

def find_matching_subreddit(data_list, subreddit_name):
    """Find matching subreddit in data list."""
    for item in data_list:
        if item['name'] == subreddit_name:
            return item
    return None

def compare_subreddit_keywords(v22_sub, embed_sub):
    """Compare keywords between versions for the same subreddit."""
    
    subreddit = v22_sub['name']
    v22_terms = [kw['term'] for kw in v22_sub['keywords'][:15]]
    embed_terms = [kw['term'] for kw in embed_sub['keywords'][:15]]
    
    # Check what issues were filtered out
    filtered_issues = []
    for term in v22_terms:
        if term not in embed_terms:
            if has_word_repetition(term):
                filtered_issues.append(f"word_rep: {term}")
            elif is_mechanical(term):
                filtered_issues.append(f"mechanical: {term}")
    
    # Simple improvement score based on issue reduction
    v22_issues = sum(1 for term in v22_terms if has_word_repetition(term) or is_mechanical(term))
    embed_issues = sum(1 for term in embed_terms if has_word_repetition(term) or is_mechanical(term))
    
    improvement_score = (v22_issues - embed_issues) / max(len(v22_terms), 1)
    
    return {
        'subreddit': subreddit,
        'improvement_score': improvement_score,
        'filtered_issues': filtered_issues,
        'v22_issues': v22_issues,
        'embed_issues': embed_issues
    }

def has_word_repetition(term):
    """Check for word repetition."""
    words = term.split()
    return len(set(words)) < len(words)

def is_mechanical(term):
    """Simple mechanical composition check."""
    words = term.split()
    return (len(words) >= 4 and 
            not any(w.lower() in ['the', 'and', 'of', 'in'] for w in words))

if __name__ == "__main__":
    compare_versions()
