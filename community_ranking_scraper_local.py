#!/usr/bin/env python3
"""
Enhanced Reddit Community Ranking Scraper (Headless Browser)

Discovers subreddits by scraping Reddit's community ranking pages at
https://www.reddit.com/best/communities/{page} using advanced Playwright techniques
inspired by the frontpage scraper.

Key Features:
- Multi-browser engine support (Chromium, WebKit, Firefox) for better stealth
- Enhanced error handling with exponential backoff and connection monitoring
- Bandwidth optimization with image blocking and request filtering
- Historical tracking of ranking/subscriber changes with systematic archiving
- Internet connectivity monitoring and automatic recovery
- Advanced stealth techniques and fingerprint randomization
- Parallel processing support with worker isolation

Historical tracking:
- Archives existing data weekly before refresh to enable trend analysis
- Preserves ranking changes, subscriber growth, new subreddit discoveries
- Data organized by ISO week for systematic comparison

Requirements:
- pip install -r requirements.txt
- playwright install chromium (webkit firefox optional for multi-engine)
"""

from __future__ import annotations

import os
import time
import random
import json
import argparse
import asyncio
import signal
import sys
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from bs4 import BeautifulSoup

# We import Playwright lazily to allow parser-only tests without it installed
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - only triggered if playwright missing
    sync_playwright = None
    PlaywrightTimeoutError = Exception


# Browser profile configurations (borrowed from frontpage scraper)
BROWSER_PROFILES = {
    "chromium": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.9",
        "sec_fetch_site": "none",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
    },
    "webkit": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.9",
        "sec_fetch_site": "none",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
    },
    "firefox": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.5",
        "sec_fetch_dest": "document",
        "sec_fetch_mode": "navigate",
        "sec_fetch_site": "none",
    }
}

DEFAULT_UA = BROWSER_PROFILES["chromium"]["user_agent"]


@dataclass
class EnhancedScraperConfig:
    headless: bool = True
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    base_url: str = "https://www.reddit.com/best/communities"
    user_agent: str = DEFAULT_UA
    min_delay: float = 1.5
    max_delay: float = 3.5
    wait_selector: str = 'div[data-community-id]'
    max_page_seconds: float = 45.0
    max_attempts: int = 3
    
    # Enhanced browser features
    browser_engine: str = "chromium"  # chromium, webkit, firefox
    multi_engine: bool = False  # Rotate between browser engines
    disable_images: bool = True  # Block images to save bandwidth
    
    # Enhanced error handling
    retry_delay_base: float = 2.0  # Base delay for exponential backoff
    retry_connection_errors: bool = True
    connection_refused_threshold: int = 3
    
    # Internet connectivity monitoring
    wait_for_internet: bool = True
    internet_check_url: str = "https://www.google.com/generate_204"
    internet_check_interval: float = 5.0
    
    # Worker support
    worker_id: Optional[int] = None


