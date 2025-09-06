#!/usr/bin/env python3
"""
Emergency cleanup script to kill lingering batch scraper processes.
Use this if Ctrl+C doesn't properly terminate all workers.
"""
import subprocess
import sys
import os

def kill_scraper_processes():
    """Find and kill any lingering batch scraper processes."""
    print("🔍 Looking for lingering scraper processes...")
    
    try:
        # Find processes containing our script names
        cmd = ["pgrep", "-f", "batch_scrape_subreddits.py|subreddit_frontpage_scraper"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            print(f"Found {len(pids)} lingering processes: {pids}")
            
            # Kill each process
            for pid in pids:
                try:
                    print(f"🔫 Killing process {pid}...")
                    subprocess.run(["kill", "-9", pid], check=True)
                    print(f"✅ Killed process {pid}")
                except subprocess.CalledProcessError:
                    print(f"❌ Failed to kill process {pid} (may have already exited)")
        else:
            print("✅ No lingering processes found")
            
    except FileNotFoundError:
        print("⚠️  pgrep not found, trying alternative method...")
        try:
            # Alternative: use ps and grep
            cmd = ["ps", "aux"]
            ps_result = subprocess.run(cmd, capture_output=True, text=True)
            
            if ps_result.returncode == 0:
                lines = ps_result.stdout.split('\n')
                scraper_lines = [line for line in lines if 'batch_scrape_subreddits.py' in line or 'subreddit_frontpage_scraper' in line]
                
                if scraper_lines:
                    print(f"Found {len(scraper_lines)} processes:")
                    for line in scraper_lines:
                        parts = line.split()
                        if len(parts) > 1:
                            pid = parts[1]
                            print(f"🔫 Killing process {pid}: {' '.join(parts[10:])}")
                            try:
                                subprocess.run(["kill", "-9", pid], check=True)
                                print(f"✅ Killed process {pid}")
                            except subprocess.CalledProcessError:
                                print(f"❌ Failed to kill process {pid}")
                else:
                    print("✅ No lingering processes found")
        except Exception as e:
            print(f"❌ Error in alternative method: {e}")

def kill_playwright_browsers():
    """Kill any lingering Playwright browser processes."""
    print("\n🌐 Looking for lingering browser processes...")
    
    browser_processes = ["chromium", "firefox", "webkit"]
    
    for browser in browser_processes:
        try:
            cmd = ["pgrep", "-f", browser]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"Found {len(pids)} {browser} processes: {pids}")
                
                for pid in pids:
                    try:
                        # Check if it's actually a Playwright browser by looking at command line
                        cmd_check = ["ps", "-p", pid, "-o", "command="]
                        check_result = subprocess.run(cmd_check, capture_output=True, text=True)
                        
                        if check_result.returncode == 0 and ("playwright" in check_result.stdout.lower() or "--remote-debugging-port" in check_result.stdout):
                            print(f"🔫 Killing {browser} browser process {pid}...")
                            subprocess.run(["kill", "-9", pid], check=True)
                            print(f"✅ Killed {browser} process {pid}")
                    except subprocess.CalledProcessError:
                        pass  # Process may have already exited
                        
        except FileNotFoundError:
            pass  # pgrep not available

def main():
    print("🚨 Emergency Scraper Process Cleanup 🚨\n")
    
    # Kill scraper processes
    kill_scraper_processes()
    
    # Kill browser processes
    kill_playwright_browsers()
    
    print("\n🧹 Cleanup completed!")
    print("💡 Tip: In the future, use Ctrl+C and wait a moment for graceful shutdown.")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print("Emergency cleanup script for lingering batch scraper processes")
        print("Usage: python3 kill_lingering_scrapers.py")
        print("\nThis script will:")
        print("- Find and kill any batch_scrape_subreddits.py processes")
        print("- Find and kill any Playwright browser processes")
        print("- Clean up zombie workers that didn't respond to Ctrl+C")
        sys.exit(0)
    
    main()
