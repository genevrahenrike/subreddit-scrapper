#!/usr/bin/env python3
"""
Local Reddit Communities Scraper (Headless Browser)

Scrapes https://www.reddit.com/best/communities/{page} using a local
headless Chromium browser via Playwright with basic stealth tweaks.

Goals:
- Keep existing ZenRows-based scraper intact
- Provide an alternative local mode using your own IP or a custom proxy
- Render JS and bypass basic bot checks with lightweight stealth

Proxy usage:
- By default, no proxy is used (your residential/local IP)
- To use a proxy, set env PROXY_SERVER to e.g. http://user:pass@host:port

Requirements:
- pip install -r requirements.txt
- playwright install chromium
"""

from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional

from bs4 import BeautifulSoup

# We import Playwright lazily to allow parser-only tests without it installed
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - only triggered if playwright missing
    sync_playwright = None
    PlaywrightTimeoutError = Exception


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class LocalScraperConfig:
    headless: bool = True
    proxy_server: Optional[str] = None  # e.g., "http://user:pass@host:port"
    timeout_ms: int = 30000
    base_url: str = "https://www.reddit.com/best/communities"
    user_agent: str = DEFAULT_UA
    min_delay: float = 1.5
    max_delay: float = 3.5
    wait_selector: str = 'div[data-community-id]'
    # Hard per-page max wall time (seconds) before recycling page/browser
    max_page_seconds: float = 45.0
    # Attempts per page before marking as failed
    max_attempts: int = 2