class CommunityRankingScraper:
    """Enhanced headless browser scraper for Reddit community ranking pages"""
    
    def __init__(self, config: Optional[EnhancedScraperConfig] = None):
        self.config = config or EnhancedScraperConfig(
            proxy_server=os.getenv("PROXY_SERVER") or None,
        )
        self.all_subreddits = []
        self.total_count = 0
        self.pages_done = set()
        
        # Enhanced features tracking
        self._current_engine = self.config.browser_engine
        self._available_engines = list(BROWSER_PROFILES.keys())
        random.shuffle(self._available_engines)
        self._engine_index = 0
        self._connection_refused_count = 0
        self._last_refused_time = 0

    # ------------------------- Browser lifecycle ------------------------- #
    def _start(self):
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install -r requirements.txt && playwright install chromium"
            )
        self._pw = sync_playwright().start()
        self._start_browser()

    def _start_browser(self):
        """Start browser with current engine configuration"""
        engine = self._current_engine
        
        launch_kwargs = {
            "headless": self.config.headless,
            "args": self._get_browser_args(engine),
        }
        
        if self.config.proxy_server:
            launch_kwargs["proxy"] = {"server": self.config.proxy_server}

        # Launch appropriate browser engine
        if engine == "chromium":
            self._browser = self._pw.chromium.launch(**launch_kwargs)
        elif engine == "webkit":
            self._browser = self._pw.webkit.launch(**launch_kwargs)
        elif engine == "firefox":
            self._browser = self._pw.firefox.launch(**launch_kwargs)
        else:
            raise ValueError(f"Unsupported browser engine: {engine}")
            
        print(f"[browser] Started {engine} engine")
        self._new_context()

    def _get_browser_args(self, engine: str) -> List[str]:
        """Get browser-specific launch arguments"""
        if engine == "chromium":
            return [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor"
            ]
        elif engine == "webkit":
            return []
        elif engine == "firefox":
            return ["--no-sandbox"]
        return []

    def _new_context(self):
        """Create new browser context with current profile"""
        profile = BROWSER_PROFILES[self._current_engine]
        
        context_kwargs = {
            "user_agent": profile["user_agent"],
            "locale": "en-US",
            "timezone_id": "America/Los_Angeles",
            "viewport": {
                "width": random.randint(1280, 1440),
                "height": random.randint(800, 900),
            },
        }
        
        self._context = self._browser.new_context(**context_kwargs)
        
        # Block images to save bandwidth
        if self.config.disable_images:
            self._context.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico}", lambda route: route.abort())
        
        self._page = self._context.new_page()
        
        try:
            self._context.set_default_timeout(self.config.timeout_ms)
            self._page.set_default_timeout(self.config.timeout_ms)
        except Exception:
            pass
            
        self._apply_stealth(self._page)

    def _stop(self):
        """Clean shutdown of browser resources"""
        for attr in ["_page", "_context", "_browser", "_pw"]:
            if hasattr(self, attr):
                try:
                    getattr(self, attr).close() if attr != "_pw" else getattr(self, attr).stop()
                except Exception:
                    pass

    def _rotate_engine(self):
        """Rotate to next available browser engine"""
        if not self.config.multi_engine or len(self._available_engines) <= 1:
            return
            
        self._engine_index = (self._engine_index + 1) % len(self._available_engines)
        new_engine = self._available_engines[self._engine_index]
        
        if new_engine != self._current_engine:
            print(f"[browser] Rotating from {self._current_engine} to {new_engine}")
            try:
                self._browser.close()
            except Exception:
                pass
            self._current_engine = new_engine
            self._start_browser()

    # ----------------------------- Enhanced Stealth ----------------------------- #
    def _apply_stealth(self, page):
        """Enhanced stealth evasions based on current browser engine"""
        engine = self._current_engine
        
        # Common evasions
        common_evasions = [
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});",
            "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});",
            "window.chrome = window.chrome || { runtime: {} };",
        ]
        
        # Engine-specific evasions
        if engine == "chromium":
            common_evasions.extend([
                "Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});",
                "Object.defineProperty(navigator, 'mimeTypes', {get: () => [1, 2, 3, 4]});",
            ])
        elif engine == "webkit":
            common_evasions.extend([
                "Object.defineProperty(navigator, 'vendor', {get: () => 'Apple Computer, Inc.'});",
                "Object.defineProperty(navigator, 'appVersion', {get: () => '5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15'});",
            ])
        elif engine == "firefox":
            common_evasions.extend([
                "Object.defineProperty(navigator, 'buildID', {get: () => '20100101'});",
                "Object.defineProperty(navigator, 'product', {get: () => 'Gecko'});",
            ])
        
        for js in common_evasions:
            try:
                page.add_init_script(js)
            except Exception:
                pass

    # ----------------------------- Connectivity Monitoring ----------------------------- #
    def _check_internet_connectivity(self) -> bool:
        """Check if internet connection is available"""
        try:
            import urllib.request
            urllib.request.urlopen(self.config.internet_check_url, timeout=5)
            return True
        except Exception:
            return False

    def _wait_for_internet_connection(self):
        """Wait for internet connection to be restored"""
        if not self.config.wait_for_internet:
            return
            
        while not self._check_internet_connectivity():
            print(f"🌐 No internet connection, waiting {self.config.internet_check_interval}s...")
            time.sleep(self.config.internet_check_interval)
        print("✅ Internet connection restored")

    def _is_internet_connectivity_error(self, error_str: str) -> bool:
        """Check if error indicates internet connectivity issues"""
        connectivity_patterns = [
            "ERR_INTERNET_DISCONNECTED",
            "ERR_NETWORK_CHANGED", 
            "ERR_PROXY_CONNECTION_FAILED",
            "ECONNREFUSED",
            "EHOSTUNREACH",
            "getaddrinfo ENOTFOUND"
        ]
        return any(pattern in error_str for pattern in connectivity_patterns)

    def _is_connection_refused_error(self, error_str: str) -> bool:
        """Check if error is connection refused"""
        return "ERR_CONNECTION_REFUSED" in error_str or "ECONNREFUSED" in error_str

    # ----------------------------- Enhanced Scraping ----------------------------- #
    def fetch_page_html(self, page_number: int) -> Optional[str]:
        """Fetch page HTML with enhanced error handling and retries"""
        url = f"{self.config.base_url}/{page_number}"
        start = time.monotonic()
        
        for attempt in range(self.config.max_attempts):
            try:
                # Check for connection refused pattern
                if self._connection_refused_count >= self.config.connection_refused_threshold:
                    if time.time() - self._last_refused_time < 30:  # 30 second cooldown
                        print(f"⏳ Connection refused cooldown, waiting...")
                        time.sleep(5)
                        continue
                    else:
                        self._connection_refused_count = 0  # Reset after cooldown

                self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                
                # Wait for content to render
                try:
                    self._page.wait_for_selector(self.config.wait_selector, timeout=15000)
                except PlaywrightTimeoutError:
                    self._page.wait_for_timeout(3000)  # Fallback wait
                
                # Reset connection refused counter on success
                self._connection_refused_count = 0
                return self._page.content()
                
            except Exception as e:
                error_str = str(e)
                elapsed = time.monotonic() - start
                
                print(f"⚠️  Attempt {attempt + 1} failed for {url}: {e} (elapsed {elapsed:.1f}s)")
                
                # Handle different error types
                if self._is_internet_connectivity_error(error_str):
                    print("🌐 Internet connectivity issue detected")
                    self._wait_for_internet_connection()
                    continue
                    
                if self._is_connection_refused_error(error_str):
                    self._connection_refused_count += 1
                    self._last_refused_time = time.time()
                    print(f"🚫 Connection refused ({self._connection_refused_count}/{self.config.connection_refused_threshold})")
                    
                    if self._connection_refused_count >= self.config.connection_refused_threshold:
                        print("🔄 Threshold reached, rotating browser engine...")
                        self._rotate_engine()
                
                # Exponential backoff for retries
                if attempt < self.config.max_attempts - 1:
                    delay = self.config.retry_delay_base * (2 ** attempt)
                    jitter = random.uniform(0.5, 1.5)
                    sleep_time = delay * jitter
                    print(f"⏳ Waiting {sleep_time:.1f}s before retry...")
                    time.sleep(sleep_time)
                    
                    # Recycle page for next attempt
                    try:
                        self._page.close()
                        self._page = self._context.new_page()
                        self._apply_stealth(self._page)
                    except Exception:
                        # If page recycling fails, restart browser
                        try:
                            self._stop()
                            self._start()
                        except Exception:
                            pass

                if elapsed >= self.config.max_page_seconds:
                    break

        print(f"❌ Failed to fetch {url} after {self.config.max_attempts} attempts")
        return None

    def scrape_page(self, page_number: int, delay: Optional[float] = None) -> List[Dict]:
        """Scrape a single page with enhanced error handling"""
        print(f"📄 [enhanced] Scraping community ranking page {page_number}...")
        html = self.fetch_page_html(page_number)
        subs = self.parse_subreddit_data(html or "", page_number)
        print(f"✅ [enhanced] Found {len(subs)} subreddits on page {page_number}")
        
        # Polite delay with jitter
        d = delay if delay is not None else random.uniform(self.config.min_delay, self.config.max_delay)
        time.sleep(d)
        return subs

    def scrape_all_pages(self, start_page: int = 1, end_page: int = 5, save_every: int = 2, 
                        delay: Optional[float] = None, archive_existing: bool = True) -> List[Dict]:
        """Enhanced scraping with better error handling and progress tracking"""
        print(f"🚀 [enhanced] Community ranking discovery: pages {start_page}-{end_page}")
        print(f"   Engine: {self._current_engine}, Multi-engine: {self.config.multi_engine}")
        print(f"   Bandwidth optimization: {self.config.disable_images}")
        
        # Archive existing data before starting fresh scrape
        if archive_existing and start_page == 1:
            self._archive_existing_data()
            
        start_time = datetime.now()
        
        try:
            self._start()
            for page in range(start_page, end_page + 1):
                self.scrape_and_persist_page(page, delay=delay)
                
                if page % save_every == 0:
                    print(f"💾 Progress: {page}/{end_page} pages, {self.total_count} subreddits")
                    
                # Rotate engine periodically if multi-engine enabled
                if self.config.multi_engine and page % 10 == 0:
                    self._rotate_engine()
                    
        finally:
            self._stop()

        self._write_manifest(last_page=end_page)
        elapsed = datetime.now() - start_time
        print(f"🎉 [enhanced] Community ranking complete! {self.total_count} subreddits in {elapsed}")
        return self.all_subreddits

    def scrape_and_persist_page(self, page_number: int, delay: Optional[float] = None) -> List[Dict]:
        """Scrape and save individual page with error tracking"""
        error = None
        subs: List[Dict] = []
        
        try:
            subs = self.scrape_page(page_number, delay=delay)
        except Exception as e:
            error = str(e)
            print(f"❌ Error on page {page_number}: {error}")
        
        # Save page data with error information
        self.save_page_data(page_number, subs, error=error)
        self.pages_done.add(page_number)
        self.total_count += len(subs)
        
        # Keep memory usage reasonable
        self.all_subreddits.extend(subs)
        if len(self.all_subreddits) > 5000:
            self.all_subreddits = self.all_subreddits[-1000:]
            
        return subs

    # ------------------------------ Parsing (unchanged) ----------------------------- #
    def parse_subreddit_data(self, html_content: str, page_number: int) -> List[Dict]:
        """Parse subreddit data from HTML (keeping original logic)"""
        if not html_content:
            return []
        soup = BeautifulSoup(html_content, "html.parser")

        community_divs = soup.find_all("div", {"data-community-id": True})
        subreddits: List[Dict] = []
        
        for i, div in enumerate(community_divs):
            try:
                community_id = div.get("data-community-id")
                prefixed_name = div.get("data-prefixed-name")
                subscribers_count = div.get("data-subscribers-count")
                description = div.get("data-public-description-text", "")
                icon_url = div.get("data-icon-url", "")

                member_count_elem = div.find(
                    "h6",
                    class_="flex flex-col font-bold justify-center items-center text-12 w-2xl m-0 truncate",
                )
                displayed_count = member_count_elem.text.strip() if member_count_elem else ""

                link_elem = div.find("a", href=True)
                subreddit_url = link_elem.get("href") if link_elem else ""

                approximate_rank = ((page_number - 1) * 50) + i + 1

                subreddits.append({
                    "rank": approximate_rank,
                    "page": page_number,
                    "community_id": community_id,
                    "name": prefixed_name,
                    "url": subreddit_url,
                    "full_url": f"https://reddit.com{subreddit_url}" if subreddit_url else "",
                    "subscribers_count": int(subscribers_count) if subscribers_count else 0,
                    "displayed_count": displayed_count,
                    "description": description,
                    "icon_url": icon_url,
                    "scraped_at": datetime.now().isoformat(),
                })
            except Exception as e:
                print(f"⚠️  Parse error on page {page_number}: {e}")
                continue

        return subreddits

    # ------------------------------ Historical Tracking ----------------------------- #
    def _get_current_week_id(self) -> str:
        """Get current ISO week identifier (YYYY-WW format)"""
        now = datetime.now(timezone.utc)
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    
    def _archive_existing_data(self):
        """Archive existing pages data to historical folder for week-over-week comparison"""
        pages_dir = os.path.join("output", "pages")
        if not os.path.exists(pages_dir) or not os.listdir(pages_dir):
            print("📁 No existing data to archive")
            return
            
        week_id = self._get_current_week_id()
        archive_dir = os.path.join("output", "historical", "community_ranking", week_id)
        os.makedirs(archive_dir, exist_ok=True)
        
        # Archive pages
        pages_archive_dir = os.path.join(archive_dir, "pages")
        if os.path.exists(pages_archive_dir):
            print(f"📁 Archive for {week_id} already exists, skipping archive step")
            return
            
        print(f"📦 Archiving existing data to {archive_dir}")
        
        # Copy pages directory
        shutil.copytree(pages_dir, pages_archive_dir)
        
        # Copy manifest if it exists
        manifest_path = os.path.join("output", "manifest.json")
        if os.path.exists(manifest_path):
            shutil.copy2(manifest_path, os.path.join(archive_dir, "manifest.json"))
            
        # Create archive metadata
        archive_meta = {
            "week_id": week_id,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "source": "community_ranking_scraper_enhanced",
            "scraper_config": {
                "browser_engine": self._current_engine,
                "multi_engine": self.config.multi_engine,
                "disable_images": self.config.disable_images,
            },
            "description": "Weekly archive of community ranking data for trend analysis"
        }
        
        with open(os.path.join(archive_dir, "archive_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(archive_meta, f, indent=2, ensure_ascii=False)
            
        print(f"✅ Successfully archived data for week {week_id}")

    # ------------------------------ Storage ----------------------------- #
    def save_data(self, filename: str):
        """Save scraped data to JSON file"""
        out_dir = os.path.dirname(filename)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.all_subreddits, f, indent=2, ensure_ascii=False)

    def save_page_data(self, page_number: int, subreddits: List[Dict], error: Optional[str] = None):
        """Save individual page data with enhanced metadata"""
        pages_dir = os.path.join("output", "pages")
        os.makedirs(pages_dir, exist_ok=True)
        
        payload = {
            "page": page_number,
            "count": len(subreddits),
            "subreddits": subreddits,
            "scraped_at": datetime.now().isoformat(),
            "error": error,
            "scraper_info": {
                "version": "enhanced",
                "browser_engine": self._current_engine,
                "worker_id": self.config.worker_id,
            }
        }
        
        path = os.path.join(pages_dir, f"page_{page_number}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _write_manifest(self, last_page: int):
        """Write enhanced manifest with scraper information"""
        pages_dir = os.path.join("output", "pages")
        os.makedirs(pages_dir, exist_ok=True)
        
        week_id = self._get_current_week_id()
        manifest = {
            "last_page": last_page,
            "pages_done": sorted(list(self.pages_done)),
            "total": self.total_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "week_id": week_id,
            "format": "per-page",
            "scraper_info": {
                "version": "enhanced",
                "source": "community_ranking_scraper_enhanced",
                "browser_engine": self._current_engine,
                "multi_engine": self.config.multi_engine,
                "features": {
                    "bandwidth_optimization": self.config.disable_images,
                    "connectivity_monitoring": self.config.wait_for_internet,
                    "enhanced_stealth": True,
                    "multi_browser_support": True,
                }
            },
            "historical_tracking": {
                "enabled": True,
                "archive_location": f"output/historical/community_ranking/{week_id}",
                "description": "Data archived weekly for trend analysis"
            }
        }
        
        out_path = os.path.join("output", "manifest.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception:
            pass

    # ------------------------------ Trend Analysis (unchanged) ----------------------------- #
    def generate_weekly_comparison_report(self, current_week: Optional[str] = None, previous_week: Optional[str] = None) -> Dict:
        """Generate a comparison report between two weeks of community ranking data"""
        if not current_week:
            current_week = self._get_current_week_id()
            
        # Load current data
        current_data = self._load_week_data("output/pages")
        if not current_data:
            print("❌ No current data found")
            return {}
            
        # Find previous week data
        if not previous_week:
            historical_dir = os.path.join("output", "historical", "community_ranking")
            if os.path.exists(historical_dir):
                weeks = [d for d in os.listdir(historical_dir) if d.startswith("20") and "-W" in d]
                weeks.sort(reverse=True)
                previous_week = weeks[0] if weeks else None
                
        if not previous_week:
            print("❌ No previous week data found for comparison")
            return {}
            
        # Load previous data
        previous_data_path = os.path.join("output", "historical", "community_ranking", previous_week, "pages")
        previous_data = self._load_week_data(previous_data_path)
        
        if not previous_data:
            print(f"❌ No data found for previous week {previous_week}")
            return {}
            
        print(f"📊 Comparing {previous_week} → {current_week}")
        
        # Generate comparison
        comparison = self._compare_ranking_data(previous_data, current_data, previous_week, current_week)
        
        # Save comparison report
        report_dir = os.path.join("output", "reports", "weekly_comparison")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, f"{previous_week}_to_{current_week}.json")
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2, ensure_ascii=False)
            
        print(f"📄 Comparison report saved to {report_path}")
        return comparison
        
    def _load_week_data(self, pages_dir: str) -> Dict[str, Dict]:
        """Load all page data from a directory and return keyed by subreddit name"""
        if not os.path.exists(pages_dir):
            return {}
            
        subreddits = {}
        for filename in os.listdir(pages_dir):
            if filename.startswith("page_") and filename.endswith(".json"):
                filepath = os.path.join(pages_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        page_data = json.load(f)
                        for sub in page_data.get("subreddits", []):
                            name = sub.get("name", "").lstrip("r/")
                            if name:
                                subreddits[name] = sub
                except Exception as e:
                    print(f"⚠️ Error loading {filepath}: {e}")
                    
        return subreddits
        
    def _compare_ranking_data(self, previous: Dict, current: Dict, prev_week: str, curr_week: str) -> Dict:
        """Compare two weeks of ranking data and generate insights"""
        all_subs = set(previous.keys()) | set(current.keys())
        
        ranking_changes = []
        subscriber_changes = []
        new_subreddits = []
        disappeared_subreddits = []
        
        for sub_name in all_subs:
            prev_sub = previous.get(sub_name)
            curr_sub = current.get(sub_name)
            
            if prev_sub and curr_sub:
                # Existing subreddit - check for changes
                prev_rank = prev_sub.get("rank", 999999)
                curr_rank = curr_sub.get("rank", 999999)
                prev_subs = prev_sub.get("subscribers_count", 0)
                curr_subs = curr_sub.get("subscribers_count", 0)
                
                rank_change = prev_rank - curr_rank  # Positive = rank improved
                sub_change = curr_subs - prev_subs
                
                if rank_change != 0:
                    ranking_changes.append({
                        "name": sub_name,
                        "previous_rank": prev_rank,
                        "current_rank": curr_rank,
                        "rank_change": rank_change,
                        "subscribers_change": sub_change,
                        "current_subscribers": curr_subs
                    })
                    
                if sub_change != 0:
                    subscriber_changes.append({
                        "name": sub_name,
                        "previous_subscribers": prev_subs,
                        "current_subscribers": curr_subs,
                        "subscribers_change": sub_change,
                        "growth_rate": (sub_change / prev_subs * 100) if prev_subs > 0 else 0,
                        "current_rank": curr_rank
                    })
                    
            elif curr_sub and not prev_sub:
                # New subreddit
                new_subreddits.append({
                    "name": sub_name,
                    "rank": curr_sub.get("rank"),
                    "subscribers": curr_sub.get("subscribers_count", 0),
                    "description": curr_sub.get("description", "")
                })
                
            elif prev_sub and not curr_sub:
                # Disappeared subreddit
                disappeared_subreddits.append({
                    "name": sub_name,
                    "previous_rank": prev_sub.get("rank"),
                    "previous_subscribers": prev_sub.get("subscribers_count", 0)
                })
        
        # Sort by significance
        ranking_changes.sort(key=lambda x: abs(x["rank_change"]), reverse=True)
        subscriber_changes.sort(key=lambda x: abs(x["subscribers_change"]), reverse=True)
        new_subreddits.sort(key=lambda x: x["rank"])
        
        return {
            "comparison_period": {
                "previous_week": prev_week,
                "current_week": curr_week,
                "generated_at": datetime.now(timezone.utc).isoformat()
            },
            "summary": {
                "total_previous": len(previous),
                "total_current": len(current),
                "new_subreddits": len(new_subreddits),
                "disappeared_subreddits": len(disappeared_subreddits),
                "ranking_changes": len(ranking_changes),
                "significant_subscriber_changes": len([x for x in subscriber_changes if abs(x["subscribers_change"]) > 1000])
            },
            "ranking_changes": ranking_changes[:50],  # Top 50 ranking changes
            "subscriber_changes": subscriber_changes[:50],  # Top 50 subscriber changes
            "new_subreddits": new_subreddits,
            "disappeared_subreddits": disappeared_subreddits
        }


# ------------------------------ Worker Support ----------------------------- #
def scrape_pages_worker(worker_id: int, page_range: Tuple[int, int], config_dict: Dict) -> Dict:
    """Worker function for parallel page scraping"""
    try:
        # Ensure clean asyncio environment for worker
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.close()
        except Exception:
            pass
        
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
        except Exception:
            pass
        
        # Reconstruct config
        config = EnhancedScraperConfig(**config_dict)
        config.worker_id = worker_id
        
        # Create scraper
        scraper = CommunityRankingScraper(config)
        
        start_page, end_page = page_range
        pages_scraped = []
        total_subreddits = 0
        errors = 0
        
        print(f"[w{worker_id}] Processing pages {start_page}-{end_page}")
        
        try:
            scraper._start()
            for page in range(start_page, end_page + 1):
                try:
                    subs = scraper.scrape_and_persist_page(page)
                    pages_scraped.append(page)
                    total_subreddits += len(subs)
                except Exception as e:
                    print(f"[w{worker_id}] Error on page {page}: {e}")
                    errors += 1
        finally:
            scraper._stop()
            
        return {
            "worker_id": worker_id,
            "pages_scraped": pages_scraped,
            "total_subreddits": total_subreddits,
            "errors": errors,
        }
        
    except Exception as e:
        return {
            "worker_id": worker_id,
            "pages_scraped": [],
            "total_subreddits": 0,
            "errors": 1,
            "error": str(e)
        }


def main():
    """Enhanced CLI for community ranking discovery"""
    parser = argparse.ArgumentParser(description="Enhanced Reddit community ranking scraper with advanced features")
    
    # Basic scraping options
    parser.add_argument("--start-page", type=int, default=1, help="Starting page number")
    parser.add_argument("--end-page", type=int, default=5, help="Ending page number") 
    parser.add_argument("--save-every", type=int, default=2, help="Save progress every N pages")
    parser.add_argument("--no-archive", action="store_true", help="Skip archiving existing data")
    
    # Browser and proxy options
    parser.add_argument("--proxy", help="Proxy server (overrides PROXY_SERVER env var)")
    parser.add_argument("--browser-engine", choices=["chromium", "webkit", "firefox"], 
                       default="chromium", help="Browser engine to use")
    parser.add_argument("--multi-engine", action="store_true", 
                       help="Rotate between browser engines for better stealth")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser in headless mode")
    parser.add_argument("--visible", action="store_true", help="Run browser in visible mode")
    
    # Enhanced features
    parser.add_argument("--disable-images", action="store_true", default=True,
                       help="Block images to save bandwidth (default)")
    parser.add_argument("--enable-images", dest="disable_images", action="store_false",
                       help="Enable image downloads")
    parser.add_argument("--no-wait-internet", dest="wait_for_internet", action="store_false",
                       default=True, help="Don't wait for internet connection recovery")
    
    # Parallel processing
    parser.add_argument("--workers", type=int, default=1, 
                       help="Number of parallel worker processes (1=sequential)")
    parser.add_argument("--chunk-size", type=int, default=20,
                       help="Pages per worker when using parallel processing")
    
    args = parser.parse_args()
    
    # Create enhanced configuration
    config = EnhancedScraperConfig(
        headless=not args.visible,
        proxy_server=args.proxy or os.getenv("PROXY_SERVER") or None,
        browser_engine=args.browser_engine,
        multi_engine=args.multi_engine,
        disable_images=args.disable_images,
        wait_for_internet=args.wait_for_internet,
    )
    
    print(f"🚀 Enhanced Community Ranking Discovery")
    print(f"   Pages: {args.start_page} to {args.end_page}")
    print(f"   Archive existing: {not args.no_archive}")
    print(f"   Browser: {config.browser_engine} (multi-engine: {config.multi_engine})")
    print(f"   Proxy: {config.proxy_server or 'None (local IP)'}")
    print(f"   Features: images={'enabled' if not config.disable_images else 'blocked'}, connectivity_monitoring={config.wait_for_internet}")
    
    if args.workers > 1:
        # Parallel processing with workers
        print(f"   Workers: {args.workers} (chunk size: {args.chunk_size})")
        
        from concurrent.futures import ProcessPoolExecutor
        
        # Split page range into chunks for workers
        total_pages = args.end_page - args.start_page + 1
        pages_per_worker = max(1, args.chunk_size)
        
        page_ranges = []
        for start in range(args.start_page, args.end_page + 1, pages_per_worker):
            end = min(start + pages_per_worker - 1, args.end_page)
            page_ranges.append((start, end))
        
        print(f"   Page allocation: {page_ranges}")
        
        # Convert config to dict for worker serialization
        config_dict = {
            "headless": config.headless,
            "proxy_server": config.proxy_server,
            "browser_engine": config.browser_engine,
            "multi_engine": config.multi_engine,
            "disable_images": config.disable_images,
            "wait_for_internet": config.wait_for_internet,
        }
        
        try:
            with ProcessPoolExecutor(max_workers=args.workers) as executor:
                futures = [
                    executor.submit(scrape_pages_worker, i, page_range, config_dict)
                    for i, page_range in enumerate(page_ranges)
                ]
                
                total_subreddits = 0
                total_errors = 0
                
                for future in futures:
                    result = future.result()
                    worker_id = result["worker_id"]
                    pages = result["pages_scraped"]
                    subs = result["total_subreddits"]
                    errors = result["errors"]
                    
                    print(f"[w{worker_id}] Completed: {len(pages)} pages, {subs} subreddits, {errors} errors")
                    total_subreddits += subs
                    total_errors += errors
                
                print(f"\n✅ Parallel processing complete!")
                print(f"   Total subreddits: {total_subreddits}")
                print(f"   Total errors: {total_errors}")
                
        except Exception as e:
            print(f"❌ Parallel processing failed: {e}")
            return
    else:
        # Sequential processing
        scraper = CommunityRankingScraper(config)
        scraper.scrape_all_pages(
            start_page=args.start_page,
            end_page=args.end_page,
            save_every=args.save_every,
            archive_existing=not args.no_archive
        )
    
    print(f"\n✅ Discovery complete! Check output/pages/ for current data")
    print(f"📊 Run 'python3 analyze_community_ranking_trends.py --auto-compare' for trend analysis")


if __name__ == "__main__":
    main()
