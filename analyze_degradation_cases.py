#!/usr/bin/env python3
"""
Deep dive analysis of embedding degradation cases where quality got worse.
"""

import json
import re
from pathlib import Path

def analyze_degradation_cases():
    """Examine specific cases where embedding reranking degraded quality."""
    
    base_dir = "/Users/markzhu/Git/subreddit-scrapper/output"
    
    # The specific degradation cases from our earlier analysis
    degradation_cases = [
        'r/bengals',
        'r/Destiny', 
        'r/iagreewithmyhusband'
    ]
    
    print("🔍 DEEP DIVE: EMBEDDING DEGRADATION ANALYSIS")
    print("=" * 60)
    print("Examining cases where embedding reranking introduced new mechanical phrases")
    
    for subreddit in degradation_cases:
        print(f"\n{'='*60}")
        print(f"CASE STUDY: {subreddit}")
        print(f"{'='*60}")
        
        # Get keywords from both versions
        v22_keywords = find_subreddit_keywords(f"{base_dir}/keywords_10k_v22", subreddit)
        embed_keywords = find_subreddit_keywords(f"{base_dir}/keywords_10k_v22_embed", subreddit)
        
        if not v22_keywords or not embed_keywords:
            print(f"❌ Keywords not found for {subreddit}")
            continue
        
        # Load source content to understand context
        frontpage_data = load_subreddit_frontpage(base_dir, subreddit)
        
        # Analyze the differences
        analyze_keyword_differences(subreddit, v22_keywords, embed_keywords, frontpage_data)

def find_subreddit_keywords(keywords_dir, subreddit_name):
    """Find keywords for a specific subreddit."""
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

