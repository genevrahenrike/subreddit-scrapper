#!/usr/bin/env python3
"""
Tool to analyze HTML debug dumps and understand content preview structure.
"""
import os
import re
from pathlib import Path
from bs4 import BeautifulSoup
import json
from typing import List, Dict, Set

def find_html_files(directory: str) -> List[Path]:
    """Find all HTML debug files in the directory."""
    path = Path(directory)
    html_files = []
    if path.exists():
        html_files.extend(path.glob("*.html"))
        # Also check subdirectories
        for subdir in path.iterdir():
            if subdir.is_dir():
                html_files.extend(subdir.glob("*.html"))
    return html_files

def analyze_post_content_structure(html_file: Path) -> Dict:
    """Analyze a single HTML file to understand post content structure."""
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        soup = BeautifulSoup(content, 'html.parser')
        
        # Look for shreddit-post elements
        shreddit_posts = soup.find_all('shreddit-post')
        
        analysis = {
            'file': str(html_file),
            'shreddit_posts_count': len(shreddit_posts),
            'content_preview_patterns': [],
            'text_content_patterns': [],
            'post_samples': []
        }
        
        # Analyze first few posts in detail
        for i, post in enumerate(shreddit_posts[:5]):
            post_analysis = {
                'index': i,
                'attributes': dict(post.attrs) if hasattr(post, 'attrs') else {},
                'content_preview_found': False,
                'text_content_found': False,
                'preview_text': None,
                'content_selectors': []
            }
            
            # Look for various content preview patterns
            preview_selectors = [
                'div[slot="text-body"]',
                'div[data-testid="post-content"]',
                'div.text-body',
                'div.post-content',
                '[slot="text-body"]',
                'p',
                'div:contains("selftext")',
                'div[class*="text"]',
                'div[class*="content"]',
                'div[class*="body"]'
            ]
            
            for selector in preview_selectors:
                try:
                    elements = post.select(selector)
                    if elements:
                        for elem in elements:
                            text = elem.get_text(strip=True)
                            if text and len(text) > 10:  # Only meaningful text
                                post_analysis['content_selectors'].append({
                                    'selector': selector,
                                    'text_preview': text[:200] + '...' if len(text) > 200 else text,
                                    'full_length': len(text)
                                })
                                if not post_analysis['content_preview_found']:
                                    post_analysis['content_preview_found'] = True
                                    post_analysis['preview_text'] = text[:500]
                except Exception as e:
                    continue
            
            # Also check for any text content in the post
            all_text = post.get_text(strip=True)
            if all_text and len(all_text) > 50:
                post_analysis['text_content_found'] = True
                post_analysis['all_text_preview'] = all_text[:300] + '...' if len(all_text) > 300 else all_text
            
            analysis['post_samples'].append(post_analysis)
        
        # Look for alternative post containers if shreddit-post is empty
        if not shreddit_posts:
            alt_containers = soup.select('div[data-testid="post-container"]')
            analysis['alt_containers_count'] = len(alt_containers)
            
            for i, container in enumerate(alt_containers[:3]):
                container_analysis = {
                    'index': i,
                    'type': 'post-container',
                    'content_found': False,
                    'text_preview': None
                }
                
                # Look for text content in alternative containers
                text_elements = container.select('div[data-testid="post-content"], p, div:contains("text")')
                for elem in text_elements:
                    text = elem.get_text(strip=True)
                    if text and len(text) > 10:
                        container_analysis['content_found'] = True
                        container_analysis['text_preview'] = text[:200]
                        break
                
                analysis['post_samples'].append(container_analysis)
        
        return analysis
        
    except Exception as e:
        return {
            'file': str(html_file),
            'error': str(e)
        }

def find_content_preview_patterns(html_files: List[Path], max_files: int = 10) -> Dict:
    """Analyze multiple HTML files to find common content preview patterns."""
    all_patterns = {
        'successful_selectors': {},
        'common_attributes': {},
        'file_analyses': []
    }
    
    for html_file in html_files[:max_files]:
        print(f"Analyzing {html_file.name}...")
        analysis = analyze_post_content_structure(html_file)
        all_patterns['file_analyses'].append(analysis)
        
        # Collect successful selectors
        if 'post_samples' in analysis:
            for post in analysis['post_samples']:
                if 'content_selectors' in post:
                    for sel_info in post['content_selectors']:
                        selector = sel_info['selector']
                        if selector not in all_patterns['successful_selectors']:
                            all_patterns['successful_selectors'][selector] = []
                        all_patterns['successful_selectors'][selector].append({
                            'file': analysis['file'],
                            'text_length': sel_info['full_length'],
                            'preview': sel_info['text_preview']
                        })
    
    return all_patterns

def main():
    print("Scanning for HTML debug files...")
    
    # Check common locations
    locations = [
        "output/pages",
        "output",
        "."
    ]
    
    all_html_files = []
    for loc in locations:
        html_files = find_html_files(loc)
        if html_files:
            print(f"Found {len(html_files)} HTML files in {loc}")
            all_html_files.extend(html_files)
    
    if not all_html_files:
        print("No HTML debug files found!")
        return
    
    print(f"\nTotal HTML files found: {len(all_html_files)}")
    
    # Analyze patterns
    print("Analyzing content preview patterns...")
    patterns = find_content_preview_patterns(all_html_files, max_files=15)
    
    # Save results
    output_file = "html_content_analysis.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(patterns, f, indent=2, ensure_ascii=False)
    
    print(f"\nAnalysis saved to {output_file}")
    
    # Print summary
    print("\n=== SUMMARY ===")
    print(f"Files analyzed: {len(patterns['file_analyses'])}")
    
    successful_selectors = patterns['successful_selectors']
    if successful_selectors:
        print("\nSuccessful content selectors:")
        for selector, examples in successful_selectors.items():
            print(f"  {selector}: {len(examples)} matches")
            if examples:
                avg_length = sum(ex['text_length'] for ex in examples) / len(examples)
                print(f"    Average text length: {avg_length:.1f}")
                print(f"    Example: {examples[0]['preview'][:100]}...")
    else:
        print("No successful content selectors found!")
    
    # Show some examples of posts that had content
    print("\n=== SAMPLE POST CONTENT ===")
    for file_analysis in patterns['file_analyses'][:3]:
        if 'post_samples' in file_analysis:
            print(f"\nFile: {Path(file_analysis['file']).name}")
            for post in file_analysis['post_samples'][:2]:
                if post.get('content_preview_found') or post.get('preview_text'):
                    print(f"  Post {post['index']}: {post.get('preview_text', 'No preview')[:150]}...")

if __name__ == "__main__":
    main()