class LocalRedditCommunitiesScraper:
    def __init__(self, config: Optional[LocalScraperConfig] = None):
        self.config = config or LocalScraperConfig(
            proxy_server=os.getenv("PROXY_SERVER") or None,
        )
        self.all_subreddits = []  # retained for compatibility; not required
        self.total_count = 0
        self.pages_done = set()

    # ------------------------- Browser lifecycle ------------------------- #
    def _start(self):
        if sync_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install -r requirements.txt && playwright install chromium"
            )
        self._pw = sync_playwright().start()

        launch_kwargs = {
            "headless": self.config.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        }
        if self.config.proxy_server:
            launch_kwargs["proxy"] = {"server": self.config.proxy_server}

        self._browser = self._pw.chromium.launch(**launch_kwargs)

        # Create a realistic browser context
        context_kwargs = {
            "user_agent": self.config.user_agent,
            "locale": "en-US",
            "timezone_id": "America/Los_Angeles",
            "viewport": {
                "width": random.randint(1280, 1440),
                "height": random.randint(800, 900),
            },
        }
        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()
        try:
            # Apply default timeouts globally
            self._context.set_default_timeout(self.config.timeout_ms)
            self._page.set_default_timeout(self.config.timeout_ms)
        except Exception:
            pass
        self._apply_stealth(self._page)

    def _stop(self):
        try:
            if hasattr(self, "_page"):
                self._page.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_context"):
                self._context.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_browser"):
                self._browser.close()
        except Exception:
            pass
        try:
            if hasattr(self, "_pw"):
                self._pw.stop()
        except Exception:
            pass

    # ----------------------------- Stealth ------------------------------ #
    def _apply_stealth(self, page):
        # Lightweight evasions; avoids external deps
        evasions = [
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
            # Plugins & languages
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});",
            "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});",
            # Chrome runtime
            "window.chrome = window.chrome || { runtime: {} };",
            # Permissions (single line to avoid Python multiline string issues)
            "const _q = navigator.permissions.query.bind(navigator.permissions); navigator.permissions.query = (p) => (p && p.name === 'notifications' ? Promise.resolve({ state: 'denied' }) : _q(p));",
            # Navigator connection
            "Object.defineProperty(navigator, 'connection', {get: () => ({ downlink: 10, effectiveType: '4g' })});",
        ]
        for js in evasions:
            try:
                page.add_init_script(js)
            except Exception:
                pass

    # ----------------------------- Scraping ----------------------------- #
    def fetch_page_html(self, page_number: int) -> Optional[str]:
        url = f"{self.config.base_url}/{page_number}"
        start = time.monotonic()
        attempts = 0
        while attempts < self.config.max_attempts:
            attempts += 1
            try:
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                # Wait for content to render if possible
                try:
                    self._page.wait_for_selector(self.config.wait_selector, timeout=15000)
                except PlaywrightTimeoutError:
                    # Fallback: give it a little more time
                    self._page.wait_for_timeout(3000)
                return self._page.content()
            except Exception as e:
                elapsed = time.monotonic() - start
                print(f"⚠️  Attempt {attempts} failed for {url}: {e} (elapsed {elapsed:.1f}s)")
                # If we exceeded the wall time, recycle page and maybe retry
                if elapsed >= self.config.max_page_seconds or attempts >= self.config.max_attempts:
                    break
                # Recycle page before retry
                try:
                    self._page.close()
                except Exception:
                    pass
                try:
                    self._page = self._context.new_page()
                    self._apply_stealth(self._page)
                    self._page.set_default_timeout(self.config.timeout_ms)
                except Exception:
                    # If we can't recover the page, try full restart
                    try:
                        self._stop()
                    except Exception:
                        pass
                    self._start()
        print(f"❌ Giving up on {url} after {attempts} attempts and {(time.monotonic()-start):.1f}s")
        return None

    def scrape_page(self, page_number: int, delay: Optional[float] = None) -> List[Dict]:
        print(f"📄 [local] Scraping page {page_number}...")
        html = self.fetch_page_html(page_number)
        subs = self.parse_subreddit_data(html or "", page_number)
        print(f"✅ [local] Found {len(subs)} subreddits on page {page_number}")
        # Polite delay
        d = delay if delay is not None else random.uniform(self.config.min_delay, self.config.max_delay)
        time.sleep(d)
        return subs

    def scrape_all_pages(self, start_page: int = 1, end_page: int = 5, save_every: int = 2, delay: Optional[float] = None) -> List[Dict]:
        print(f"🚀 [local] Scraping from page {start_page} to {end_page}")
        start = datetime.now()
        try:
            self._start()
            for p in range(start_page, end_page + 1):
                self.scrape_and_persist_page(p, delay=delay)
                if p % save_every == 0:
                    self._write_manifest(last_page=p)
        finally:
            self._stop()

        self._write_manifest(last_page=end_page)
        elapsed = datetime.now() - start
        print(f"🎉 [local] Done. total_count={self.total_count} pages={len(self.pages_done)} in {elapsed}.")
        return self.all_subreddits

    def scrape_and_persist_page(self, page_number: int, delay: Optional[float] = None) -> List[Dict]:
        error = None
        subs: List[Dict] = []
        try:
            subs = self.scrape_page(page_number, delay=delay)
        except Exception as e:
            error = str(e)
        # Save this page only (even if empty) with error marker if needed
        self.save_page_data(page_number, subs, error=error)
        self.pages_done.add(page_number)
        self.total_count += len(subs)
        # Optionally keep a small rolling buffer rather than all
        self.all_subreddits.extend(subs)
        if len(self.all_subreddits) > 5000:
            # truncate to keep memory small; we retain only latest ~2 pages worth
            self.all_subreddits = self.all_subreddits[-1000:]
        return subs

    # ------------------------------ Parsing ----------------------------- #
    def parse_subreddit_data(self, html_content: str, page_number: int) -> List[Dict]:
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

                subreddits.append(
                    {
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
                    }
                )
            except Exception as e:
                print(f"⚠️  Parse error on page {page_number}: {e}")
                continue

        return subreddits

    # ------------------------------ Storage ----------------------------- #
    def save_data(self, filename: str):
        # Ensure output directory exists
        out_dir = os.path.dirname(filename)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        import json

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.all_subreddits, f, indent=2, ensure_ascii=False)

    # ------------------------------ Helpers ----------------------------- #
    def save_page_data(self, page_number: int, subreddits: List[Dict], error: Optional[str] = None):
        # Ensure pages directory exists
        pages_dir = os.path.join("output", "pages")
        os.makedirs(pages_dir, exist_ok=True)
        payload = {
            "page": page_number,
            "count": len(subreddits),
            "subreddits": subreddits,
            "scraped_at": datetime.now().isoformat(),
            "error": error,
        }
        path = os.path.join(pages_dir, f"page_{page_number}.json")
        import json as _json
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(payload, f, indent=2, ensure_ascii=False)
        # If we have HTML, optionally save a lightweight debug snapshot for failures
        if error and not subreddits:
            try:
                html = self._page.content()
                fail_dir = os.path.join("output", "failures")
                os.makedirs(fail_dir, exist_ok=True)
                with open(os.path.join(fail_dir, f"page_{page_number}.html"), "w", encoding="utf-8") as hf:
                    hf.write(html)
            except Exception:
                pass

    def _dedup_inplace(self):
        seen = set()
        unique: List[Dict] = []
        for item in self.all_subreddits:
            key = item.get("community_id") or (item.get("name"), item.get("url"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        self.all_subreddits = unique

    def _write_manifest(self, last_page: int):
        pages_dir = os.path.join("output", "pages")
        os.makedirs(pages_dir, exist_ok=True)
        manifest = {
            "last_page": last_page,
            "pages_done": sorted(list(self.pages_done)),
            "total": self.total_count,
            "updated_at": datetime.now().isoformat(),
            "format": "per-page",
        }
        out_path = os.path.join("output", "manifest.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                import json as _json
                _json.dump(manifest, f, indent=2)
        except Exception:
            pass


def main():
    # Simple CLI for a quick run
    cfg = LocalScraperConfig(
        headless=True,
        proxy_server=os.getenv("PROXY_SERVER") or None,
    )
    scraper = LocalRedditCommunitiesScraper(cfg)
    scraper.scrape_all_pages(start_page=1, end_page=2, save_every=1)


if __name__ == "__main__":
    main()
