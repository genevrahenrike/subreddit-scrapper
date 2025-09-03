"""
Subreddit data processing utilities.
"""
import json
import re
from typing import Iterable

from .data_models import SubDoc
from .name_processing import extract_name_terms


def iter_subreddits_from_file(path: str) -> Iterable[SubDoc]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    subs = data.get("subreddits", []) or []
    for s in subs:
        yield SubDoc(
            community_id=s.get("community_id", ""),
            name=s.get("name", ""),
            url=s.get("url", ""),
            rank=s.get("rank"),
            subscribers_count=s.get("subscribers_count"),
            desc_text=s.get("description", "") or "",
            name_terms=extract_name_terms(s.get("name", "")),
        )


def canonicalize_subreddit_key(name: str, url: str) -> str:
    """
    Build a canonical lowercase key (e.g., 'valorant') from subreddit name or URL.
    """
    # Try name like "r/VALORANT"
    if name:
        m = re.search(r"r/([^/\s]+)", name, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip("/").lower()
        name2 = name.strip().strip("/").lower()
        return re.sub(r"^r/", "", name2)

    # Try URL like "https://www.reddit.com/r/VALORANT"
    if url:
        m = re.search(r"/r/([^/\s]+)/?", url, flags=re.IGNORECASE)
        if m:
            return m.group(1).lower()

    return ""


def subreddit_folder_from_name(name: str) -> str:
    """
    Derive folder name from display name (preserve casing if present).
    Input "r/VALORANT" -> "VALORANT"
    """
    if not name:
        return ""
    n = re.sub(r"^r/+", "", name.strip(), flags=re.IGNORECASE)
    return n.strip("/")


def subreddit_display_key(name: str, url: str) -> str:
    # Extract displayed subreddit key (preserve casing), e.g., "CX5"
    if name:
        m = re.search(r"r/([^/\s]+)", name, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip("/")
    if url:
        m = re.search(r"/r/([^/\s]+)/?", url, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip("/")
    return ""