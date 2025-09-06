#!/usr/bin/env python3
"""
Quick test to verify the batch scraper fixes for async API conflicts.
"""
import sys
import multiprocessing as mp
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from batch_scrape_subreddits import _init_worker, _worker_process
from subreddit_frontpage_scraper import FPConfig

def test_worker_init():
    """Test that worker initialization works without conflicts."""
    print("Testing worker initialization...")
    try:
        _init_worker()
        print("✅ Worker initialization successful")
        return True
    except Exception as e:
        print(f"❌ Worker initialization failed: {e}")
        return False

def test_small_batch():
    """Test a very small batch with minimal targets."""
    print("Testing small batch processing...")
    
    # Set multiprocessing start method
    try:
        mp.set_start_method("spawn", force=True)
    except RuntimeError:
        pass
    
    # Create minimal test data
    targets = [(1, "test"), (2, "python")]  # Small test set
    
    try:
        result = _worker_process(
            worker_id=0,
            targets=targets,
            chunk_size=10,
            overwrite=False,
            proxy=None,
            jitter_s=0.1,
            skip_failed=True,
            multi_profile=False,
            persistent_session=False,
            browser_engine="chromium",
            user_data_dir=None,
        )
        print(f"✅ Small batch test completed: {result}")
        return True
    except Exception as e:
        print(f"❌ Small batch test failed: {e}")
        return False

if __name__ == "__main__":
    print("Running batch scraper fixes tests...")
    
    init_ok = test_worker_init()
    
    # Only run batch test if init works
    if init_ok:
        batch_ok = test_small_batch()
        if batch_ok:
            print("✅ All tests passed!")
        else:
            print("❌ Batch test failed")
    else:
        print("❌ Skipping batch test due to init failure")