def load_subreddit_frontpage(base_dir, subreddit_name):
    """Load frontpage data for a subreddit."""
    subreddit_clean = subreddit_name.replace("r/", "")
    frontpage_file = Path(base_dir) / "subreddits" / subreddit_clean / "frontpage.json"
    
    if frontpage_file.exists():
        try:
            with open(frontpage_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return None

def analyze_keyword_differences(subreddit, v22_data, embed_data, frontpage_data):
    """Analyze the specific differences that constitute degradation."""
    
    print(f"\n📊 BASIC INFO:")
    print(f"  Subreddit: {subreddit}")
    print(f"  Subscribers: {v22_data.get('subscribers_count', 'N/A'):,}")
    print(f"  Description: {v22_data.get('description', 'N/A')[:100]}...")
    
    # Show frontpage context
    if frontpage_data and 'posts' in frontpage_data:
        print(f"\n📄 FRONTPAGE POSTS (sample):")
        for i, post in enumerate(frontpage_data['posts'][:5], 1):
            title = post.get('title', '')[:80]
            score = post.get('score', 0)
            comments = post.get('comments', 0)
            print(f"  {i}. {title}... (↑{score}, 💬{comments})")
    
    # Get composed keywords from both versions
    v22_composed = [kw for kw in v22_data['keywords'][:15] if 'composed' in kw.get('source', '')]
    embed_composed = [kw for kw in embed_data['keywords'][:15] if 'composed' in kw.get('source', '')]
    
    print(f"\n🎯 COMPOSED KEYWORDS COMPARISON:")
    print(f"  V22 composed phrases: {len(v22_composed)}")
    print(f"  Embed composed phrases: {len(embed_composed)}")
    
    # Find the new mechanical phrases introduced by embedding
    v22_terms = {kw['term'] for kw in v22_composed}
    embed_terms = {kw['term'] for kw in embed_composed}
    new_in_embed = embed_terms - v22_terms
    
    if new_in_embed:
        print(f"\n❌ NEW MECHANICAL PHRASES IN EMBED (the degradation):")
        for term in new_in_embed:
            # Find the phrase in embed results
            embed_kw = next(kw for kw in embed_composed if kw['term'] == term)
            rank = embed_data['keywords'].index(embed_kw) + 1
            print(f"  • '{term}' (score: {embed_kw['score']:.2f}, rank: {rank})")
            
            # Analyze why this phrase is mechanical/low quality
            quality_issues = analyze_phrase_quality(term, frontpage_data)
            for issue in quality_issues:
                print(f"    ⚠️  {issue}")
    
    # Compare top 10 overall
    print(f"\n📋 TOP 10 COMPARISON:")
    print(f"\n  V22 TOP 10:")
    for i, kw in enumerate(v22_data['keywords'][:10], 1):
        source_icon = get_source_icon(kw['source'])
        print(f"  {i:2d}. {source_icon} {kw['term']:<35} ({kw['score']:.2f})")
    
    print(f"\n  EMBED TOP 10:")
    for i, kw in enumerate(embed_data['keywords'][:10], 1):
        source_icon = get_source_icon(kw['source'])
        is_new = kw['term'] in new_in_embed
        marker = " 🆕" if is_new else ""
        print(f"  {i:2d}. {source_icon} {kw['term']:<35} ({kw['score']:.2f}){marker}")
    
    # Examine the source posts that created these mechanical phrases
    if new_in_embed and frontpage_data:
        print(f"\n🔍 SOURCE POST ANALYSIS:")
        analyze_source_posts_for_mechanical_phrases(new_in_embed, frontpage_data)

def analyze_phrase_quality(phrase, frontpage_data):
    """Analyze what makes a phrase mechanical/low quality."""
    issues = []
    words = phrase.lower().split()
    
    # Issue 1: Disconnected fragments
    if len(words) >= 4:
        coherence = calculate_semantic_coherence(words)
        if coherence < 0.3:
            issues.append(f"Low semantic coherence ({coherence:.2f})")
    
    # Issue 2: Person names (likely from ads/irrelevant content)
    if any(word.istitle() and len(word) > 3 for word in phrase.split()):
        issues.append("Contains proper names (likely promotional content)")
    
    # Issue 3: Repeated words
    word_counts = {}
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1
    if any(count > 1 for count in word_counts.values()):
        issues.append("Contains repeated words")
    
    # Issue 4: Non-English characters
    if re.search(r'[^\x00-\x7F]', phrase):
        issues.append("Contains non-ASCII characters")
    
    # Issue 5: Length without substance
    if len(words) >= 5 and all(len(word) <= 3 for word in words):
        issues.append("Many short words, likely fragmented")
    
    # Issue 6: No clear subject-verb-object or noun phrase structure
    if len(words) >= 4 and not has_clear_structure(words):
        issues.append("No clear grammatical structure")
    
    return issues

def calculate_semantic_coherence(words):
    """Calculate how semantically related the words are (simple heuristic)."""
    if len(words) < 2:
        return 1.0
    
    coherence_score = 0
    total_pairs = len(words) - 1
    
    for i in range(len(words) - 1):
        word1, word2 = words[i], words[i + 1]
        
        # Similar length suggests related concepts
        length_similarity = 1 - abs(len(word1) - len(word2)) / max(len(word1), len(word2))
        coherence_score += length_similarity * 0.3
        
        # Shared characters
        shared = len(set(word1.lower()) & set(word2.lower()))
        char_similarity = shared / max(len(word1), len(word2))
        coherence_score += char_similarity * 0.4
        
        # Common prefixes/suffixes
        if (word1.lower().startswith(word2.lower()[:2]) or 
            word2.lower().startswith(word1.lower()[:2]) or
            word1.lower().endswith(word2.lower()[-2:]) or 
            word2.lower().endswith(word1.lower()[-2:])) and len(word1) > 2:
            coherence_score += 0.3
    
    return min(1.0, coherence_score / total_pairs)

def has_clear_structure(words):
    """Check if phrase has clear grammatical structure."""
    # Very simple heuristic - look for common patterns
    phrase = ' '.join(words).lower()
    
    # Noun phrases
    if any(pattern in phrase for pattern in ['new ', 'best ', 'good ', 'old ', 'big ', 'small ']):
        return True
    
    # Action phrases  
    if any(pattern in phrase for pattern in [' and ', ' or ', ' the ', ' of ', ' in ', ' on ', ' for ']):
        return True
    
    # Compound terms
    if len(words) == 2 and all(len(word) > 3 for word in words):
        return True
        
    return False

def analyze_source_posts_for_mechanical_phrases(mechanical_phrases, frontpage_data):
    """Find which posts generated the mechanical phrases."""
    if not frontpage_data or 'posts' not in frontpage_data:
        print("    No frontpage data available")
        return
    
    for phrase in mechanical_phrases:
        phrase_words = set(word.lower() for word in phrase.split())
        
        print(f"\n  🔍 Tracing phrase: '{phrase}'")
        
        # Find posts that contain these words
        matching_posts = []
        for post in frontpage_data['posts']:
            title = post.get('title', '').lower()
            content = post.get('content', '').lower()
            full_text = title + ' ' + content
            
            # Check if most words from phrase appear in this post
            words_found = sum(1 for word in phrase_words if word in full_text)
            if words_found >= len(phrase_words) * 0.6:  # 60% word overlap
                matching_posts.append({
                    'post': post,
                    'word_overlap': words_found / len(phrase_words),
                    'title': post.get('title', '')[:100]
                })
        
        # Sort by overlap and show most likely sources
        matching_posts.sort(key=lambda x: x['word_overlap'], reverse=True)
        
        if matching_posts:
            print(f"    Likely source posts:")
            for i, match in enumerate(matching_posts[:2], 1):
                post = match['post']
                title = match['title']
                score = post.get('score', 0)
                comments = post.get('comments', 0)
                overlap = match['word_overlap']
                print(f"      {i}. \"{title}...\" (↑{score}, 💬{comments}, {overlap:.1%} overlap)")
        else:
            print(f"    No clear source post found")

def get_source_icon(source):
    """Get emoji icon for source type."""
    icons = {
        "name": "🏷️", 
        "description": "📄", 
        "posts": "💬", 
        "posts_composed": "🎯",
        "description+name": "📄🏷️",
        "description+posts": "📄💬",
        "name+posts": "🏷️💬",
        "description+name+posts": "📄🏷️💬"
    }
    return icons.get(source, "❓")

def main():
    analyze_degradation_cases()
    
    print(f"\n\n📋 QUALITY MEASUREMENT METHODOLOGY:")
    print("=" * 60)
    print("My quality assessment considers a phrase 'mechanical' if it has:")
    print("  1. Low semantic coherence (< 0.3 on 0-1 scale)")
    print("  2. Disconnected word fragments (4+ words, no clear relationship)")
    print("  3. Repeated words or non-English characters")
    print("  4. Proper names (suggesting promotional content)")
    print("  5. No clear grammatical structure")
    print("  6. Many short words without substance")
    print("\nThese heuristics aim to identify phrases that:")
    print("  • Lack meaningful semantic content")
    print("  • Result from mechanical composition rather than natural language")
    print("  • Would not be useful as thematic keywords")

if __name__ == "__main__":
    main()
