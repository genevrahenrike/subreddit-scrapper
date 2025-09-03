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


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class FPConfig:
    headless: bool = True
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    user_agent: str = DEFAULT_UA
    min_delay: float = 1.0
    max_delay: float = 2.0
    max_page_seconds: float = 75.0
    max_attempts: int = 2
    # Scrolling / loading behavior
    min_posts: int = 50
    max_scroll_loops: int = 80
    scroll_step_px: int = 1600
    scroll_wait_ms: int = 900
    stagnant_loops: int = 5
    save_debug_html: bool = True


class SubredditFrontPageScraper:
    def __init__(self, config: Optional[FPConfig] = None):
        self.config = config or FPConfig(proxy_server=os.getenv("PROXY_SERVER") or None)

    # --------------- Browser lifecycle --------------- #
    def _start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright not installed. Run: pip install -r requirements.txt && playwright install chromium")
        self._pw = sync_playwright().start()
        launch_kwargs = {
            "headless": self.config.headless,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        }
        if self.config.proxy_server:
            launch_kwargs["proxy"] = {"server": self.config.proxy_server}
        self._browser = self._pw.chromium.launch(**launch_kwargs)
        self._new_context()

    def _new_context(self):
        self._context = self._browser.new_context(
            user_agent=self.config.user_agent,
            locale="en-US",
            timezone_id="America/Los_Angeles",
            viewport={"width": random.randint(1280, 1440), "height": random.randint(800, 900)},
        )
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

    # --------------- Stealth and banners --------------- #
    def _apply_stealth(self, page):
        evasions = [
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});",
            "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});",
            "Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});",
            "window.chrome = window.chrome || { runtime: {} };",
        ]
        for js in evasions:
            try:
                page.add_init_script(js)
            except Exception:
                pass

    def _dismiss_banners(self):
        sel_try = [
            "button:has-text('Accept all')",
            "button:has-text('Accept')",
            "#onetrust-accept-btn-handler",
            "button[aria-label*='accept']",
        ]
        for s in sel_try:
            try:
                if self._page.is_visible(s):
                    self._page.click(s)
                    break
            except Exception:
                continue

    def _handle_mature_gate(self):
        """Attempt to bypass NSFW or mature content interstitials without login.
        Best-effort only; if login is required, we'll fallback to old.reddit later.
        """
        gate_selectors = [
            "button:has-text('Yes')",
            "button:has-text('Continue')",
            "button:has-text('I am over 18')",
            "button[aria-label*='continue']",
        ]
        for s in gate_selectors:
            try:
                if self._page.is_visible(s):
                    self._page.click(s)
                    # give UI a moment to refresh
                    self._page.wait_for_timeout(800)
                    break
            except Exception:
                continue

    # --------------- Scrape subreddit --------------- #
    def scrape_frontpage(self, name_or_url: str) -> Dict:
        sub_name, url = self._normalize_target(name_or_url)
        start = time.monotonic()
        attempts = 0
        last_error = None
        while attempts < self.config.max_attempts:
            attempts += 1
            try:
                # Try to wait for DOM first; networkidle can be too strict on reddit
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                self._dismiss_banners()
                self._handle_mature_gate()
                # Try to wait for posts in the new Reddit UI
                try:
                    self._page.wait_for_selector("shreddit-post, div[data-testid='post-container']", timeout=15000)
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
                if elapsed >= self.config.max_page_seconds or attempts >= self.config.max_attempts:
                    break
                # Recycle page and retry
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
                "() => document.querySelectorAll('shreddit-post, div[data-testid=\\'post-container\\']').length"
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
                    last_post = self._page.locator("shreddit-post, div[data-testid='post-container']").last
                    last_post.scroll_into_view_if_needed()
                except Exception:
                    pass
                # Wheel and also scroll to bottom to ensure we hit the page end
                self._page.mouse.wheel(0, self.config.scroll_step_px)
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
                    "(prev) => document.querySelectorAll('shreddit-post, div[data-testid=\\'post-container\\']').length > prev",
                    arg=last_count,
                    timeout=min(5000, max(1500, self.config.scroll_wait_ms * 2))
                )
            except Exception:
                pass

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
        # Members count (best-effort)
        try:
            # Look for common numeric fields in sidebar-like elements
            text = soup.get_text(" ")
            m = re.search(r"(\d[\d,\. ]+)(?:\s+members|\s+readers)", text, re.I)
            if m:
                meta["members_text"] = m.group(1).strip()
        except Exception:
            pass
        return meta

    def _parse_posts_new_reddit(self, soup: BeautifulSoup) -> List[Dict]:
        posts: List[Dict] = []
        # Try web components first
        for post in soup.find_all("shreddit-post"):
            try:
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
                })
            except Exception:
                continue
        # Fallback to div cards
        if not posts:
            for card in soup.select("div[data-testid='post-container']"):
                try:
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
                    })
                except Exception:
                    continue
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
                    })
                except Exception:
                    continue
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
    parser.add_argument("--subs", nargs="*", default=["r/funny", "r/AskReddit"], help="List of subreddit names or URLs (e.g., r/aww r/funny)")
    parser.add_argument("--min-posts", type=int, default=50, help="Target number of posts to load before stopping")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless (default)")
    parser.add_argument("--no-headless", dest="headless", action="store_false", help="Run with visible browser window")
    parser.add_argument("--proxy", type=str, default=os.getenv("PROXY_SERVER") or None, help="Proxy server, e.g. http://user:pass@host:port")
    parser.add_argument("--debug-html", action="store_true", help="Save a debug HTML snapshot when too few posts are found")
    args = parser.parse_args()

    cfg = FPConfig(
        headless=args.headless,
        proxy_server=args.proxy,
        min_posts=args.min_posts,
        save_debug_html=True if args.debug_html else True,  # keep debug snapshots on by default
    )
    scraper = SubredditFrontPageScraper(cfg)
    scraper._start()
    try:
        for target in args.subs:
            data = scraper.scrape_frontpage(target)
            scraper.save_frontpage(data["subreddit"], data)
            posts_n = len(data.get("posts", []))
            error = data.get("error")
            out_path = Path("output/subreddits") / data["subreddit"] / "frontpage.json"
            if error:
                print(f"[saved] {out_path} — posts={posts_n}, error={error}")
            else:
                print(f"[saved] {out_path} — posts={posts_n}")
            time.sleep(random.uniform(0.6, 1.1))
    finally:
        scraper._stop()
