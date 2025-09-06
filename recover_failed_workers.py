#!/usr/bin/env python3
"""
Recovery utility for failed workers from batch_scrape_subreddits.py

This script helps recover and retry work from failed workers by:
1. Finding all failed_worker_*_targets.json files
2. Consolidating them into a single retry list
3. Optionally running the scraper on the failed targets
"""
import argparse
import json
import glob
from pathlib import Path
import subprocess
import sys

def find_failed_worker_files():
    """Find all failed worker target files."""
    pattern = "output/subreddits/failed_worker_*_targets.json"
    return list(Path().glob(pattern))

def load_failed_targets(files):
    """Load and consolidate all failed targets."""
    all_targets = []
    worker_info = []
    
    for file_path in files:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            worker_info.append({
                "worker_id": data.get("worker_id"),
                "error": data.get("error", "")[:100],
                "failed_at": data.get("failed_at"),
                "count": len(data.get("unfinished_targets", []))
            })
            
            # Extract subreddit names
            targets = data.get("unfinished_targets", [])
            for target in targets:
                all_targets.append(target.get("subreddit"))
                
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}")
    
    return all_targets, worker_info

def create_retry_file(targets, output_file="retry_failed_workers.txt"):
    """Create a retry file with failed targets."""
    with open(output_file, 'w') as f:
        for target in targets:
            if target:  # Skip empty targets
                f.write(f"{target}\n")
    return output_file

def print_summary(worker_info, targets):
    """Print a summary of failed workers and targets."""
    print(f"\n=== Failed Worker Recovery Summary ===")
    print(f"Total failed workers: {len(worker_info)}")
    print(f"Total failed targets: {len(targets)}")
    print(f"Unique failed targets: {len(set(targets))}")
    
    print(f"\nFailed workers details:")
    for info in worker_info:
        print(f"  Worker {info['worker_id']}: {info['count']} targets, failed at {info['failed_at']}")
        print(f"    Error: {info['error']}")

def main():
    parser = argparse.ArgumentParser(description="Recover failed worker targets and optionally retry them")
    parser.add_argument("--list", action="store_true", help="List failed workers and their targets")
    parser.add_argument("--create-retry", action="store_true", help="Create retry file from failed targets")
    parser.add_argument("--retry-file", default="retry_failed_workers.txt", help="Name of retry file to create")
    parser.add_argument("--run-retry", action="store_true", help="Actually run the retry (requires --create-retry)")
    parser.add_argument("--clean", action="store_true", help="Remove failed worker files after successful recovery")
    parser.add_argument("--concurrency", type=int, default=2, help="Concurrency for retry run")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing results when retrying")
    
    args = parser.parse_args()
    
    # Find failed worker files
    failed_files = find_failed_worker_files()
    if not failed_files:
        print("No failed worker files found.")
        return
    
    print(f"Found {len(failed_files)} failed worker files:")
    for f in failed_files:
        print(f"  {f}")
    
    # Load and consolidate targets
    targets, worker_info = load_failed_targets(failed_files)
    
    if args.list:
        print_summary(worker_info, targets)
        return
    
    if args.create_retry:
        unique_targets = list(set(targets))  # Remove duplicates
        retry_file = create_retry_file(unique_targets, args.retry_file)
        print(f"\nCreated retry file: {retry_file} with {len(unique_targets)} unique targets")
        
        if args.run_retry:
            print(f"\nRunning retry with concurrency={args.concurrency}...")
            cmd = [
                "python3", "batch_scrape_subreddits.py",
                "--file", retry_file,
                "--concurrency", str(args.concurrency),
                "--chunk-size", "25"  # Smaller chunks for retry
            ]
            
            if args.overwrite:
                cmd.append("--overwrite")
            
            print(f"Command: {' '.join(cmd)}")
            try:
                result = subprocess.run(cmd, check=True)
                print("Retry completed successfully!")
                
                if args.clean:
                    print("Cleaning up failed worker files...")
                    for f in failed_files:
                        f.unlink()
                    print(f"Removed {len(failed_files)} failed worker files")
                    
            except subprocess.CalledProcessError as e:
                print(f"Retry failed with exit code {e.returncode}")
                sys.exit(1)
        else:
            print(f"Use --run-retry to execute: python3 batch_scrape_subreddits.py --file {retry_file}")
            print_summary(worker_info, targets)

if __name__ == "__main__":
    main()
