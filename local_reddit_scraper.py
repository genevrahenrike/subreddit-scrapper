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


class LocalRedditCommunitiesScraper:
    def __init__(self, config: Optional[LocalScraperConfig] = None):
        self.config = config or LocalScraperConfig(
            proxy_server=os.getenv("PROXY_SERVER") or None,
        )
        self.all_subreddits: List[Dict] = []

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
            print(f"❌ Error navigating to {url}: {e}")
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
                subs = self.scrape_page(p, delay=delay)
                self.all_subreddits.extend(subs)
                if p % save_every == 0:
                    self.save_data(f"output/reddit_communities_progress_page_{p}.json")
        finally:
            self._stop()

        self.save_data("output/reddit_communities_complete.json")
        elapsed = datetime.now() - start
        print(f"🎉 [local] Done. {len(self.all_subreddits)} subreddits in {elapsed}.")
        return self.all_subreddits

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
