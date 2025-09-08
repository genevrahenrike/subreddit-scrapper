#!/usr/bin/env python3
"""
Batch Community Ranking Scraper

High-throughput parallel scraping of Reddit community ranking pages with
intelligent work distribution and load balancing.

Features:
- Parallel processing with worker isolation
- Intelligent work allocation and load balancing
- Engine rotation and enhanced stealth
- Bandwidth optimization and connectivity monitoring
- Progress tracking and error recovery
"""

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import random
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from discovery_scraper_local import CommunityRankingScraper, EnhancedScraperConfig


def _init_worker():
    """Initialize worker process with clean environment"""
    # Handle signals in worker processes
    def worker_signal_handler(signum, frame):
        print(f"[worker-{os.getpid()}] Received signal {signum}, exiting...")
        sys.exit(1)
    
    signal.signal(signal.SIGINT, worker_signal_handler)
    signal.signal(signal.SIGTERM, worker_signal_handler)
    
    # Ensure no asyncio loop interference
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.close()
    except Exception:
        pass
    
    try:
        asyncio.set_event_loop(None)
    except Exception:
        pass


def _worker_process(
    worker_id: int,
    page_ranges: List[Tuple[int, int]],
    config_dict: Dict,
    jitter_s: float = 0.5,
    chunk_size: int = 25,
) -> Dict:
    """Worker that processes multiple page ranges with one browser per chunk"""
    
    print(f"[w{worker_id}] Starting with {len(page_ranges)} page ranges")
    
    # Light stagger to prevent workers starting simultaneously
    time.sleep(random.uniform(0, max(0.0, float(jitter_s))))
    
    # Reconstruct config with worker ID
    config = EnhancedScraperConfig(**config_dict)
    config.worker_id = worker_id
    
    total_pages = 0
    total_subreddits = 0
    errors = 0
    pages_completed = []
    
    # Process page ranges in chunks to recycle browser periodically
    for range_start in range(0, len(page_ranges), chunk_size):
        chunk_ranges = page_ranges[range_start:range_start + chunk_size]
        scraper = None
        
        try:
            # Create new scraper for this chunk
            scraper = CommunityRankingScraper(config)
            scraper._start()
            
            # Process all ranges in this chunk
            for start_page, end_page in chunk_ranges:
                try:
                    for page in range(start_page, end_page + 1):
                        subs = scraper.scrape_and_persist_page(page)
                        pages_completed.append(page)
                        total_pages += 1
                        total_subreddits += len(subs)
                        
                        # Brief inter-page delay
                        time.sleep(random.uniform(0.1, 0.3))
                        
                except Exception as e:
                    print(f"[w{worker_id}] Error in range {start_page}-{end_page}: {e}")
                    errors += 1
                    
        except Exception as e:
            print(f"[w{worker_id}] Chunk error: {e}")
            errors += 1
        finally:
            if scraper:
                try:
                    scraper._stop()
                except Exception:
                    pass
        
        # Brief inter-chunk delay
        if range_start + chunk_size < len(page_ranges):
            time.sleep(random.uniform(1.0, 2.0))
    
    print(f"[w{worker_id}] Completed: {total_pages} pages, {total_subreddits} subreddits, {errors} errors")
    
    return {
        "worker_id": worker_id,
        "pages_completed": pages_completed,
        "total_pages": total_pages,
        "total_subreddits": total_subreddits,
        "errors": errors,
    }


def distribute_page_ranges(start_page: int, end_page: int, workers: int, chunk_size: int = 5) -> List[List[Tuple[int, int]]]:
    """Distribute page ranges across workers for balanced load"""
    
    # Create small page ranges (chunks)
    page_chunks = []
    for start in range(start_page, end_page + 1, chunk_size):
        chunk_end = min(start + chunk_size - 1, end_page)
        page_chunks.append((start, chunk_end))
    
    print(f"Created {len(page_chunks)} page chunks of size {chunk_size}")
    
    # Distribute chunks across workers using round-robin for balance
    worker_assignments = [[] for _ in range(workers)]
    for i, chunk in enumerate(page_chunks):
        worker_assignments[i % workers].append(chunk)
    
    # Show distribution
    for w, ranges in enumerate(worker_assignments):
        if ranges:
            total_pages = sum(end - start + 1 for start, end in ranges)
            print(f"[w{w}] Assigned {len(ranges)} ranges ({total_pages} pages)")
    
    return worker_assignments


