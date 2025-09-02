#!/usr/bin/env python3
"""
Subreddit Post + Comments Scraper (Playwright)

Purpose:
  Given a subreddit (or a ranked list of subreddits already scraped via frontpage
  batch), visit individual post permalinks, extract full post body and a slice of
  the comment tree with configurable filters (age, score, type, etc.).

Input sources:
  - Existing frontpage JSON: output/subreddits/<name>/frontpage.json
  - Direct subreddit name (will live-scrape frontpage first if no cached JSON)

Outputs:
  - Per-post JSON: output/subreddits/<name>/posts/<post_id>.json
  - Per-sub manifest: output/subreddits/<name>/posts_manifest.json (append/update)

Filters (best-effort, applied pre &/or post fetch):
  - min_score: skip posts below score threshold (uses frontpage parsed score when available)
  - max_age_hours: skip posts older than threshold (uses created_ts if present)
  - allowed_post_types: restrict to e.g. ['text','image','link','video'] (based on post-type attr)
  - max_posts_per_subreddit: cap processed posts per run
  - max_comments_per_post: cap collected comment nodes
  - max_comment_depth: ignore comments deeper than this depth

Scrolling / lazy load:
  - Attempts incremental scroll & optional "More replies" button clicks until
    comment or loop limits reached.

NOTE: This is an initial implementation focused on New Reddit web-component
structure (<shreddit-post>, <shreddit-comment>). It intentionally avoids login-
gated data and advanced media extraction.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple

from bs4 import BeautifulSoup

try:  # Lazy import Playwright
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover
    sync_playwright = None
    PlaywrightTimeoutError = Exception

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class PostScrapeConfig:
    headless: bool = True
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    user_agent: str = DEFAULT_UA
    # Post selection filters
    min_score: int = 0
    max_age_hours: Optional[float] = None
    allowed_post_types: Optional[List[str]] = None  # e.g. ['text','image']
    max_posts_per_subreddit: int = 20
    # Comments limits
    max_comments_per_post: int = 150
    max_comment_depth: int = 5
    # Scrolling tuning
    comment_scroll_wait_ms: int = 800
    comment_max_scroll_loops: int = 30
    # Retry & timing
    max_post_attempts: int = 2
    save_debug_html: bool = True
    # Politeness
    min_delay: float = 0.6
    max_delay: float = 1.4


class SubredditPostsScraper:
    def __init__(self, config: Optional[PostScrapeConfig] = None):
        self.config = config or PostScrapeConfig(proxy_server=os.getenv("PROXY_SERVER") or None)

    # -------------- Browser lifecycle -------------- #
    def _start(self):
        if sync_playwright is None:
            raise RuntimeError("Playwright not installed. Install requirements and run: playwright install chromium")
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

    def _stop(self):
        for attr in ["_page", "_context", "_browser", "_pw"]:
            try:
                obj = getattr(self, attr, None)
                if obj:
                    obj.close() if hasattr(obj, "close") else None
            except Exception:
                pass
        try:
            if getattr(self, "_pw", None):
                self._pw.stop()
        except Exception:
            pass

    # -------------- Helpers -------------- #
    def _normalize_sub(self, name_or_url: str) -> str:
        s = name_or_url.strip()
        if s.startswith("http"):
            m = re.search(r"/r/([^/]+)/?", s)
            if m:
                s = m.group(1)
        if s.startswith("r/"):
            s = s[2:]
        return s

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

    def _parse_iso(self, ts: str) -> Optional[datetime]:
        if not ts:
            return None
        try:
            # Normalize timezone format if ends with +0000
            if re.match(r".*[+-]\d{4}$", ts):
                ts = ts[:-5] + ts[-5:-2] + ":" + ts[-2:]
            # Replace Z with +00:00
            ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    # -------------- Frontpage loading (for candidate posts) -------------- #
    def load_frontpage_cached(self, subreddit: str) -> Dict:
        fp_path = Path("output/subreddits") / subreddit / "frontpage.json"
        if fp_path.exists():
            try:
                return json.loads(fp_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def iter_candidates(self, subreddit: str, frontpage_data: Dict) -> Iterable[Dict]:
        posts = frontpage_data.get("posts", []) if frontpage_data else []
        for p in posts:
            yield p

    def filter_candidates(self, candidates: Iterable[Dict]) -> List[Dict]:
        out: List[Dict] = []
        now = datetime.now(timezone.utc)
        for p in candidates:
            # Score filter
            if self.config.min_score and p.get("score", 0) < self.config.min_score:
                continue
            # Post type filter
            if self.config.allowed_post_types:
                pt = (p.get("post_type") or "").lower()
                if pt and pt not in {t.lower() for t in self.config.allowed_post_types}:
                    continue
            # Age filter
            if self.config.max_age_hours and p.get("created_ts"):
                dt = self._parse_iso(p["created_ts"])
                if dt:
                    if not dt.tzinfo:
                        dt = dt.replace(tzinfo=timezone.utc)
                    age_h = (now - dt).total_seconds() / 3600.0
                    if age_h > self.config.max_age_hours:
                        continue
            out.append(p)
            if len(out) >= self.config.max_posts_per_subreddit:
                break
        return out

    # -------------- Post page scraping -------------- #
    def scrape_post(self, permalink: str) -> Dict:
        """Visit a post permalink and extract metadata + text + comments."""
        attempts = 0
        last_error = None
        if permalink.startswith("/"):
            permalink = f"https://www.reddit.com{permalink}"
        while attempts < self.config.max_post_attempts:
            attempts += 1
            try:
                self._page.goto(permalink, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
                # Try wait for shreddit-post
                try:
                    self._page.wait_for_selector("shreddit-post", timeout=15000)
                except Exception:
                    self._page.wait_for_timeout(1500)
                # Scroll a bit to trigger comment load
                self._auto_scroll_comments(target_min=10)
                html = self._page.content()
                soup = BeautifulSoup(html, "html.parser")
                post = soup.find("shreddit-post")
                post_data = self._parse_post_component(post, permalink)
                comments = self._parse_comments(soup)
                # If we haven't reached target comments, try extra scroll loops
                if len(comments) < min(25, self.config.max_comments_per_post):
                    self._auto_scroll_comments(target_min=self.config.max_comments_per_post)
                    html = self._page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    comments = self._parse_comments(soup)
                post_data["comments"] = comments[: self.config.max_comments_per_post]
                post_data["comment_count_scraped"] = len(post_data["comments"])
                post_data["scraped_at"] = datetime.utcnow().isoformat()
                return post_data
            except Exception as e:
                last_error = str(e)
                if attempts >= self.config.max_post_attempts:
                    break
        return {
            "permalink": permalink,
            "error": last_error or "unknown",
            "scraped_at": datetime.utcnow().isoformat(),
            "comments": [],
        }

    def _parse_post_component(self, node, permalink: str) -> Dict:
        data: Dict = {"permalink": permalink}
        if not node:
            return data
        # Capture broad set of attributes from shreddit-post (whitelist dashed attrs -> snake_case)
        for attr, val in node.attrs.items():
            if not isinstance(val, (str, int)):
                try:
                    val = str(val)
                except Exception:
                    continue
            key = attr.replace("-", "_")
            data[key] = val
        # Title fallback
        if not data.get("post_title"):
            t = node.get("title") or (node.find(attrs={"data-click-id": "body"}).get_text(strip=True) if node.find(attrs={"data-click-id": "body"}) else "")
            data["post_title"] = t
        # Text body
        body_text = ""
        body_div = None
        # Common id pattern: t3_<id>-post-rtjson-content
        for div in node.find_all("div", id=re.compile(r"^t3_.*-post-rtjson-content")):
            body_div = div
            break
        if not body_div:
            # Generic md content
            body_div = node.find("div", class_=re.compile(r"md"))
        if body_div:
            body_text = body_div.get_text(" ", strip=True)
        data["text_body"] = body_text
        # Status flags (locked, stickied, archived) best-effort
        try:
            status_host = node.find("shreddit-status-icons") or node
            data["is_locked"] = bool(status_host.find(class_=re.compile(r"lock-status")) and not status_host.find(class_=re.compile(r"lock-status")).get("class"," ").count("hidden"))
            data["is_stickied"] = bool(status_host.find(class_=re.compile(r"stickied-status")) and not status_host.find(class_=re.compile(r"stickied-status")).get("class"," ").count("hidden"))
            data["is_archived"] = bool(status_host.find(class_=re.compile(r"archived-status")) and not status_host.find(class_=re.compile(r"archived-status")).get("class"," ").count("hidden"))
        except Exception:
            pass
        # Media extraction (images & videos inside post scope)
        images: List[str] = []
        try:
            for img in node.find_all("img"):
                src = img.get("src")
                if src and src.startswith("http") and src not in images:
                    images.append(src)
        except Exception:
            pass
        videos: List[str] = []
        try:
            for v in node.find_all("video"):
                # prefer <source>
                src = ""
                src_tag = v.find("source")
                if src_tag and src_tag.get("src"):
                    src = src_tag.get("src")
                elif v.get("src"):
                    src = v.get("src")
                if src and src.startswith("http") and src not in videos:
                    videos.append(src)
        except Exception:
            pass
        data["media_images"] = images
        data["media_videos"] = videos
        if images:
            data.setdefault("primary_image", images[0])
        # Numeric cast
        data["score"] = self._to_int(data.get("score"))
        data["comment_count"] = self._to_int(data.get("comment_count"))
        return data

    def _parse_comments(self, soup: BeautifulSoup) -> List[Dict]:
        out: List[Dict] = []
        for c in soup.find_all("shreddit-comment"):
            try:
                cid = c.get("thingid") or c.get("id")
                depth = self._to_int(c.get("depth"))
                if self.config.max_comment_depth is not None and depth > self.config.max_comment_depth:
                    continue
                parent = c.get("parentid") or None
                author = c.get("author") or ""
                score = self._to_int(c.get("score"))
                award_count = self._to_int(c.get("award-count")) if c.get("award-count") else 0
                content_type = c.get("content-type") or ""
                # Text content div id pattern: <commentid>-post-rtjson-content
                text = ""
                text_div = c.find("div", id=re.compile(rf"{re.escape(cid or '')}.*-post-rtjson-content")) if cid else None
                if not text_div:
                    text_div = c.find("div", class_=re.compile(r"md|scalable-text"))
                if text_div:
                    text = text_div.get_text(" ", strip=True)
                # Created time: look for first <time> descendant
                created_ts = None
                tnode = c.find("time")
                if tnode and tnode.has_attr("datetime"):
                    created_ts = tnode["datetime"]
                out.append({
                    "id": cid,
                    "parent_id": parent,
                    "depth": depth,
                    "author": author,
                    "score": score,
                    "award_count": award_count,
                    "content_type": content_type,
                    "created_ts": created_ts,
                    "text": text,
                })
                if len(out) >= self.config.max_comments_per_post:
                    break
            except Exception:
                continue
        return out

    def _get_comment_count_dom(self) -> int:
        try:
            return int(self._page.evaluate("() => document.querySelectorAll('shreddit-comment').length"))
        except Exception:
            return 0

    def _auto_scroll_comments(self, target_min: int):
        loops = 0
        last_count = 0
        stagnant = 0
        target = min(self.config.max_comments_per_post, target_min)
        while loops < self.config.comment_max_scroll_loops:
            loops += 1
            count = self._get_comment_count_dom()
            if count >= target:
                break
            if count <= last_count:
                stagnant += 1
            else:
                stagnant = 0
            if stagnant >= 5:
                break
            last_count = count
            # Attempt to click 'more replies' style buttons (best-effort)
            try:
                btns = self._page.locator("button:has-text('More replies'), button:has-text('more replies'), button:has-text('more reply')")
                n = btns.count()
                if n:
                    for i in range(min(n, 2)):  # click at most 2 per loop
                        try:
                            btns.nth(i).click(timeout=1500)
                        except Exception:
                            pass
            except Exception:
                pass
            # Scroll
            try:
                self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            self._page.wait_for_timeout(int(self.config.comment_scroll_wait_ms * random.uniform(0.85, 1.25)))

    # -------------- Public orchestration -------------- #
    def scrape_subreddit_posts(self, subreddit: str, overwrite: bool = False) -> List[str]:
        sub = self._normalize_sub(subreddit)
        fp = self.load_frontpage_cached(sub)
        if not fp:
            # Optionally, import and call frontpage scraper on-demand
            try:
                from subreddit_frontpage_scraper import SubredditFrontPageScraper, FPConfig  # lazy import
                fps = SubredditFrontPageScraper(FPConfig(headless=self.config.headless, proxy_server=self.config.proxy_server))
                fps._start()
                try:
                    data = fps.scrape_frontpage(sub)
                    fps.save_frontpage(data["subreddit"], data)
                    fp = data
                finally:
                    fps._stop()
            except Exception:
                pass
        candidates = list(self.iter_candidates(sub, fp))
        filtered = self.filter_candidates(candidates)
        saved = []
        if not filtered:
            return saved
        out_dir = Path("output/subreddits") / sub / "posts"
        out_dir.mkdir(parents=True, exist_ok=True)
        for p in filtered:
            permalink = p.get("permalink") or p.get("content_href")
            if not permalink:
                continue
            post_id = p.get("post_id") or self._infer_post_id_from_permalink(permalink)
            out_path = out_dir / f"{post_id or 'unknown'}.json"
            if out_path.exists() and not overwrite:
                continue
            # Polite delay between posts
            time.sleep(random.uniform(self.config.min_delay, self.config.max_delay))
            data = self.scrape_post(permalink)
            data["subreddit"] = sub
            # Merge frontpage summary fields for context
            for k, v in p.items():
                data.setdefault(f"frontpage_{k}", v)
            out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            saved.append(str(out_path))
        self._update_sub_manifest(sub)
        return saved

    def _infer_post_id_from_permalink(self, permalink: str) -> Optional[str]:
        try:
            m = re.search(r"/comments/([a-z0-9]+)/", permalink)
            if m:
                return f"t3_{m.group(1)}"
        except Exception:
            pass
        return None

    def _update_sub_manifest(self, subreddit: str):
        sub_dir = Path("output/subreddits") / subreddit / "posts"
        manifest_path = sub_dir.parent / "posts_manifest.json"
        posts = []
        if sub_dir.exists():
            for f in sub_dir.glob("*.json"):
                try:
                    posts.append(f.name)
                except Exception:
                    continue
        manifest = {
            "subreddit": subreddit,
            "post_files": sorted(posts),
            "count": len(posts),
            "updated_at": datetime.utcnow().isoformat(),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# -------- Batch utilities (ranked order) ---------- #
def load_ranked_subs(limit: Optional[int] = None) -> List[str]:
    """Reuse logic similar to batch_scrape_subreddits to rank by best rank."""
    pages_dir = Path("output/pages")
    best_rank: Dict[str, int] = {}
    if not pages_dir.exists():
        return []
    for pp in sorted(pages_dir.glob("page_*.json")):
        try:
            data = json.loads(pp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in data.get("subreddits", []):
            nm = item.get("name") or item.get("url") or ""
            nm = nm.strip().strip("/")
            if nm.startswith("r/"):
                nm = nm[2:]
            if not nm:
                continue
            r = item.get("rank")
            try:
                r = int(r) if r is not None else None
            except Exception:
                r = None
            if r is None:
                r = 10**12
            cur = best_rank.get(nm)
            best_rank[nm] = min(cur, r) if cur is not None else r
    pairs = sorted(best_rank.items(), key=lambda x: (x[1], x[0].lower()))
    subs = [p[0] for p in pairs]
    if limit:
        subs = subs[:limit]
    return subs


def main():
    ap = argparse.ArgumentParser(description="Scrape subreddit posts + comments with filters")
    ap.add_argument("--subs", nargs="*", help="Explicit subreddit names or URLs (r/funny, https://reddit.com/r/funny)")
    ap.add_argument("--ranked", action="store_true", help="Use ranked subreddits from output/pages (ignored if --subs given)")
    ap.add_argument("--ranked-limit", type=int, default=0, help="Limit number of ranked subreddits (0=all)")
    ap.add_argument("--min-score", type=int, default=0, help="Minimum frontpage score filter")
    ap.add_argument("--max-age-hours", type=float, default=None, help="Skip posts older than this many hours")
    ap.add_argument("--allowed-types", nargs="*", default=None, help="Allowed post types (e.g. text image video link)")
    ap.add_argument("--max-posts", type=int, default=10, help="Max posts per subreddit to process")
    ap.add_argument("--max-comments", type=int, default=150, help="Max comment nodes per post")
    ap.add_argument("--max-depth", type=int, default=5, help="Max comment depth to retain")
    ap.add_argument("--overwrite", action="store_true", help="Re-scrape existing post JSON files")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    ap.add_argument("--proxy", type=str, default=os.getenv("PROXY_SERVER") or None)
    args = ap.parse_args()

    cfg = PostScrapeConfig(
        headless=args.headless,
        proxy_server=args.proxy,
        min_score=args.min_score,
        max_age_hours=args.max_age_hours,
        allowed_post_types=args.allowed_types,
        max_posts_per_subreddit=args.max_posts,
        max_comments_per_post=args.max_comments,
        max_comment_depth=args.max_depth,
    )
    scraper = SubredditPostsScraper(cfg)
    scraper._start()
    try:
        if args.subs:
            subs = args.subs
        elif args.ranked:
            subs = load_ranked_subs(limit=None if args.ranked_limit in (0, None) else args.ranked_limit)
        else:
            ap.error("Provide --subs or --ranked")
            return
        for s in subs:
            name = scraper._normalize_sub(s)
            print(f"[posts] Subreddit {name}")
            try:
                saved = scraper.scrape_subreddit_posts(name, overwrite=args.overwrite)
                print(f"  -> saved {len(saved)} posts")
            except Exception as e:
                print(f"  !! error {e}")
            # Periodically recycle context to reduce memory & fingerprinting
            try:
                scraper._page.close()
            except Exception:
                pass
            scraper._new_context()
    finally:
        scraper._stop()


if __name__ == "__main__":
    main()
