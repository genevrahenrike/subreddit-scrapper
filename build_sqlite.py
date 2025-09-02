#!/usr/bin/env python3
"""
Build a normalized SQLite database from keyword JSONL outputs and page metadata.

Inputs:
  - Keywords JSONL files: output/keywords/page_*.keywords.jsonl
  - Page metadata JSON files: output/pages/page_*.json

Schema (normalized):
  - subreddits(community_id PK, name, url, full_url, rank, subscribers_count,
               displayed_count, description, icon_url,
               first_seen_at, last_seen_at, last_scraped_at,
               source_page, source_path,
               ingest_run_id, created_at, updated_at)
  - keywords(id PK, term UNIQUE)
  - subreddit_keywords(subreddit_id FK, keyword_id FK,
                       weight, score, source, topk_rank,
                       page, input_file, extracted_at, ingest_run_id,
                       PRIMARY KEY(subreddit_id, keyword_id))
  - ingests(id PK, run_id, input_file, file_type, page, file_hash,
            processed_at, record_count, status)

Rerun-safety:
  - Upserts update rows in place; updated_at/extracted_at refreshed.
  - A file hash is stored in ingests; unchanged files can be skipped with --skip-unchanged.

Usage examples:
  python3 build_sqlite.py --db output/reddit_keywords.sqlite \
    --keywords-glob 'output/keywords/page_*.keywords.jsonl' \
    --pages-dir output/pages --skip-unchanged

Only stdlib is used.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from typing import Dict, Iterable, List, Optional, Tuple


def sha256_of_file(path: str, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def connect_db(db_path: str) -> sqlite3.Connection:
    ensure_dir(os.path.dirname(db_path) or '.')
    conn = sqlite3.connect(db_path)
    conn.execute('PRAGMA foreign_keys = ON;')
    conn.execute('PRAGMA journal_mode = WAL;')
    conn.execute('PRAGMA synchronous = NORMAL;')
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # subreddits
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subreddits (
            community_id    TEXT PRIMARY KEY,
            name            TEXT,
            url             TEXT,
            full_url        TEXT,
            rank            INTEGER,
            subscribers_count INTEGER,
            displayed_count TEXT,
            description     TEXT,
            icon_url        TEXT,
            first_seen_at   TEXT,
            last_seen_at    TEXT,
            last_scraped_at TEXT,
            source_page     INTEGER,
            source_path     TEXT,
            ingest_run_id   TEXT,
            created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        """
    )

    # keywords
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS keywords (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            term    TEXT NOT NULL UNIQUE
        );
        """
    )

    # mapping table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subreddit_keywords (
            subreddit_id    TEXT NOT NULL,
            keyword_id      INTEGER NOT NULL,
            weight          REAL NOT NULL,
            score           REAL NOT NULL,
            source          TEXT NOT NULL,
            topk_rank       INTEGER,
            page            INTEGER,
            input_file      TEXT,
            extracted_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            ingest_run_id   TEXT,
            PRIMARY KEY (subreddit_id, keyword_id),
            FOREIGN KEY (subreddit_id) REFERENCES subreddits(community_id) ON DELETE CASCADE,
            FOREIGN KEY (keyword_id)   REFERENCES keywords(id) ON DELETE CASCADE
        );
        """
    )

    # ingests metadata
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT,
            input_file      TEXT,
            file_type       TEXT,
            page            INTEGER,
            file_hash       TEXT,
            processed_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            record_count    INTEGER,
            status          TEXT
        );
        """
    )

    # indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_keywords_term ON keywords(term);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subkw_kw ON subreddit_keywords(keyword_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subkw_sub ON subreddit_keywords(subreddit_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subs_rank ON subreddits(rank);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_subs_subs ON subreddits(subscribers_count);")

    conn.commit()


def upsert_subreddit(
    cur: sqlite3.Cursor,
    run_id: str,
    sr: Dict,
    page: Optional[int],
    source_path: Optional[str],
) -> None:
    # sr may include: community_id, name, url, full_url, rank, subscribers_count,
    # displayed_count, description, icon_url, scraped_at
    cur.execute(
        """
        INSERT INTO subreddits (
            community_id, name, url, full_url, rank, subscribers_count,
            displayed_count, description, icon_url,
            first_seen_at, last_seen_at, last_scraped_at,
            source_page, source_path, ingest_run_id, updated_at
        ) VALUES (
            :community_id, :name, :url, :full_url, :rank, :subscribers_count,
            :displayed_count, :description, :icon_url,
            :scraped_at, :scraped_at, :scraped_at,
            :page, :source_path, :ingest_run_id, strftime('%Y-%m-%dT%H:%M:%SZ','now')
        )
        ON CONFLICT(community_id) DO UPDATE SET
            name = excluded.name,
            url  = excluded.url,
            rank = excluded.rank,
            subscribers_count = excluded.subscribers_count,
            source_page = excluded.source_page,
            source_path = excluded.source_path,
            ingest_run_id = excluded.ingest_run_id,
            updated_at = excluded.updated_at,
            -- Prefer non-empty values for these optional fields
            full_url = CASE WHEN excluded.full_url IS NOT NULL AND excluded.full_url != '' THEN excluded.full_url ELSE subreddits.full_url END,
            displayed_count = CASE WHEN excluded.displayed_count IS NOT NULL AND excluded.displayed_count != '' THEN excluded.displayed_count ELSE subreddits.displayed_count END,
            description = CASE WHEN excluded.description IS NOT NULL AND excluded.description != '' THEN excluded.description ELSE subreddits.description END,
            icon_url = CASE WHEN excluded.icon_url IS NOT NULL AND excluded.icon_url != '' THEN excluded.icon_url ELSE subreddits.icon_url END,
            last_scraped_at = CASE WHEN excluded.last_scraped_at IS NOT NULL AND (subreddits.last_scraped_at IS NULL OR excluded.last_scraped_at > subreddits.last_scraped_at) THEN excluded.last_scraped_at ELSE subreddits.last_scraped_at END,
            last_seen_at = excluded.last_scraped_at,
            first_seen_at = COALESCE(subreddits.first_seen_at, excluded.first_seen_at)
        ;
        """,
        {
            'community_id': sr.get('community_id'),
            'name': sr.get('name'),
            'url': sr.get('url'),
            'full_url': sr.get('full_url') or '',
            'rank': sr.get('rank'),
            'subscribers_count': sr.get('subscribers_count'),
            'displayed_count': sr.get('displayed_count') or '',
            'description': sr.get('description') or '',
            'icon_url': sr.get('icon_url') or '',
            'scraped_at': sr.get('scraped_at') or now_iso(),
            'page': page,
            'source_path': source_path,
            'ingest_run_id': run_id,
        },
    )


def get_or_create_keyword(cur: sqlite3.Cursor, term: str) -> int:
    cur.execute("SELECT id FROM keywords WHERE term = ?", (term,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO keywords(term) VALUES (?)", (term,))
    return cur.lastrowid


def upsert_subreddit_keyword(
    cur: sqlite3.Cursor,
    run_id: str,
    community_id: str,
    keyword_id: int,
    weight: float,
    score: float,
    source: str,
    topk_rank: Optional[int],
    page: Optional[int],
    input_file: Optional[str],
    extracted_at: Optional[str],
) -> None:
    cur.execute(
        """
        INSERT INTO subreddit_keywords (
            subreddit_id, keyword_id, weight, score, source,
            topk_rank, page, input_file, extracted_at, ingest_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, strftime('%Y-%m-%dT%H:%M:%SZ','now')), ?)
        ON CONFLICT(subreddit_id, keyword_id) DO UPDATE SET
            weight = excluded.weight,
            score  = excluded.score,
            source = excluded.source,
            topk_rank = excluded.topk_rank,
            page = excluded.page,
            input_file = excluded.input_file,
            extracted_at = excluded.extracted_at,
            ingest_run_id = excluded.ingest_run_id
        ;
        """,
        (
            community_id, keyword_id, weight, score, source,
            topk_rank, page, input_file, extracted_at, run_id,
        ),
    )


def parse_page_number_from_filename(path: str) -> Optional[int]:
    m = re.search(r"page_(\d+)\.keywords\.jsonl$", os.path.basename(path))
    if not m:
        return None
    return int(m.group(1))


def load_page_metadata(pages_json_path: str) -> Dict[str, Dict]:
    """Return a dict keyed by community_id with page subreddit dicts."""
    with open(pages_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    out: Dict[str, Dict] = {}
    for sr in data.get('subreddits', []) or []:
        cid = sr.get('community_id')
        if cid:
            out[cid] = sr
    return out


def import_keywords_file(
    conn: sqlite3.Connection,
    run_id: str,
    keywords_file: str,
    pages_dir: str,
    skip_unchanged: bool,
) -> Tuple[int, int]:
    """Import one JSONL keywords file. Returns (subreddits_upserted, keyword_rows_upserted)."""
    file_hash = sha256_of_file(keywords_file)
    page_num = parse_page_number_from_filename(keywords_file)

    # Skip unchanged if requested
    cur = conn.cursor()
    if skip_unchanged:
        cur.execute(
            "SELECT id, file_hash FROM ingests WHERE input_file = ? AND file_type = 'keywords' ORDER BY processed_at DESC LIMIT 1",
            (keywords_file,),
        )
        row = cur.fetchone()
        if row and row[1] == file_hash:
            return (0, 0)

    # Load corresponding page metadata (best-effort)
    pages_path = None
    page_map: Dict[str, Dict] = {}
    if page_num is not None:
        candidate = os.path.join(pages_dir, f"page_{page_num}.json")
        if os.path.exists(candidate):
            pages_path = candidate
            page_map = load_page_metadata(candidate)

    subs_up = 0
    kw_rows = 0
    processed = 0
    status = 'ok'
    try:
        with open(keywords_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                processed += 1
                obj = json.loads(line)
                cid = obj.get('community_id')
                if not cid:
                    continue

                # Merge subreddit info from JSONL and page metadata
                sr = {
                    'community_id': cid,
                    'name': obj.get('name'),
                    'url': obj.get('url'),
                    'rank': obj.get('rank'),
                    'subscribers_count': obj.get('subscribers_count'),
                }
                page_sr = page_map.get(cid) if page_map else {}
                if page_sr:
                    # overlay extra fields
                    sr.update({
                        'full_url': page_sr.get('full_url'),
                        'displayed_count': page_sr.get('displayed_count'),
                        'description': page_sr.get('description'),
                        'icon_url': page_sr.get('icon_url'),
                        'scraped_at': page_sr.get('scraped_at'),
                    })

                upsert_subreddit(
                    cur, run_id, sr, page=page_num, source_path=pages_path or keywords_file
                )
                subs_up += 1

                # keywords array
                kws: List[Dict] = obj.get('keywords') or []
                for idx, k in enumerate(kws):
                    term = (k.get('term') or '').strip()
                    if not term:
                        continue
                    kid = get_or_create_keyword(cur, term)
                    weight = float(k.get('weight') or 0.0)
                    score = float(k.get('score') or 0.0)
                    source = k.get('source') or 'unknown'
                    upsert_subreddit_keyword(
                        cur, run_id, cid, kid, weight, score, source,
                        topk_rank=idx + 1, page=page_num,
                        input_file=keywords_file, extracted_at=None,
                    )
                    kw_rows += 1

        # record ingest row
        cur.execute(
            """
            INSERT INTO ingests (run_id, input_file, file_type, page, file_hash, record_count, status)
            VALUES (?, ?, 'keywords', ?, ?, ?, ?)
            """,
            (run_id, keywords_file, page_num, file_hash, processed, status),
        )

        conn.commit()
    except Exception as e:
        conn.rollback()
        # log failing ingest
        cur.execute(
            """
            INSERT INTO ingests (run_id, input_file, file_type, page, file_hash, record_count, status)
            VALUES (?, ?, 'keywords', ?, ?, ?, ?)
            """,
            (run_id, keywords_file, page_num, file_hash, processed, f'error:{e!r}'),
        )
        conn.commit()
        raise

    return subs_up, kw_rows


def import_pages_file(
    conn: sqlite3.Connection,
    run_id: str,
    pages_file: str,
    skip_unchanged: bool,
) -> int:
    """Optional: import/update subreddits directly from a pages JSON file."""
    file_hash = sha256_of_file(pages_file)
    # Skip unchanged
    cur = conn.cursor()
    if skip_unchanged:
        cur.execute(
            "SELECT id, file_hash FROM ingests WHERE input_file = ? AND file_type = 'pages' ORDER BY processed_at DESC LIMIT 1",
            (pages_file,),
        )
        row = cur.fetchone()
        if row and row[1] == file_hash:
            return 0

    with open(pages_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    page_num = data.get('page')
    subs = data.get('subreddits', []) or []

    updated = 0
    status = 'ok'
    processed = 0
    try:
        for sr in subs:
            processed += 1
            upsert_subreddit(
                cur, run_id, sr, page=page_num, source_path=pages_file
            )
            updated += 1

        cur.execute(
            """
            INSERT INTO ingests (run_id, input_file, file_type, page, file_hash, record_count, status)
            VALUES (?, ?, 'pages', ?, ?, ?, ?)
            """,
            (run_id, pages_file, page_num, file_hash, processed, status),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        cur.execute(
            """
            INSERT INTO ingests (run_id, input_file, file_type, page, file_hash, record_count, status)
            VALUES (?, ?, 'pages', ?, ?, ?, ?)
            """,
            (run_id, pages_file, page_num, file_hash, processed, f'error:{e!r}'),
        )
        conn.commit()
        raise

    return updated


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Import subreddit keywords and metadata into SQLite.")
    ap.add_argument('--db', default='output/reddit_keywords.sqlite', help='Path to SQLite DB file')
    ap.add_argument('--keywords-glob', default='output/keywords/page_*.keywords.jsonl', help='Glob for keywords JSONL files')
    ap.add_argument('--pages-dir', default='output/pages', help='Directory for page_*.json files')
    ap.add_argument('--also-import-pages', action='store_true', help='Also import page JSON files directly (to fill missing fields)')
    ap.add_argument('--skip-unchanged', action='store_true', help='Skip files whose content hash matches last successful ingest')
    ap.add_argument('--rebuild', action='store_true', help='Drop all tables before import')
    ap.add_argument('--dry-run', action='store_true', help='Parse but do not write to DB')
    ap.add_argument('--verbose', action='store_true', help='Verbose logging')
    args = ap.parse_args(argv)

    run_id = str(uuid.uuid4())
    if args.verbose:
        print(f"[run] run_id={run_id}")

    if args.dry_run:
        print("[dry-run] Parsing only; no DB writes.")

    conn = connect_db(args.db)

    if args.rebuild:
        cur = conn.cursor()
        cur.executescript(
            """
            DROP TABLE IF EXISTS subreddit_keywords;
            DROP TABLE IF EXISTS keywords;
            DROP TABLE IF EXISTS subreddits;
            DROP TABLE IF EXISTS ingests;
            """
        )
        conn.commit()

    init_schema(conn)

    total_subs = 0
    total_kwrows = 0

    # Optionally import pages first
    if args.also_import_pages:
        pages_files = sorted(glob.glob(os.path.join(args.pages_dir, 'page_*.json')))
        for pf in pages_files:
            if args.verbose:
                print(f"[pages] importing {pf} ...", flush=True)
            if args.dry_run:
                sha256_of_file(pf)  # touch for parity
                continue
            imported = import_pages_file(conn, run_id, pf, skip_unchanged=args.skip_unchanged)
            total_subs += imported

    # Import keywords files
    keywords_files = sorted(glob.glob(args.keywords_glob))
    for kf in keywords_files:
        if args.verbose:
            print(f"[keywords] importing {kf} ...", flush=True)
        if args.dry_run:
            sha256_of_file(kf)
            continue
        subs_up, kw_rows = import_keywords_file(
            conn, run_id, kf, args.pages_dir, skip_unchanged=args.skip_unchanged
        )
        total_subs += subs_up
        total_kwrows += kw_rows

    if args.verbose:
        print(f"[done] subreddits upserted: {total_subs:,}, keyword links upserted: {total_kwrows:,}")

    # lightweight integrity check
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM subreddits")
    n_subs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM keywords")
    n_kw = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM subreddit_keywords")
    n_links = cur.fetchone()[0]
    print(f"Imported: {n_subs} subreddits, {n_kw} keywords, {n_links} links")

    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
