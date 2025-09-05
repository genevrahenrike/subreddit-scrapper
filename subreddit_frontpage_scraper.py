#!/usr/bin/env python3
"""
Subreddit Front Page Scraper (Headless Browser)

Scrapes https://www.reddit.com/r/<subreddit>/ front page with Playwright.
Falls back to https://old.reddit.com/r/<subreddit>/ if needed.

Saves one JSON per subreddit:
  output/subreddits/<name>/frontpage.json
Also writes HTML snapshots on failure for debugging.
"""
from __future__ import annotations

import os
import argparse
import json
import re
import time
import random
import requests
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:
    sync_playwright = None
    PlaywrightTimeoutError = Exception


# Browser profile configurations
BROWSER_PROFILES = {
    "chromium": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "sec_fetch_site": "none",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"macOS"',
    },
    "webkit": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br",
        "sec_fetch_site": "none",
        "sec_fetch_mode": "navigate",
        "sec_fetch_dest": "document",
        "priority": "u=0, i",
    },
    "firefox": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:130.0) Gecko/20100101 Firefox/130.0",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.5",
        "accept_encoding": "gzip, deflate, br, zstd",
        "sec_fetch_dest": "document",
        "sec_fetch_mode": "navigate",
        "sec_fetch_site": "none",
    }
}

DEFAULT_UA = BROWSER_PROFILES["chromium"]["user_agent"]


@dataclass
class FPConfig:
    headless: bool = True
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    user_agent: str = DEFAULT_UA
    min_delay: float = 1.0
    max_delay: float = 2.0
    max_page_seconds: float = 75.0  # Restored to original value
    max_attempts: int = 3  # Increased from 2 to 3
    # Browser profile and session options
    browser_engine: str = "chromium"  # chromium, webkit, firefox
    persistent_session: bool = False  # Use persistent user data directory
    multi_profile: bool = False  # Rotate between browser profiles
    user_data_dir: Optional[str] = None  # Custom user data directory
    # Scrolling / loading behavior
    min_posts: int = 50
    max_scroll_loops: int = 80  # Restored to original value
    scroll_step_px: int = 1600
    scroll_wait_ms: int = 900
    stagnant_loops: int = 5
    save_debug_html: bool = True
    # Promoted content handling
    include_promoted: bool = True  # Whether to include promoted/ad posts in results
    # Enhanced error handling
    retry_delay_base: float = 2.0  # Base delay for exponential backoff
    retry_connection_errors: bool = True  # Retry on connection errors
    # Bandwidth optimization
    disable_images: bool = True  # Block image downloads to save bandwidth (default enabled)
    # Internet connectivity monitoring
    wait_for_internet: bool = True  # Wait for internet connection to be restored before continuing
    internet_check_url: str = "https://www.google.com/generate_204"  # Reliable endpoint for connectivity checks
    internet_check_interval: float = 5.0  # Seconds between connectivity checks when offline


