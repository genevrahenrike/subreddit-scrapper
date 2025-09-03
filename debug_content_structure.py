#!/usr/bin/env python3
"""
Advanced HTML structure analysis for debugging content preview extraction.
"""
import os
import re
from pathlib import Path
from bs4 import BeautifulSoup
import json

def analyze_specific_post_structure(html_file: Path, max_posts: int = 3):
    """Analyze specific posts in detail to understand the DOM structure."""
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        
        analysis = {
            'file': str(html_file),
            'detailed_posts': []
        }
        
        # Analyze shreddit-post elements in detail
        shreddit_posts = soup.find_all('shreddit-post')[:max_posts]
        
        for i, post in enumerate(shreddit_posts):
            post_detail = {
                'post_index': i,
                'attributes': dict(post.attrs) if hasattr(post, 'attrs') else {},
                'slot_elements': [],
                'text_elements': [],
                'all_selectors_found': {}
            }
            
            # Find all elements with slot="text-body"
            slot_elements = post.select('[slot="text-body"]')
            for elem in slot_elements:
                post_detail['slot_elements'].append({
                    'tag': elem.name,
                    'classes': elem.get('class', []),
                    'text_content': elem.get_text(strip=True)[:200],
                    'text_length': len(elem.get_text(strip=True)),
                    'children_count': len(elem.find_all()),
                    'has_links': bool(elem.find('a')),
                    'innerHTML_snippet': str(elem)[:300] + '...' if len(str(elem)) > 300 else str(elem)
                })
            
            # Test all our selectors
            selectors_to_test = [
                '[slot="text-body"]',
                'div[slot="text-body"]',
                'shreddit-post-text-body',
                'div[class*="text"]',
                'div[class*="content"]',
                'p'
            ]
            
            for selector in selectors_to_test:
                try:
                    if selector == 'shreddit-post-text-body':
                        # Special handling for this element
                        elements = post.find_all("shreddit-post-text-body")
                    else:
                        elements = post.select(selector)
                    
                    selector_results = []
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        if text:  # Only include elements with text
                            selector_results.append({
                                'tag': elem.name,
                                'text_preview': text[:100] + '...' if len(text) > 100 else text,
                                'text_length': len(text),
                                'is_url': text.startswith(('http://', 'https://')),
                                'has_children': bool(elem.find_all())
                            })
                    
                    if selector_results:
                        post_detail['all_selectors_found'][selector] = selector_results
                
                except Exception as e:
                    post_detail['all_selectors_found'][selector] = f"ERROR: {str(e)}"
            
            analysis['detailed_posts'].append(post_detail)
        
        return analysis
        
    except Exception as e:
        return {'file': str(html_file), 'error': str(e)}

def find_best_content_selector():
    """Find the best selector for content preview by analyzing recent HTML files."""
    html_files = list(Path("output/pages").glob("*debug*.html"))
    
    if not html_files:
        print("No debug HTML files found!")
        return
    
    # Analyze a few recent files
    recent_files = sorted(html_files, key=lambda x: x.stat().st_mtime, reverse=True)[:5]
    
    all_analyses = []
    
    for html_file in recent_files:
        print(f"Analyzing {html_file.name}...")
        analysis = analyze_specific_post_structure(html_file, max_posts=2)
        all_analyses.append(analysis)
    
    # Save detailed analysis
    output_file = "detailed_content_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_analyses, f, indent=2, ensure_ascii=False)
    
    print(f"\nDetailed analysis saved to {output_file}")
    
    # Summary analysis
    print("\n=== SUMMARY ===")
    
    selector_stats = {}
    
    for analysis in all_analyses:
        if 'detailed_posts' in analysis:
            for post in analysis['detailed_posts']:
                post_type = post['attributes'].get('post-type', 'unknown')
                
                print(f"\nPost type: {post_type}")
                print(f"Title: {post['attributes'].get('post-title', 'NO TITLE')[:60]}...")
                
                for selector, results in post.get('all_selectors_found', {}).items():
                    if isinstance(results, list) and results:
                        if selector not in selector_stats:
                            selector_stats[selector] = {'text_posts': 0, 'link_posts': 0, 'url_content': 0, 'text_content': 0}
                        
                        best_result = max(results, key=lambda x: x['text_length'] if isinstance(x, dict) else 0)
                        
                        if post_type == 'text':
                            selector_stats[selector]['text_posts'] += 1
                        elif post_type == 'link':
                            selector_stats[selector]['link_posts'] += 1
                        
                        if isinstance(best_result, dict):
                            if best_result['is_url']:
                                selector_stats[selector]['url_content'] += 1
                            else:
                                selector_stats[selector]['text_content'] += 1
                            
                            print(f"  {selector}: {best_result['text_preview']}")
    
    print("\n=== SELECTOR EFFECTIVENESS ===")
    for selector, stats in selector_stats.items():
        total = stats['text_posts'] + stats['link_posts']
        text_ratio = stats['text_content'] / total if total > 0 else 0
        print(f"{selector}:")
        print(f"  Total matches: {total}")
        print(f"  Text content ratio: {text_ratio:.2f} ({stats['text_content']}/{total})")
        print(f"  URL content: {stats['url_content']}")

if __name__ == "__main__":
    find_best_content_selector()
