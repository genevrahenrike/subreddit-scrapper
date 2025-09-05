#!/usr/bin/env python3
"""
Alternative job splitting strategies for subreddit scraping.
"""

import json
from pathlib import Path
import argparse
from collections import defaultdict

def load_all_subreddits():
    """Load all subreddits with their ranks."""
    subs_with_rank = {}
    pages_dir = Path('output/pages')
    
    for page_file in pages_dir.glob('page_*.json'):
        if 'gpu_test' in str(page_file):
            continue
        try:
            with open(page_file, 'r') as f:
                data = json.load(f)
                for item in data.get('subreddits', []):
                    name = item.get('name', '') or item.get('url', '')
                    if name:
                        if name.startswith('r/'):
                            name = name[2:]
                        name = name.lower()
                        rank = item.get('rank')
                        if rank is not None and (name not in subs_with_rank or rank < subs_with_rank[name]):
                            subs_with_rank[name] = rank
        except Exception as e:
            print(f'Error in {page_file}: {e}')
    
    return subs_with_rank

def split_alphabetically(subs_dict, num_splits):
    """Split subreddits alphabetically."""
    sorted_subs = sorted(subs_dict.keys())
    chunk_size = len(sorted_subs) // num_splits
    remainder = len(sorted_subs) % num_splits
    
    chunks = []
    start = 0
    for i in range(num_splits):
        size = chunk_size + (1 if i < remainder else 0)
        end = start + size
        chunk = sorted_subs[start:end]
        chunks.append(chunk)
        start = end
    
    return chunks

def split_by_rank_ranges(subs_dict, num_splits):
    """Split by rank ranges (most popular to least popular)."""
    sorted_by_rank = sorted(subs_dict.items(), key=lambda x: x[1] if x[1] is not None else float('inf'))
    chunk_size = len(sorted_by_rank) // num_splits
    remainder = len(sorted_by_rank) % num_splits
    
    chunks = []
    start = 0
    for i in range(num_splits):
        size = chunk_size + (1 if i < remainder else 0)
        end = start + size
        chunk = [sub for sub, rank in sorted_by_rank[start:end]]
        chunks.append(chunk)
        start = end
    
    return chunks

def generate_custom_jobs(method='alphabetical', num_servers=6, concurrency=4):
    """Generate job files for custom splitting."""
    
    print("Loading subreddit data...")
    subs_dict = load_all_subreddits()
    print(f"Loaded {len(subs_dict):,} unique subreddits")
    
    if method == 'alphabetical':
        chunks = split_alphabetically(subs_dict, num_servers)
        method_desc = "alphabetically"
    elif method == 'rank':
        chunks = split_by_rank_ranges(subs_dict, num_servers)
        method_desc = "by rank (popular first)"
    else:
        raise ValueError(f"Unknown method: {method}")
    
    print(f"\nSplitting {method_desc} into {num_servers} chunks:")
    
    # Create individual subreddit list files
    scripts_dir = Path('scripts/jobs')
    scripts_dir.mkdir(exist_ok=True)
    
    for i, chunk in enumerate(chunks):
        # Write subreddit list file
        list_file = scripts_dir / f"subreddits_server_{i+1}.txt"
        with open(list_file, 'w') as f:
            for sub in chunk:
                f.write(f"r/{sub}\n")
        
        print(f"Server {i+1:2d}: {len(chunk):5d} subreddits ({chunk[0][:20]:<20} ... {chunk[-1][:20]:<20})")
        print(f"           File: {list_file}")
    
    print(f"\nNow create a custom script that reads from these files!")
    print("You could modify subreddit_frontpage_scraper.py to accept a file input.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=['alphabetical', 'rank'], default='alphabetical')
    parser.add_argument("--servers", type=int, default=6)
    parser.add_argument("--concurrency", type=int, default=4)
    
    args = parser.parse_args()
    generate_custom_jobs(args.method, args.servers, args.concurrency)
