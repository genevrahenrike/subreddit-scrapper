#!/usr/bin/env python3
"""
Quick benchmark to verify SentenceTransformers embedding throughput and device routing.

- Respects EMBED_DEVICE (mps|cuda|cpu) and EMBED_BATCH_SIZE env vars
- Allows switching models via --model (default: BAAI/bge-small-en-v1.5)
- Prints device info and timing for a batch encode
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List

# Ensure repo root is on sys.path for 'src' package imports
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np

try:
    import torch  # type: ignore
    _HAS_TORCH = True
except Exception:
    torch = None  # type: ignore
    _HAS_TORCH = False

# Use project embed loader to ensure identical device routing and caching
try:
    # If running from repo root
    from src.keyword_extraction.embedding import _get_embedder, _select_device  # type: ignore
    _HAS_LOCAL = True
except Exception as e:
    print(f"[bench] failed to import local embedding utils: {e}", file=sys.stderr)
    _HAS_LOCAL = False

DEFAULT_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")


def gen_terms(n: int) -> List[str]:
    base = [
        "mazda cx-5 cabin air filter",
        "toyota prius oil change interval",
        "credit card debt snowball",
        "double slit experiment physics",
        "tattoo aftercare best practice",
        "gluten free baking sourdough",
        "brawl stars new season",
        "reddit api changes discussion",
        "iphone battery health optimization",
        "valorant agent tier list",
    ]
    out: List[str] = []
    for i in range(n):
        out.append(f"{base[i % len(base)]} example {i}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=str, default=DEFAULT_MODEL, help="ST model id (e.g., BAAI/bge-small-en-v1.5, BAAI/bge-large-en-v1.5, BAAI/bge-m3)")
    ap.add_argument("--n", type=int, default=512, help="Number of terms to encode")
    ap.add_argument("--rounds", type=int, default=3, help="Rounds to average")
    args = ap.parse_args()

    if not _HAS_LOCAL:
        print("[bench] local embedding module unavailable", file=sys.stderr)
        return 2

    device = _select_device("EMBED_DEVICE")
    bs_env = os.getenv("EMBED_BATCH_SIZE")
    bs = int(bs_env) if bs_env and bs_env.isdigit() else (16 if ("large" in args.model.lower() or "m3" in args.model.lower()) else 64)

    print(f"[bench] model={args.model}")
    print(f"[bench] device={device}")
    if _HAS_TORCH:
        try:
            print(f"[bench] torch.version={torch.__version__}")
            print(f"[bench] torch.cuda.is_available={torch.cuda.is_available() if hasattr(torch, 'cuda') else False}")
            mps_avail = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            print(f"[bench] torch.mps.is_available={mps_avail}")
        except Exception:
            pass
    print(f"[bench] batch_size={bs}")
    print(f"[bench] n_terms={args.n}, rounds={args.rounds}")

    embedder = _get_embedder(args.model)
    if embedder is None:
        print("[bench] failed to load SentenceTransformer model. Check requirements and internet.", file=sys.stderr)
        return 3

    terms = gen_terms(args.n)

    # Warmup
    try:
        _ = embedder.encode(terms[:min(64, len(terms))], normalize_embeddings=True, batch_size=min(bs, 16))
    except Exception as e:
        print(f"[bench] warmup failed: {e}", file=sys.stderr)

    times = []
    for r in range(args.rounds):
        t0 = time.perf_counter()
        try:
            embs = embedder.encode(terms, normalize_embeddings=True, batch_size=bs)
        except Exception as e:
            print(f"[bench] encode failed: {e}", file=sys.stderr)
            return 4
        dt = time.perf_counter() - t0
        times.append(dt)
        embs = np.asarray(embs)
        print(f"[bench] round {r+1}: {dt:.3f}s, shape={embs.shape}")

    avg = sum(times) / len(times)
    print(f"[bench] avg_time={avg:.3f}s over {args.rounds} rounds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())