def save_batch_manifest(workers_completed: int, total_workers: int, total_pages: int, total_subreddits: int, total_errors: int):
    """Save batch processing manifest"""
    manifest = {
        "batch_type": "community_ranking_parallel",
        "workers_completed": workers_completed,
        "total_workers": total_workers,
        "total_pages": total_pages,
        "total_subreddits": total_subreddits,
        "total_errors": total_errors,
        "success_rate": workers_completed / total_workers * 100 if total_workers > 0 else 0,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    
    os.makedirs("output", exist_ok=True)
    with open("output/batch_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)


def main():
    """Enhanced batch scraper with intelligent work allocation"""
    parser = argparse.ArgumentParser(description="Batch community ranking scraper with parallel processing")
    
    # Page range options
    parser.add_argument("--start-page", type=int, default=1, help="Starting page number")
    parser.add_argument("--end-page", type=int, default=100, help="Ending page number")
    parser.add_argument("--chunk-size", type=int, default=5, help="Pages per chunk for load balancing")
    
    # Parallel processing options
    parser.add_argument("--workers", type=int, default=2, help="Number of parallel workers")
    parser.add_argument("--max-workers", type=int, default=8, help="Maximum workers safety cap")
    parser.add_argument("--worker-chunk-size", type=int, default=25, help="Chunks per browser instance")
    parser.add_argument("--initial-jitter", type=float, default=1.0, help="Worker start jitter (seconds)")
    parser.add_argument("--ramp-up", type=float, default=3.0, help="Worker ramp-up period (seconds)")
    
    # Browser and network options
    parser.add_argument("--browser-engine", choices=["chromium", "webkit", "firefox"],
                       default="chromium", help="Browser engine to use")
    parser.add_argument("--multi-engine", action="store_true",
                       help="Enable engine rotation for enhanced stealth")
    parser.add_argument("--proxy", help="Proxy server URL")
    parser.add_argument("--disable-images", action="store_true", default=True,
                       help="Block images to save bandwidth (default)")
    parser.add_argument("--enable-images", dest="disable_images", action="store_false",
                       help="Enable image downloads")
    
    # Control options
    parser.add_argument("--no-archive", action="store_true", help="Skip archiving existing data")
    parser.add_argument("--visible", action="store_true", help="Run browsers in visible mode")

    # Resume / overwrite
    parser.add_argument("--resume", action="store_true", help="Skip pages that already have output files")
    parser.add_argument("--overwrite", action="store_true", help="Force re-scrape and overwrite existing output files")
    
    args = parser.parse_args()
    
    # Validate worker count
    workers = max(1, min(args.workers, args.max_workers))
    if args.workers > args.max_workers:
        print(f"⚠️  Requested {args.workers} workers exceeds safety cap, using {args.max_workers}")
    
    # Force spawn method for better Playwright compatibility
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass
    
    # Calculate total pages
    total_pages = args.end_page - args.start_page + 1
    
    print(f"🚀 Batch Community Ranking Discovery")
    print(f"   Pages: {args.start_page} to {args.end_page} ({total_pages} total)")
    print(f"   Workers: {workers}, chunk size: {args.chunk_size}")
    print(f"   Browser: {args.browser_engine} (multi-engine: {args.multi_engine})")
    print(f"   Features: bandwidth_opt={args.disable_images}, proxy={args.proxy or 'None'}")
    
    # Archive existing data if this is a fresh run
    if not args.no_archive and args.start_page == 1:
        print("📦 Archiving existing data...")
        try:
            temp_scraper = CommunityRankingScraper()
            temp_scraper._archive_existing_data()
        except Exception as e:
            print(f"⚠️  Archive failed: {e}")
    
    # Distribute work across workers
    worker_assignments = distribute_page_ranges(args.start_page, args.end_page, workers, args.chunk_size)
    active_workers = [i for i, assignment in enumerate(worker_assignments) if assignment]
    
    print(f"   Active workers: {len(active_workers)}")
    
    # Prepare configuration for workers
    config_dict = {
        "headless": not args.visible,
        "proxy_server": args.proxy or os.getenv("PROXY_SERVER"),
        "browser_engine": args.browser_engine,
        "multi_engine": args.multi_engine,
        "disable_images": args.disable_images,
        "wait_for_internet": True,
        "resume": args.resume,
        "overwrite": args.overwrite,
    }
    
    start_time = time.time()
    
    # Process with parallel workers
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as executor:
        # Submit workers with ramp-up
        futures = []
        for i, worker_assignment in enumerate(worker_assignments):
            if not worker_assignment:  # Skip empty assignments
                continue
                
            # Calculate ramp-up delay
            delay = (i * args.ramp_up / max(1, len(active_workers) - 1)) if len(active_workers) > 1 else 0
            
            # Start worker after delay
            if delay > 0:
                time.sleep(delay)
            
            future = executor.submit(
                _worker_process,
                i,
                worker_assignment,
                config_dict,
                args.initial_jitter,
                args.worker_chunk_size,
            )
            futures.append(future)
            print(f"[batch] Started worker {i} (delay: {delay:.1f}s)")
        
        # Collect results
        workers_completed = 0
        total_pages_scraped = 0
        total_subreddits = 0
        total_errors = 0
        
        try:
            for future in as_completed(futures):
                result = future.result()
                workers_completed += 1
                total_pages_scraped += result["total_pages"]
                total_subreddits += result["total_subreddits"]
                total_errors += result["errors"]
                
                print(f"[batch] Worker {result['worker_id']} completed "
                      f"({workers_completed}/{len(futures)})")
                
        except KeyboardInterrupt:
            print("\n[batch] Interrupted by user, shutting down...")
            executor.shutdown(wait=False)
            return
        except Exception as e:
            print(f"\n[batch] Error during processing: {e}")
    
    # Summary
    elapsed = time.time() - start_time
    success_rate = workers_completed / len(futures) * 100 if futures else 0
    
    print(f"\n✅ Batch processing complete!")
    print(f"   Duration: {elapsed:.1f}s")
    print(f"   Workers: {workers_completed}/{len(futures)} completed ({success_rate:.1f}%)")
    print(f"   Pages: {total_pages_scraped} scraped")
    print(f"   Subreddits: {total_subreddits} discovered")
    print(f"   Errors: {total_errors}")
    
    # Save batch manifest
    save_batch_manifest(workers_completed, len(futures), total_pages_scraped, total_subreddits, total_errors)
    
    if total_subreddits > 0:
        print(f"\n📊 Run 'python3 analyze_discovery_trends.py --auto-compare' for trend analysis")


if __name__ == "__main__":
    main()