class SubredditFrontPageScraper:
    def __init__(self, config: Optional[FPConfig] = None):
        self.config = config or FPConfig(proxy_server=os.getenv("PROXY_SERVER") or None)
        self._current_profile_index = 0
        self._available_profiles = list(BROWSER_PROFILES.keys())
        random.shuffle(self._available_profiles)  # Randomize profile order

    # --------------- Browser lifecycle --------------- #
    def _start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright not installed. Run: pip install -r requirements.txt && playwright install")
        self._pw = sync_playwright().start()
        
        # Determine browser engine (use already set if available)
        if not hasattr(self, '_current_engine'):
            if self.config.multi_profile:
                engine = self._available_profiles[self._current_profile_index % len(self._available_profiles)]
                self._current_profile_index += 1
            else:
                engine = self.config.browser_engine
            self._current_engine = engine
        
        self._start_browser()

    def _get_current_browser_engine(self) -> str:
        """Get the current browser engine to use, with rotation support."""
        if self.config.multi_profile:
            # Rotate through available profiles
            engine = self._available_profiles[self._current_profile_index % len(self._available_profiles)]
            self._current_profile_index += 1
            return engine
        else:
            return self.config.browser_engine

    def _get_current_profile(self) -> Dict:
        """Get the current browser profile configuration."""
        if not hasattr(self, '_current_engine'):
            if self.config.multi_profile:
                # Rotate through available profiles
                engine = self._available_profiles[self._current_profile_index % len(self._available_profiles)]
                self._current_profile_index += 1
            else:
                engine = self.config.browser_engine
            self._current_engine = engine
        return BROWSER_PROFILES[self._current_engine]

    def _new_context(self):
        profile = self._get_current_profile()
        
        # Create context with profile-specific settings
        context_kwargs = {
            "user_agent": profile["user_agent"],
            "locale": "en-US",
            "timezone_id": "America/Los_Angeles",
            "viewport": {"width": random.randint(1280, 1440), "height": random.randint(800, 900)},
        }
        
        # Add extra headers based on browser profile
        extra_headers = {}
        for key, value in profile.items():
            if key.startswith("accept"):
                header_name = key.replace("_", "-")
                extra_headers[header_name] = value
            elif key in ["sec_fetch_site", "sec_fetch_mode", "sec_fetch_dest", "priority"]:
                header_name = key.replace("_", "-")
                extra_headers[header_name] = value
            elif key.startswith("sec_ch_ua"):
                header_name = key.replace("_", "-")
                extra_headers[header_name] = value
                
        if extra_headers:
            context_kwargs["extra_http_headers"] = extra_headers
            
        self._context = self._browser.new_context(**context_kwargs)
        
        # Block image resources if disabled to save bandwidth
        if self.config.disable_images:
            def block_images(route):
                if route.request.resource_type in ["image", "media", "imageset"]:
                    route.abort()
                else:
                    route.continue_()
            
            self._context.route("**/*", block_images)
            
        try:
            self._context.set_default_timeout(self.config.timeout_ms)
        except Exception:
            pass
        self._page = self._context.new_page()
        try:
            self._page.set_default_timeout(self.config.timeout_ms)
        except Exception:
            pass
        self._apply_stealth(self._page)

    def _stop(self):
        for attr in ["_page", "_context", "_browser", "_pw"]:
            try:
                if hasattr(self, attr) and getattr(self, attr):
                    getattr(self, attr).close() if attr in ("_page", "_browser") else getattr(self, attr).close()
            except Exception:
                pass
        try:
            if hasattr(self, "_pw") and self._pw:
                self._pw.stop()
        except Exception:
            pass

    def _recycle_browser_for_multi_profile(self):
        """Recycle browser context to switch profiles in multi-profile mode."""
        if not self.config.multi_profile:
            return
            
        try:
            # Close current page and context
            if hasattr(self, '_page') and self._page:
                self._page.close()
            if hasattr(self, '_context') and self._context:
                self._context.close()
        except Exception:
            pass
            
        # Select next engine
        next_engine = self._available_profiles[self._current_profile_index % len(self._available_profiles)]
        self._current_profile_index += 1
        current_engine = getattr(self, '_current_engine', None)
        
        if next_engine != current_engine:
            # Need to restart browser with different engine
            try:
                if hasattr(self, '_browser') and self._browser:
                    self._browser.close()
            except Exception:
                pass
            # Reset the engine and restart just the browser (not playwright)
            self._current_engine = next_engine
            self._start_browser()
        else:
            # Just create new context with same browser
            # Reset the engine to force new profile selection
            self._current_engine = next_engine
            self._new_context()

    def _start_browser(self):
        """Start just the browser (not the entire playwright instance)"""
        engine = self._current_engine
        
        # Setup launch arguments
        launch_kwargs = {
            "headless": self.config.headless,
        }
        
        # Add engine-specific args
        if engine == "chromium":
            launch_kwargs["args"] = [
                "--disable-blink-features=AutomationControlled", 
                "--no-sandbox", 
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor"
            ]
        elif engine == "webkit":
            # WebKit has fewer configuration options but we can still tune some basics
            launch_kwargs["args"] = ["--no-startup-window"]
        elif engine == "firefox":
            # Firefox has different argument handling
            launch_kwargs["args"] = ["-no-remote"]
            
        # Add proxy if specified
        if self.config.proxy_server:
            launch_kwargs["proxy"] = {"server": self.config.proxy_server}
            
        # Add persistent user data directory if enabled  
        if self.config.persistent_session and engine == "chromium":
            # Only Chromium supports user_data_dir in launch args properly
            user_data_dir = self.config.user_data_dir or f"./browser_profiles/{engine}_profile"
            Path(user_data_dir).mkdir(parents=True, exist_ok=True)
            launch_kwargs["user_data_dir"] = user_data_dir
            
        # Launch the appropriate browser
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

    # --------------- Stealth and banners --------------- #
    def _check_internet_connectivity(self) -> bool:
        """Check if internet connection is available using a reliable endpoint."""
        try:
            # Use a simple HTTP request with short timeout
            # Google's generate_204 is designed for connectivity checks - returns 204 with no content
            response = requests.get(
                self.config.internet_check_url,
                timeout=5.0,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ConnectivityCheck)"}
            )
            return response.status_code == 204 or 200 <= response.status_code < 300
        except requests.exceptions.RequestException:
            # Any request exception means no connectivity
            return False
        except Exception:
            # Any other exception, assume no connectivity
            return False

    def _wait_for_internet_connection(self):
        """Wait for internet connection to be restored, checking periodically."""
        if not self.config.wait_for_internet:
            return
            
        print(f"[internet] Checking connectivity to {self.config.internet_check_url}...")
        
        # First check - if it's working, no need to wait
        if self._check_internet_connectivity():
            print("[internet] Internet connection is working")
            return
            
        print(f"[internet] No internet connection detected. Will check every {self.config.internet_check_interval}s...")
        wait_count = 0
        max_wait_cycles = 360  # Don't wait forever, max ~30 minutes with 5s intervals
        
        while wait_count < max_wait_cycles:
            if self._check_internet_connectivity():
                print("[internet] Internet connection restored. Continuing...")
                return
                
            wait_count += 1
            if wait_count % 12 == 0:  # Print status every minute (12 * 5s intervals)
                elapsed_minutes = (wait_count * self.config.internet_check_interval) / 60
                print(f"[internet] Still waiting for connection... ({elapsed_minutes:.1f} minutes elapsed)")
            
            time.sleep(self.config.internet_check_interval)
        
        print(f"[internet] Gave up waiting for internet connection after {max_wait_cycles * self.config.internet_check_interval / 60:.1f} minutes")
        # Don't raise an exception, let the normal retry logic handle it

    def _is_internet_connectivity_error(self, error_str: str) -> bool:
        """Check if error is related to internet connectivity rather than rate limiting."""
        connectivity_patterns = [
            "ERR_INTERNET_DISCONNECTED",
            "ERR_NETWORK_CHANGED", 
            "ERR_NETWORK_ACCESS_DENIED",
            "ERR_PROXY_CONNECTION_FAILED",
            "ERR_NAME_NOT_RESOLVED",
            "ERR_ADDRESS_UNREACHABLE",
            "net::ERR_NETWORK_ACCESS_DENIED",
            "net::ERR_INTERNET_DISCONNECTED",
            "getaddrinfo ENOTFOUND",
            "ECONNREFUSED",
            "EHOSTUNREACH",
            "ENETUNREACH"
        ]
        return any(pattern in error_str for pattern in connectivity_patterns)

    def _apply_stealth(self, page):
        engine = getattr(self, '_current_engine', 'chromium')
        
        # Common stealth evasions
        common_evasions = [
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});",
            "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});",
        ]
        
        # Engine-specific evasions
        if engine == "chromium":
            common_evasions.extend([
                "window.chrome = window.chrome || { runtime: {} };",
                "Object.defineProperty(navigator, 'permissions', {get: () => ({query: () => Promise.resolve({state: 'granted'})})});",
                "Object.defineProperty(navigator, 'plugins', {get: () => [{name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'}]});",
            ])
        elif engine == "webkit":
            # Safari-specific evasions
            common_evasions.extend([
                "delete navigator.__proto__.webdriver;",
                "Object.defineProperty(navigator, 'vendor', {get: () => 'Apple Computer, Inc.'});",
                "Object.defineProperty(navigator, 'appVersion', {get: () => '5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15'});",
            ])
        elif engine == "firefox":
            # Firefox-specific evasions  
            common_evasions.extend([
                "Object.defineProperty(navigator, 'buildID', {get: () => '20100101'});",
                "Object.defineProperty(navigator, 'oscpu', {get: () => 'Intel Mac OS X 10.15'});",
            ])
            
        for js in common_evasions:
            try:
                page.add_init_script(js)
            except Exception:
                pass

    def _dismiss_banners(self):
        """Dismiss various banners and popups with human-like timing."""
        self._add_human_delay(0.2)  # Brief pause before interacting
        
        sel_try = [
            "button:has-text('Accept all')",
            "button:has-text('Accept')", 
            "button:has-text('I Agree')",
            "button:has-text('Continue')",
            "#onetrust-accept-btn-handler",
            "button[aria-label*='accept']",
            "button[aria-label*='close']",
            "[data-testid='close-button']",
            ".icon-close",
            # Reddit-specific selectors
            "button:has-text('Maybe Later')",
            "button:has-text('Not now')",
            "[aria-label='Close']",
        ]
        
        for s in sel_try:
            try:
                if self._page.is_visible(s, timeout=1000):
                    self._page.click(s)
                    self._add_human_delay(0.3)  # Pause after clicking
                    break
            except Exception:
                continue

    def _handle_mature_gate(self):
        """Attempt to bypass NSFW or mature content interstitials without login.
        Best-effort only; if login is required, we'll fallback to old.reddit later.
        """
        self._add_human_delay(0.3)  # Human-like pause before interaction
        
        gate_selectors = [
            "button:has-text('Yes')",
            "button:has-text('Continue')",
            "button:has-text('I am over 18')",
            "button:has-text('View')",
            "button[aria-label*='continue']",
            "button[data-testid='age-gate-button']",
            "[data-click-id='age_gate_continue']",
        ]
        
        for s in gate_selectors:
            try:
                if self._page.is_visible(s, timeout=2000):
                    # Add slight mouse movement before clicking for more human behavior
                    self._page.mouse.move(random.randint(100, 200), random.randint(100, 200))
                    self._add_human_delay(0.1)
                    self._page.click(s)
                    # give UI a moment to refresh
                    self._page.wait_for_timeout(random.randint(800, 1200))
                    break
            except Exception:
                continue

    # --------------- Scrape subreddit --------------- #
    def scrape_frontpage(self, name_or_url: str) -> Dict:
        sub_name, url = self._normalize_target(name_or_url)
        start = time.monotonic()
        attempts = 0
        last_error = None
        
        def _is_retryable_error(error_str: str) -> bool:
            """Check if error is worth retrying."""
            retryable_patterns = [
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_RESET", 
                "ERR_NETWORK_CHANGED",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_PROXY_CONNECTION_FAILED",
                "TimeoutError",
                "net::ERR_TIMED_OUT",
                "503 Service Unavailable",
                "502 Bad Gateway",
                "504 Gateway Timeout"
            ]
            return any(pattern in error_str for pattern in retryable_patterns)
        
        while attempts < self.config.max_attempts:
            attempts += 1
            try:
                # Try to wait for DOM first; networkidle can be too strict on reddit
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                self._dismiss_banners()
                self._handle_mature_gate()
                # Try to wait for posts in the new Reddit UI (including promoted content)
                try:
                    self._page.wait_for_selector("shreddit-post, shreddit-ad-post, div[data-testid='post-container']", timeout=15000)
                except Exception:
                    # Try a nudge scroll to trigger lazy load
                    self._page.mouse.wheel(0, self.config.scroll_step_px)
                    self._page.wait_for_timeout(self.config.scroll_wait_ms)

                # Aggressively auto-scroll to load more posts
                try:
                    self._auto_scroll_to_load_posts()
                except Exception:
                    pass
                html = self._page.content()
                soup = BeautifulSoup(html, "html.parser")
                meta = self._parse_meta(soup)
                posts = self._parse_posts_new_reddit(soup)
                if not posts or len(posts) < max(3, self.config.min_posts // 3):
                    # Fallback to old.reddit
                    posts, meta_old = self._fetch_old_reddit(sub_name)
                    if meta_old:
                        meta = {**meta, **meta_old}
                # Save debug HTML if too few posts (helps diagnose gating/lazy load issues)
                if self.config.save_debug_html and len(posts) < max(3, self.config.min_posts // 2):
                    try:
                        self._save_debug_html(sub_name)
                    except Exception:
                        pass
                return {
                    "subreddit": sub_name,
                    "url": url,
                    "meta": meta,
                    "posts": posts,
                    "scraped_at": datetime.now().isoformat(),
                }
            except Exception as e:
                last_error = str(e)
                elapsed = time.monotonic() - start
                
                # Check if this is an internet connectivity error
                if self._is_internet_connectivity_error(last_error):
                    print(f"[internet] Internet connectivity error detected: {last_error[:100]}...")
                    self._wait_for_internet_connection()
                    # Reset attempts counter when internet is restored
                    attempts = 0
                    continue
                
                # Check if we should retry based on error type and time
                should_retry = (
                    attempts < self.config.max_attempts and
                    elapsed < self.config.max_page_seconds and
                    self.config.retry_connection_errors and
                    _is_retryable_error(last_error)
                )
                
                if not should_retry:
                    break
                
                # Exponential backoff with jitter
                delay = self.config.retry_delay_base * (2 ** (attempts - 1))
                delay += random.uniform(0, delay * 0.1)  # Add 10% jitter
                delay = min(delay, 30.0)  # Cap at 30 seconds
                
                print(f"[retry] {sub_name} attempt {attempts}/{self.config.max_attempts} after {delay:.1f}s (error: {last_error[:100]})")
                time.sleep(delay)
                
                # Enhanced recovery: recycle context on connection errors for fresh fingerprint
                if "CONNECTION" in last_error or "PROXY" in last_error or attempts >= 2:
                    try:
                        print(f"[retry] Recycling browser context for fresh fingerprint")
                        self._page.close()
                        self._context.close()
                        
                        # In multi-profile mode, switch to a different profile
                        if self.config.multi_profile:
                            self._new_context()  # This will pick next profile
                        else:
                            self._new_context()  # Fresh context with same profile
                    except Exception:
                        # Fallback to just recycling the page
                        try:
                            self._page.close()
                        except Exception:
                            pass
                        self._page = self._context.new_page()
                        self._apply_stealth(self._page)
                else:
                    # Light recycle: just create new page
                    try:
                        self._page.close()
                    except Exception:
                        pass
                    self._page = self._context.new_page()
                    self._apply_stealth(self._page)
        return {
            "subreddit": sub_name,
            "url": url,
            "meta": {},
            "posts": [],
            "error": last_error or "unknown",
            "scraped_at": datetime.now().isoformat(),
        }

    def _save_debug_html(self, sub_name: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path("output/pages")
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{sub_name}_frontpage_debug_{ts}.html"
        try:
            html = self._page.content()
        except Exception:
            html = ""
        html_path.write_text(html, encoding="utf-8")

    def _get_post_count(self) -> int:
        try:
            return int(self._page.evaluate(
                "() => document.querySelectorAll('shreddit-post, shreddit-ad-post, div[data-testid=\\'post-container\\']').length"
            ))
        except Exception:
            return 0

    def _auto_scroll_to_load_posts(self):
        """Auto-scrolls the page to load additional posts until thresholds/timeouts hit."""
        started = time.monotonic()
        last_count = 0
        stagnant = 0
        loops = 0
        # Make an initial End key press to jump near bottom and trigger loads
        try:
            self._page.keyboard.press("End")
            self._page.wait_for_timeout(500)
        except Exception:
            pass
        while True:
            loops += 1
            count = self._get_post_count()
            # Stop if we've reached the target number of posts
            if count >= self.config.min_posts:
                break
            # Stop if time budget exceeded
            if (time.monotonic() - started) > self.config.max_page_seconds:
                break
            # Stop if too many loops
            if loops >= self.config.max_scroll_loops:
                break
            # Track growth; stop if not increasing for a few iterations
            if count <= last_count:
                stagnant += 1
            else:
                stagnant = 0
            if stagnant >= self.config.stagnant_loops:
                break
            last_count = count
            # Perform scroll and wait a bit for network/render
            try:
                # Scroll the last post into view to trigger lazy loading
                try:
                    last_post = self._page.locator("shreddit-post, shreddit-ad-post, div[data-testid='post-container']").last
                    last_post.scroll_into_view_if_needed()
                except Exception:
                    pass
                
                # Add human-like scroll variation
                scroll_variation = random.uniform(0.8, 1.3)
                scroll_amount = int(self.config.scroll_step_px * scroll_variation)
                
                # Sometimes do multiple smaller scrolls instead of one big one
                if random.random() < 0.3:  # 30% chance
                    for _ in range(2):
                        self._page.mouse.wheel(0, scroll_amount // 2)
                        time.sleep(random.uniform(0.1, 0.3))
                else:
                    self._page.mouse.wheel(0, scroll_amount)
                
                # Occasionally scroll to absolute bottom
                if random.random() < 0.7:  # 70% chance
                    try:
                        self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass
            except Exception:
                try:
                    self._page.evaluate("window.scrollBy(0, arguments[0])", self.config.scroll_step_px)
                except Exception:
                    pass
            # Small jitter to look more human and allow lazy-load
            sleep_ms = int(self.config.scroll_wait_ms * random.uniform(0.85, 1.25))
            self._page.wait_for_timeout(sleep_ms)
            # Wait until new posts are added (best-effort)
            try:
                self._page.wait_for_function(
                    "(prev) => document.querySelectorAll('shreddit-post, shreddit-ad-post, div[data-testid=\\'post-container\\']').length > prev",
                    arg=last_count,
                    timeout=min(5000, max(1500, self.config.scroll_wait_ms * 2))
                )
            except Exception:
                pass

    def _add_human_delay(self, base_delay: float = 0.5):
        """Add human-like delay with randomization."""
        delay = base_delay + random.uniform(0, base_delay * 0.5)
        time.sleep(delay)

    def _normalize_target(self, name_or_url: str) -> Tuple[str, str]:
        if name_or_url.startswith("http"):
            m = re.search(r"/r/([^/]+)/?", name_or_url)
            sub = m.group(1) if m else name_or_url.rstrip("/")
            return sub, name_or_url.rstrip("/")
        sub = name_or_url
        if sub.startswith("r/"):
            sub = sub[2:]
        return sub, f"https://www.reddit.com/r/{sub}"

    def _parse_meta(self, soup: BeautifulSoup) -> Dict:
        meta = {}
        # Title
        if soup.title and soup.title.string:
            meta["title"] = soup.title.string.strip()
        
        # Community details
        try:
            header = soup.find("shreddit-subreddit-header")
            if header:
                meta["description"] = header.get("description")
                meta["subscribers"] = self._to_int(header.get("subscribers"))

            # Extract online users count from faceplate-number elements
            # Look for pattern: <faceplate-number number="1375" pretty="">1.4K</faceplate-number> followed by "online"
            online_elements = soup.find_all("faceplate-number")
            for element in online_elements:
                # Check if the next text content contains "online"
                next_text = ""
                current = element
                while current and not next_text.strip():
                    current = current.next_sibling
                    if current and hasattr(current, 'get_text'):
                        next_text = current.get_text(strip=True)
                    elif current and isinstance(current, str):
                        next_text = current.strip()
                
                if "online" in next_text.lower():
                    # Extract the number from the 'number' attribute
                    online_count = element.get("number")
                    if online_count:
                        meta["online_users"] = self._to_int(online_count)
                        break

            # Fallback for created date
            created_tag = soup.find("faceplate-timeago")
            if created_tag and created_tag.has_attr('ts'):
                meta['created_timestamp'] = created_tag['ts']

        except Exception:
            pass

        # Sidebar widgets
        meta["sidebar_widgets"] = []
        try:
            sidebar = soup.select_one("#right-sidebar-contents")
            if sidebar:
                # Find all potential widget containers. This selector is more specific.
                for widget in sidebar.select("div.py-md > div.px-md"):
                    title_tag = widget.find(['h2', 'h3', 'span'], class_=re.compile(r"font-bold|text-12", re.I))
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                        
                        # Check if this widget contains multiple links (bookmarks/resources/etc)
                        bookmark_links = widget.find_all('a', href=True)
                        
                        # If we have multiple links, treat it as a links widget
                        if len(bookmark_links) >= 2:
                            bookmarks = []
                            for link in bookmark_links:
                                # Extract text more carefully to avoid duplicates from hover states
                                link_text = ""
                                
                                # Strategy 1: Look for visible i18n-translatable-text spans (not hidden)
                                visible_spans = link.find_all('span', class_=re.compile(r'i18n-translatable-text'))
                                for span in visible_spans:
                                    span_classes = span.get('class', [])
                                    if not any(cls in span_classes for cls in ['hidden', 'group-hover:block']):
                                        link_text = span.get_text(strip=True)
                                        break
                                
                                # Strategy 2: If no visible span found, take first i18n-translatable-text
                                if not link_text and visible_spans:
                                    link_text = visible_spans[0].get_text(strip=True)
                                
                                # Strategy 3: Fallback to link text, but clean up duplicates
                                if not link_text:
                                    full_text = link.get_text(strip=True)
                                    # Simple deduplication: if text repeats, take first occurrence
                                    words = full_text.split()
                                    if len(words) >= 3 and words[0] == words[len(words)//2]:
                                        # Likely duplicated, take first half
                                        link_text = " ".join(words[:len(words)//3])
                                    else:
                                        link_text = full_text
                                
                                link_href = link.get('href', '')
                                if link_text and link_href:
                                    bookmarks.append({
                                        "text": link_text,
                                        "url": link_href
                                    })
                            
                            if bookmarks:
                                meta["sidebar_widgets"].append({
                                    "title": title,
                                    "content": bookmarks
                                })
                        else:
                            # Default handling for other widgets
                            content_text = ""
                            
                            # Special handling for Community Info - extract from HTML structure
                            if "community info" in title.lower():
                                # Look for the content div with proper HTML structure
                                content_div = widget.find('div', class_=re.compile(r'i18n-translatable-text.*overflow-hidden'))
                                if content_div:
                                    # Remove SC_OFF/SC_ON comments
                                    for comment in content_div.find_all(string=lambda text: isinstance(text, str) and ('SC_OFF' in text or 'SC_ON' in text)):
                                        comment.extract()
                                    
                                    # Extract paragraphs and preserve structure with proper spacing
                                    content_parts = []
                                    for p in content_div.find_all('p'):
                                        # Use get_text with separator to preserve spaces around links
                                        p_text = p.get_text(separator=" ", strip=True)
                                        if p_text:
                                            content_parts.append(p_text)
                                    
                                    if content_parts:
                                        content_text = "\n\n".join(content_parts)
                            
                            # Fallback to generic text extraction if specific handling didn't work
                            if not content_text:
                                # Get text but exclude sub-widget titles to avoid duplication
                                content_parts = []
                                for content_element in widget.find_all(string=True, recursive=True):
                                    # A simple heuristic to filter out noisy script/style content and technical markers
                                    text = content_element.strip()
                                    if (content_element.parent.name not in ['script', 'style', 'button', 'a', 'h2', 'h3', 'span'] 
                                        and len(text) > 2 
                                        and 'SC_OFF' not in text 
                                        and 'SC_ON' not in text
                                        and text != title):  # Exclude duplicate title
                                        content_parts.append(text)
                                
                                content_text = " ".join(content_parts)
                            
                            if title and content_text and title.lower() not in ['rules', 'moderators']:
                                 meta["sidebar_widgets"].append({"title": title, "content": content_text.strip()})
        except Exception:
            pass
        
        # Rules
        meta["rules"] = []
        try:
            # More specific selector for the rules container
            rules_widget = soup.find('h2', string=re.compile("r/.* Rules"))
            if rules_widget:
                rules_container = rules_widget.find_parent('div', class_=re.compile("py-md"))
                if rules_container:
                    for rule_details in rules_container.find_all('details'):
                        summary = rule_details.find('summary')
                        description_div = rule_details.find('div', id=re.compile("rule-"))
                        if summary and description_div:
                            rule_title = summary.get_text(" ", strip=True)
                            # Strip leading number from rule title
                            rule_title = re.sub(r"^\d+\s*", "", rule_title).strip()
                            rule_desc = description_div.get_text(" ", strip=True)
                            meta["rules"].append({"title": rule_title, "description": rule_desc})
        except Exception:
            pass
            
        return meta

    def _parse_posts_new_reddit(self, soup: BeautifulSoup) -> List[Dict]:
        posts: List[Dict] = []
        # Try web components first - including promoted content (ads)
        for post in soup.find_all(["shreddit-post", "shreddit-ad-post"]):
            try:
                # Check if this is a promoted/ad post
                is_promoted = post.name == "shreddit-ad-post" or post.get("promoted") == "true"
                
                title = post.get("post-title") or post.get("title") or ""
                permalink = post.get("permalink") or ""
                score = post.get("score") or post.get("upvote-count") or ""
                comments = post.get("comment-count") or ""
                post_id = post.get("id") or ""
                post_type = post.get("post-type") or ""
                domain = post.get("domain") or ""
                author = post.get("author") or ""
                author_id = post.get("author-id") or ""
                subreddit_id = post.get("subreddit-id") or ""
                subreddit_name = post.get("subreddit-prefixed-name") or post.get("subreddit-name") or ""
                created_ts = post.get("created-timestamp") or ""
                content_href = post.get("content-href") or ""
                if not title:
                    # fallback within component
                    tnode = post.find(attrs={"data-click-id": "body"}) or post.find("a")
                    title = (tnode.get_text(strip=True) if tnode else "").strip()
                # Fix relative permalinks if needed
                if permalink and permalink.startswith("/"):
                    permalink = f"https://www.reddit.com{permalink}"
                # Extract text preview for self/text posts
                content_preview = ""
                # Try multiple selectors based on analysis of actual HTML structure
                preview_selectors = [
                    '[slot="text-body"]',        # Most reliable based on analysis
                    'div[slot="text-body"]',     # Alternative slot syntax
                    'shreddit-post-text-body',   # Original selector (keep as fallback)
                    'div[class*="text"]',        # Text-related classes
                    'p'                          # Simple paragraph elements
                ]
                
                for selector in preview_selectors:
                    try:
                        if selector == 'shreddit-post-text-body':
                            # Original logic for this specific element
                            text_body = post.find("shreddit-post-text-body")
                            if text_body:
                                preview_div = text_body.find("div", class_=re.compile(r"feed-card-text-preview|md"))
                                if preview_div:
                                    content_preview = preview_div.get_text(" ", strip=True)
                        else:
                            # Use CSS selector for other cases
                            elements = post.select(selector)
                            for elem in elements:
                                text = elem.get_text(strip=True)
                                # Only use substantial text content, avoid short labels/flairs and URLs
                                if (text and 
                                    len(text) > 20 and 
                                    not text.lower().startswith(('r/', 'u/', 'general discussion')) and
                                    not text.startswith(('http://', 'https://')) and
                                    not (text == post.get('content_href', '')) and  # Don't use if it matches content_href
                                    'http' not in text.lower()[:50]):  # Avoid any text that starts with URLs
                                    content_preview = text
                                    break
                        
                        # If we found content, stop trying other selectors
                        if content_preview:
                            break
                    except Exception:
                        continue
                # Flair texts
                flair = []
                flair_host = post.find("shreddit-post-flair")
                if flair_host:
                    for node in flair_host.find_all("div", class_=re.compile("flair-content")):
                        txt = node.get_text(" ", strip=True)
                        if txt:
                            flair.append(txt)
                # Thumbnail or media preview (best-effort)
                thumbnail_url = ""
                img = post.find("img")
                if img and img.get("src"):
                    thumbnail_url = img.get("src")
                posts.append({
                    "title": title,
                    "permalink": permalink,
                    "score": self._to_int(score),
                    "comments": self._to_int(comments),
                    "post_id": post_id,
                    "post_type": post_type,
                    "domain": domain,
                    "author": author,
                    "author_id": author_id,
                    "subreddit_id": subreddit_id,
                    "subreddit": subreddit_name,
                    "created_ts": created_ts,
                    "content_href": content_href,
                    "content_preview": content_preview,
                    "flair": flair,
                    "thumbnail_url": thumbnail_url,
                    "is_promoted": is_promoted,
                })
            except Exception:
                continue
        # Fallback to div cards (including promoted content containers)
        if not posts:
            for card in soup.select("div[data-testid='post-container']"):
                try:
                    # Check for promoted/ad indicators in the fallback section
                    is_promoted = (
                        card.get("data-promoted") == "true" or 
                        card.find(string=re.compile(r"promoted|sponsored|ad", re.I)) is not None or
                        "promoted" in " ".join(card.get("class", [])).lower() or
                        card.find("span", string=re.compile(r"promoted|sponsored|ad", re.I)) is not None
                    )
                    
                    a = card.find("a", attrs={"data-click-id": "body"}) or card.find("a", href=True)
                    title = (a.get_text(strip=True) if a else "").strip()
                    permalink = a.get("href") if a else ""
                    if permalink and permalink.startswith("/"):
                        permalink = f"https://www.reddit.com{permalink}"
                    score_node = card.find(attrs={"id": re.compile("^vote-arrows-|")}) or card.find(attrs={"aria-label": re.compile("upvote", re.I)})
                    score = ""
                    # Try to find comments link
                    comments_link = card.find("a", attrs={"data-click-id": "comments"}) or card.find("a", string=re.compile("comment", re.I))
                    comments = ""
                    if comments_link:
                        m = re.search(r"(\d+[\d,]*)", comments_link.get_text(" "))
                        if m:
                            comments = m.group(1)
                    # Try to get author from card
                    author = ""
                    author_a = card.find("a", href=re.compile(r"^/user/"))
                    if author_a:
                        author = author_a.get_text(strip=True)
                    # Enhanced content preview text within card
                    content_preview = ""
                    # Try multiple selectors based on HTML analysis
                    preview_selectors = [
                        '[slot="text-body"]',
                        'div[slot="text-body"]', 
                        'div[class*="text"]',
                        'div[class*="content"]',
                        'div[data-testid="post-content"]',
                        'p',
                        'div[class*="md"]'  # Keep original as fallback
                    ]
                    
                    for selector in preview_selectors:
                        try:
                            elements = card.select(selector)
                            for elem in elements:
                                text = elem.get_text(" ", strip=True)
                                # Only use substantial text, avoid short labels and URLs
                                if (text and 
                                    len(text) > 20 and 
                                    not text.lower().startswith(('r/', 'u/', 'general discussion')) and
                                    not text.startswith(('http://', 'https://')) and
                                    'http' not in text.lower()[:50]):  # Avoid any text that starts with URLs
                                    content_preview = text
                                    break
                            if content_preview:
                                break
                        except Exception:
                            continue
                    
                    # Original fallback if new selectors don't work
                    if not content_preview:
                        preview = card.find("div", class_=re.compile(r"line-clamp|md|RichTextJSON|text|content"))
                        if preview:
                            content_preview = preview.get_text(" ", strip=True)
                    thumb = card.find("img")
                    thumbnail_url = thumb.get("src") if thumb and thumb.get("src") else ""
                    posts.append({
                        "title": title,
                        "permalink": permalink,
                        "score": self._to_int(score),
                        "comments": self._to_int(comments),
                        "author": author,
                        "content_preview": content_preview,
                        "thumbnail_url": thumbnail_url,
                        "is_promoted": is_promoted,
                    })
                except Exception:
                    continue
        
        # Filter out promoted content if not wanted
        if not self.config.include_promoted:
            posts = [post for post in posts if not post.get("is_promoted", False)]
        
        return posts

    def _fetch_old_reddit(self, sub_name: str) -> Tuple[List[Dict], Dict]:
        url = f"https://old.reddit.com/r/{sub_name}"
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            self._page.wait_for_timeout(1500)
            html = self._page.content()
            soup = BeautifulSoup(html, "html.parser")
            posts: List[Dict] = []
            for thing in soup.select("div.thing"):
                try:
                    # Check for promoted content in old Reddit
                    is_promoted = (
                        "promoted" in thing.get("class", []) or
                        thing.find(string=re.compile(r"promoted|sponsored", re.I)) is not None
                    )
                    
                    a = thing.find("a", class_="title")
                    title = (a.get_text(strip=True) if a else "").strip()
                    permalink = a.get("href") if a else ""
                    score = thing.get("data-score") or ""
                    comments_a = thing.find("a", string=re.compile("comment"))
                    comments = ""
                    if comments_a:
                        m = re.search(r"(\d+)", comments_a.get_text(" "))
                        if m:
                            comments = m.group(1)
                    posts.append({
                        "title": title,
                        "permalink": permalink,
                        "score": self._to_int(score),
                        "comments": self._to_int(comments),
                        "is_promoted": is_promoted,
                    })
                except Exception:
                    continue
            
            # Filter out promoted content if not wanted
            if not self.config.include_promoted:
                posts = [post for post in posts if not post.get("is_promoted", False)]
                
            meta = {}
            h1 = soup.find("h1")
            if h1:
                meta["title_old"] = h1.get_text(strip=True)
            return posts, meta
        except Exception:
            return [], {}

    def save_frontpage(self, subreddit: str, data: Dict):
        out_dir = Path("output/subreddits") / subreddit
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "frontpage.json").open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _to_int(self, v) -> int:
        try:
            if v is None:
                return 0
            s = str(v).replace(",", "").strip()
            if s.endswith("k") or s.endswith("K"):
                return int(float(s[:-1]) * 1000)
            return int(re.findall(r"\d+", s)[0]) if not s.isdigit() else int(s)
        except Exception:
            return 0


def quick_demo(subs: List[str]):
    scraper = SubredditFrontPageScraper()
    scraper._start()
    try:
        for s in subs:
            data = scraper.scrape_frontpage(s)
            scraper.save_frontpage(data["subreddit"], data)
            time.sleep(random.uniform(0.8, 1.5))
    finally:
        scraper._stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape subreddit front pages with Playwright and save JSON outputs.")
    parser.add_argument("--subs", nargs="*", help="List of subreddit names or URLs (e.g., r/aww r/funny)")
    parser.add_argument("--file", type=str, help="File containing list of subreddit names (one per line)")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N subreddits in the input list")
    parser.add_argument("--min-posts", type=int, default=50, help="Target number of posts to load before stopping")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless (default)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run with visible browser window")
    parser.add_argument("--proxy", type=str, default=os.getenv("PROXY_SERVER") or None, help="Proxy server, e.g. http://user:pass@host:port")
    parser.add_argument("--debug-html", action="store_true", help="Save a debug HTML snapshot when too few posts are found")
    parser.add_argument("--include-promoted", action="store_true", default=True, help="Include promoted/ad posts in results (default)")
    parser.add_argument("--exclude-promoted", dest="include_promoted", action="store_false", help="Exclude promoted/ad posts from results")
    parser.add_argument("--overwrite", action="store_true", help="Re-scrape even if output already exists")
    parser.add_argument("--skip-failed", action="store_true", default=True, help="Only skip successfully scraped subreddits (default)")
    parser.add_argument("--skip-all", dest="skip_failed", action="store_false", help="Skip any existing output files, even failed ones")
    
    # Browser fingerprinting and profile options
    parser.add_argument("--browser-engine", choices=["chromium", "webkit", "firefox"], default="chromium", 
                        help="Browser engine to use (default: chromium)")
    parser.add_argument("--persistent-session", action="store_true", 
                        help="Use persistent browser session with cookies and cache")
    parser.add_argument("--multi-profile", action="store_true", 
                        help="Rotate between different browser profiles for better fingerprint diversity")
    parser.add_argument("--user-data-dir", type=str, 
                        help="Custom directory for persistent browser user data")
    
    # Bandwidth and connectivity options
    parser.add_argument("--enable-images", dest="disable_images", action="store_false", 
                        help="Enable image downloads (images are blocked by default to save bandwidth)")
    parser.add_argument("--disable-images", dest="disable_images", action="store_true", default=True,
                        help="Disable image downloads to save bandwidth (default)")
    parser.add_argument("--no-wait-internet", dest="wait_for_internet", action="store_false", default=True,
                        help="Don't wait for internet connection to be restored, fail immediately on connectivity issues")
    parser.add_argument("--internet-check-url", type=str, default="https://www.google.com/generate_204",
                        help="URL to use for internet connectivity checks (default: Google's generate_204)")
    parser.add_argument("--internet-check-interval", type=float, default=5.0,
                        help="Seconds between internet connectivity checks when offline (default: 5.0)")
    
    # Network priority options
    parser.add_argument("--low-priority", action="store_true",
                        help="Run with lower network and CPU priority (background mode)")
    parser.add_argument("--nice-level", type=int, default=10, choices=range(0, 20),
                        help="Process nice level when using --low-priority (0-19, higher = lower priority, default: 10)")
    
    args = parser.parse_args()

    # Apply low priority settings if requested
    if args.low_priority:
        try:
            import os
            # Set process priority to lower (nice level)
            os.nice(args.nice_level)
            print(f"[priority] Process priority lowered (nice level: {args.nice_level})")
            
            # On macOS/Unix, also try to set I/O priority if available
            try:
                import subprocess
                import sys
                # Try to use ionice if available (Linux) or equivalent
                subprocess.run(['ionice', '-c', '3', '-p', str(os.getpid())], 
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[priority] I/O priority lowered (idle class)")
            except (FileNotFoundError, subprocess.CalledProcessError):
                # ionice not available or failed, continue without it
                pass
                
        except Exception as e:
            print(f"[priority] Warning: Could not set low priority: {e}")

    # Determine target subreddits
    targets = []
    if args.file:
        try:
            with open(args.file, 'r') as f:
                targets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            print(f"Loaded {len(targets)} subreddits from {args.file}")
        except Exception as e:
            print(f"Error reading file {args.file}: {e}")
            exit(1)
    elif args.subs:
        targets = args.subs
    else:
        targets = ["r/funny", "r/AskReddit"]  # Default

    # Apply offset if specified
    if args.offset > 0:
        if args.offset >= len(targets):
            print(f"Offset {args.offset} is greater than the number of targets ({len(targets)}). Nothing to do.")
            exit(0)
        print(f"Skipping first {args.offset} subreddits (offset)")
        targets = targets[args.offset:]

    cfg = FPConfig(
        headless=args.headless,
        proxy_server=args.proxy,
        min_posts=args.min_posts,
        save_debug_html=True if args.debug_html else True,  # keep debug snapshots on by default
        include_promoted=args.include_promoted,
        browser_engine=args.browser_engine,
        persistent_session=args.persistent_session,
        multi_profile=args.multi_profile,
        user_data_dir=args.user_data_dir,
        disable_images=args.disable_images,
        wait_for_internet=args.wait_for_internet,
        internet_check_url=args.internet_check_url,
        internet_check_interval=args.internet_check_interval,
    )
    
    def already_scraped(name: str) -> bool:
        """Check if subreddit already scraped successfully."""
        if name.startswith('r/'):
            name = name[2:]
        frontpage_file = Path("output/subreddits") / name / "frontpage.json"
        if not frontpage_file.exists():
            return False
        
        if not args.skip_failed:
            # Old behavior: skip if file exists regardless of content
            return True
        
        try:
            with open(frontpage_file, 'r') as f:
                data = json.load(f)
            # Consider it scraped ONLY if no error (regardless of posts count)
            return not data.get("error")
        except Exception:
            # If we can't read the file, consider it not scraped
            return False
    
    scraper = SubredditFrontPageScraper(cfg)
    scraper._start()
    try:
        for i, target in enumerate(targets):
            if not args.overwrite and already_scraped(target):
                print(f"[skip] {target} (already exists)")
                continue
                
            # Recycle browser profile every few requests in multi-profile mode
            if cfg.multi_profile and i > 0 and i % 3 == 0:
                print(f"[profile] Switching browser profile after {i} requests")
                scraper._recycle_browser_for_multi_profile()
                
            data = scraper.scrape_frontpage(target)
            scraper.save_frontpage(data["subreddit"], data)
            posts_n = len(data.get("posts", []))
            promoted_n = len([p for p in data.get("posts", []) if p.get("is_promoted", False)])
            error = data.get("error")
            out_path = Path("output/subreddits") / data["subreddit"] / "frontpage.json"
            
            # Show which browser profile was used
            current_engine = getattr(scraper, '_current_engine', cfg.browser_engine)
            profile_info = f" [{current_engine}]" if cfg.multi_profile else ""
            
            if error:
                print(f"[saved] {out_path}{profile_info} — posts={posts_n} (promoted={promoted_n}), error={error[:100]}...")
            else:
                print(f"[saved] {out_path}{profile_info} — posts={posts_n} (promoted={promoted_n})")
            time.sleep(random.uniform(0.6, 1.1))
    finally:
        scraper._stop()
