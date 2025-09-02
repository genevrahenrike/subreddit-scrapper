#!/usr/bin/env python3
import sys
import json
import re
from pathlib import Path
from statistics import median

def tokenize_simple(text):
    if not text:
        return []
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^0-9\w\s]+", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text.lower()).strip()
    if not text:
        return []
    return text.split()

def normalize_anchor_phrase_from_title(title):
    toks = tokenize_simple(title)
    return " ".join(toks)

def canonicalize_subreddit_key(name, url):
    if name:
        m = re.search(r"r/([^/\s]+)", name, re.IGNORECASE)
        if m:
            return m.group(1).strip("/").lower()
        name2 = name.strip().strip("/").lower()
        return re.sub(r"^r/", "", name2)
    if url:
        m = re.search(r"/r/([^/\s]+)/?", url, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    return ""

def subreddit_folder_from_name(name):
    if not name:
        return ""
    n = re.sub(r"^r/+", "", name.strip(), flags=re.IGNORECASE)
    return n.strip("/")

_anchor_cache = {}

def get_anchor_from_frontpage(folder):
    if not folder:
        return ""
    if folder in _anchor_cache:
        return _anchor_cache[folder]
    fp = Path("output/subreddits") / folder / "frontpage.json"
    out = ""
    try:
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            title = ((data.get("meta") or {}).get("title") or "").strip()
            if title:
                out = normalize_anchor_phrase_from_title(title)
    except Exception:
        out = ""
    _anchor_cache[folder] = out
    return out

def main():
    if len(sys.argv) < 2:
        print("usage: analyze_posts_composed.py path/to/page.keywords.jsonl", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    total_records = 0
    subs_with_comp = 0
    total_posts_composed_terms = 0
    ranks = []
    ratios = []
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            total_records += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue
            kws = rec.get("keywords") or []
            comp = [(i, kw) for i, kw in enumerate(kws) if "posts_composed" in (kw.get("source") or "")]
            if not comp:
                continue
            subs_with_comp += 1
            total_posts_composed_terms += len(comp)
            canon = canonicalize_subreddit_key(rec.get("name", ""), rec.get("url", ""))
            folder = subreddit_folder_from_name(rec.get("name", ""))
            anchor_phrase = get_anchor_from_frontpage(folder)
            for idx, kw in comp:
                ranks.append(idx + 1)
                t = kw.get("term", "")
                tl = t.lower()
                seed = None
                if anchor_phrase and tl.startswith(anchor_phrase + " "):
                    seed = tl[len(anchor_phrase) + 1 :]
                elif canon and tl.startswith(canon + " "):
                    seed = tl[len(canon) + 1 :]
                seed_score = None
                if seed:
                    for kw2 in kws:
                        s2 = kw2.get("source") or ""
                        if "posts" in s2 and "composed" not in s2 and kw2.get("term", "").lower() == seed:
                            try:
                                seed_score = float(kw2.get("score") or 0.0)
                            except Exception:
                                seed_score = None
                            break
                if seed_score and seed_score > 0:
                    ratio = float(kw.get("score") or 0.0) / seed_score
                    ratios.append(ratio)
                    if len(examples) < 12:
                        examples.append(
                            {
                                "sub": rec.get("name"),
                                "comp_term": kw.get("term"),
                                "comp_score": kw.get("score"),
                                "seed": seed,
                                "seed_score": seed_score,
                                "ratio": ratio,
                                "rank": idx + 1,
                            }
                        )
    rank_stats = {
        "count": len(ranks),
        "mean": (sum(ranks) / len(ranks) if ranks else None),
        "min": (min(ranks) if ranks else None),
        "max": (max(ranks) if ranks else None),
    }
    ratio_stats = {
        "count": len(ratios),
        "mean": (sum(ratios) / len(ratios) if ratios else None),
        "median": (median(ratios) if ratios else None) if ratios else None,
        "min": (min(ratios) if ratios else None),
        "max": (max(ratios) if ratios else None),
    }
    summary = {
        "input": path,
        "total_records": total_records,
        "subs_with_posts_composed": subs_with_comp,
        "total_posts_composed_terms": total_posts_composed_terms,
        "rank_stats": rank_stats,
        "ratio_stats": ratio_stats,
        "examples": examples,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()