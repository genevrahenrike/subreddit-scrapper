#!/usr/bin/env python3
"""
Threshold sweep utility for subreddit keyword outputs.

- Samples page_*.keywords.jsonl files from an input directory
- Computes score quantiles per source category
- Evaluates retention at given score thresholds:
  * share kept overall (terms passing threshold / total terms)
  * mean/median kept terms per subreddit (per-record)

Usage:
  python3 scripts/threshold_sweep.py \
    --input-dir output/keywords_10k_v24_k100 \
    --max-pages 60 \
    --seed 42 \
    --thresholds 5 10 17 48
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics as stats
from typing import Dict, List, Set


CAT_NAMES: List[str] = ["all", "posts", "posts_composed", "description", "name"]


def _choose_files(all_paths: List[str], max_pages: int, seed: int) -> List[str]:
    if max_pages <= 0 or max_pages >= len(all_paths):
        return sorted(all_paths)
    rng = random.Random(seed)
    copy = list(all_paths)
    rng.shuffle(copy)
    sel = sorted(copy[:max_pages])
    return sel


def _pct(vals: List[float], p: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, int(round(p * (len(vals) - 1)))))
    return float(vals[k])


def analyze(input_dir: str, max_pages: int, seed: int, thresholds: List[float]) -> Dict:
    files = sorted(glob.glob(f"{input_dir}/page_*.keywords.jsonl"))
    if not files:
        return {"error": f"No files matched in {input_dir}/page_*.keywords.jsonl"}
    sel = _choose_files(files, max_pages=max_pages, seed=seed)

    # Collect raw scores by category across sampled corpus
    cat_scores: Dict[str, List[float]] = {c: [] for c in CAT_NAMES}

    for p in sel:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                kws = rec.get("keywords") or []
                for kw in kws:
                    try:
                        s = float(kw.get("score") or 0.0)
                        src = str(kw.get("source") or "")
                    except Exception:
                        continue
                    cat_scores["all"].append(s)
                    parts: Set[str] = set(src.split("+"))
                    if "posts_composed" in parts:
                        cat_scores["posts_composed"].append(s)
                    if ("posts" in parts) and ("posts_composed" not in parts):
                        cat_scores["posts"].append(s)
                    if "description" in parts:
                        cat_scores["description"].append(s)
                    if "name" in parts:
                        cat_scores["name"].append(s)

    # Retention by threshold, overall and per-record (per subreddit)
    retention = {
        t: {
            c: {"kept_terms": 0, "total_terms": 0, "per_record_counts": []}
            for c in CAT_NAMES
        }
        for t in thresholds
    }

    for p in sel:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                kws = rec.get("keywords") or []
                # Build per-category score lists for this record
                cats: Dict[str, List[float]] = {c: [] for c in CAT_NAMES}
                for kw in kws:
                    try:
                        s = float(kw.get("score") or 0.0)
                        src = str(kw.get("source") or "")
                    except Exception:
                        continue
                    cats["all"].append(s)
                    parts: Set[str] = set(src.split("+"))
                    if "posts_composed" in parts:
                        cats["posts_composed"].append(s)
                    if ("posts" in parts) and ("posts_composed" not in parts):
                        cats["posts"].append(s)
                    if "description" in parts:
                        cats["description"].append(s)
                    if "name" in parts:
                        cats["name"].append(s)

                for t in thresholds:
                    for c in CAT_NAMES:
                        scores = cats[c]
                        kept = sum(1 for s in scores if s >= t)
                        retention[t][c]["kept_terms"] += kept
                        retention[t][c]["total_terms"] += len(scores)
                        retention[t][c]["per_record_counts"].append(kept)

    # Summaries
    summary = {
        "files": len(sel),
        "thresholds": {},
        "quantiles": {},
        "notes": {
            "max_pages": max_pages,
            "seed": seed,
        },
    }

    # Quantiles for each category
    for c in CAT_NAMES:
        vals = cat_scores[c]
        if not vals:
            summary["quantiles"][c] = {}
        else:
            summary["quantiles"][c] = {
                "count": len(vals),
                "p50": _pct(vals, 0.50),
                "p75": _pct(vals, 0.75),
                "p90": _pct(vals, 0.90),
                "p95": _pct(vals, 0.95),
                "p99": _pct(vals, 0.99),
                "max": max(vals),
            }

    # Retention stats for each threshold
    for t in thresholds:
        ts = {}
        for c in CAT_NAMES:
            R = retention[t][c]
            tot = R["total_terms"] or 1
            kept = R["kept_terms"]
            per_rec = R["per_record_counts"]
            ts[c] = {
                "share_kept_overall": kept / tot,
                "mean_kept_per_record": (stats.fmean(per_rec) if per_rec else 0.0),
                "median_kept_per_record": (stats.median(per_rec) if per_rec else 0.0),
            }
        summary["thresholds"][t] = ts

    return summary


def main():
    ap = argparse.ArgumentParser(description="Sweep score thresholds over keyword outputs.")
    ap.add_argument("--input-dir", required=True, help="Directory containing page_*.keywords.jsonl")
    ap.add_argument("--max-pages", type=int, default=60, help="Max page files to sample (0 = all)")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    ap.add_argument("--thresholds", type=float, nargs="+", default=[5.0, 10.0, 17.0, 48.0], help="Score thresholds to evaluate")
    args = ap.parse_args()

    thresholds = [float(x) for x in args.thresholds]
    out = analyze(args.input_dir, args.max_pages, args.seed, thresholds)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()