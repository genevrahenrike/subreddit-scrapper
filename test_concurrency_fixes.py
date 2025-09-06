#!/usr/bin/env python3
"""
Test script to validate concurrency and persistent profile isolation fixes.
"""
import subprocess
import sys
import time
from pathlib import Path

def test_high_concurrency():
    """Test concurrency > 8 workers."""
    print("=== Testing High Concurrency (12 workers) ===")
    
    cmd = [
        "python3", "batch_scrape_subreddits.py",
        "--start", "80000",
        "--limit", "24",  # 24 targets = 2 per worker with 12 workers
        "--concurrency", "12",
        "--chunk-size", "5",
        "--ramp-up-s", "3.0",
        "--overwrite"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        # Check if we actually got 12 workers
        if "workers=12" in result.stdout:
            print("✅ High concurrency test: PASSED - 12 workers started")
            return True
        else:
            print("❌ High concurrency test: FAILED - Expected 12 workers")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ High concurrency test: TIMEOUT")
        return False
    except Exception as e:
        print(f"❌ High concurrency test: ERROR - {e}")
        return False

def test_persistent_profile_isolation():
    """Test that persistent profiles are isolated per worker."""
    print("\n=== Testing Persistent Profile Isolation ===")
    
    # Clear any existing profiles
    profile_dir = Path("browser_profiles")
    if profile_dir.exists():
        import shutil
        shutil.rmtree(profile_dir)
    
    cmd = [
        "python3", "batch_scrape_subreddits.py", 
        "--start", "80000",
        "--limit", "8",  # 8 targets with 4 workers = 2 per worker
        "--concurrency", "4",
        "--persistent-session",
        "--browser-engine", "chromium",
        "--chunk-size", "3",
        "--ramp-up-s", "2.0",
        "--overwrite"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        # Check if worker-specific profile directories were created
        profile_dirs = list(Path("browser_profiles").glob("chromium_profile_worker_*"))
        print(f"Found profile directories: {[d.name for d in profile_dirs]}")
        
        if len(profile_dirs) >= 4:
            print("✅ Profile isolation test: PASSED - Worker-specific profiles created")
            return True
        else:
            print("❌ Profile isolation test: FAILED - Expected 4+ worker profiles")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Profile isolation test: TIMEOUT")
        return False
    except Exception as e:
        print(f"❌ Profile isolation test: ERROR - {e}")
        return False

def test_max_workers_cap():
    """Test that max-workers cap is respected."""
    print("\n=== Testing Max Workers Cap ===")
    
    cmd = [
        "python3", "batch_scrape_subreddits.py",
        "--start", "80000", 
        "--limit", "4",
        "--concurrency", "20",  # Request 20 workers
        "--max-workers", "6",   # But cap at 6
        "--ramp-up-s", "1.0",
        "--overwrite"
    ]
    
    print(f"Command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("STDOUT:")
        print(result.stdout)
        
        # Check if workers were capped at 6
        if "workers=6" in result.stdout and "exceeds safety cap" in result.stdout:
            print("✅ Max workers cap test: PASSED - Workers capped at 6")
            return True
        else:
            print("❌ Max workers cap test: FAILED - Cap not applied correctly")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ Max workers cap test: TIMEOUT")
        return False
    except Exception as e:
        print(f"❌ Max workers cap test: ERROR - {e}")
        return False

def main():
    print("Running concurrency and profile isolation tests...\n")
    
    # Change to script directory
    import os
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    
    results = []
    
    # Test 1: High concurrency
    results.append(test_high_concurrency())
    
    # Test 2: Profile isolation  
    results.append(test_persistent_profile_isolation())
    
    # Test 3: Max workers cap
    results.append(test_max_workers_cap())
    
    # Summary
    passed = sum(results)
    total = len(results)
    print(f"\n=== Test Summary ===")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
