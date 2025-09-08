devlog - discovery scraper

---
Weekly refresh command (one week since last run)
- Batch (preferred): overwrite the same ISO-week snapshot
  ARCHIVE_GRANULARITY=week ARCHIVE_OVERWRITE_SAME_PERIOD=1 START_PAGE=1 END_PAGE=1500 WORKERS=4 NO_ARCHIVE=0 ./scripts/run_community_ranking_batch.sh

- Generate WoW report:
  python3 analyze_discovery_trends.py --auto-compare

Where archives go
- Weekly snapshot folder:
  - output/historical/community_ranking/YYYY-WW
  - Example: output/historical/community_ranking/2025-W37

Documentation updated
- Weekly Refresh section (commands and notes):
  - [README.md](README.md:308)
- Snapshot model and configuration details:
  - [README.md](README.md:140)

Runtime flags (optional)
- Keep multiple weekly snapshots instead of overwriting:
  ARCHIVE_OVERWRITE_SAME_PERIOD=0 START_PAGE=1 END_PAGE=1500 WORKERS=4 NO_ARCHIVE=0 ./scripts/run_community_ranking_batch.sh
  - The archiver will create a unique ID (e.g., append HHMMSS) if a snapshot for that week exists.

Relevant code references (for future changes)
- Archiving granularity and overwrite behavior:
  - [discovery_scraper_local.py](discovery_scraper_local.py:519)
  - CLI flags for archive control: [discovery_scraper_local.py](discovery_scraper_local.py:936)
- Batch runner entrypoint:
  - [scripts/run_community_ranking_batch.sh](scripts/run_community_ranking_batch.sh:1)
- Trends CLI:
  - [analyze_discovery_trends.py](analyze_discovery_trends.py:1)

This setup refreshes the current week’s data, archives snapshots weekly to output/historical/community_ranking/YYYY-WW, and then generates the week-over-week report.

---
Resumable runs are now supported end-to-end.

How resume works
- Per-page outputs live in output/pages/page_N.json. On resume, existing non-empty page files are skipped, so the job continues from the first missing/invalid page.
- Implementation:
  - Skip logic: [python.CommunityRankingScraper.scrape_and_persist_page()](discovery_scraper_local.py:441)
  - CLI flags and config: [python.main()](discovery_scraper_local.py:936), [python.EnhancedScraperConfig](discovery_scraper_local.py:116)
  - Batch pass-through: [python.main()](batch_discovery_scraper.py:181), [python.config_dict](batch_discovery_scraper.py:241)
- Docs updated in README:
  - Weekly refresh commands: [README.md](README.md:308)
  - Snapshot model and configuration: [README.md](README.md:140)
  - Resume usage: [README.md](README.md:331)

Weekly refresh with resume (recommended)
- Overwrite the same ISO-week snapshot and resume missing pages only:
  ARCHIVE_GRANULARITY=week ARCHIVE_OVERWRITE_SAME_PERIOD=1 START_PAGE=1 END_PAGE=1500 WORKERS=4 NO_ARCHIVE=0 ./scripts/run_community_ranking_batch.sh --resume

Generate WoW report afterwards:
- python3 analyze_discovery_trends.py --auto-compare

Other resume scenarios
- Force full re-scrape (ignore existing pages):
  ./scripts/run_community_ranking_batch.sh --overwrite
- Resume via direct runner (sequential):
  python3 discovery_scraper_local.py --start-page 1 --end-page 1500 --resume
- Recompute just a few pages:
  - Delete specific files (e.g., output/pages/page_725.json) and run with --resume; only the deleted pages will be scraped.
  - Or run with --overwrite to recompute everything in the range.

Archiving during resume
- If you resume in the same period and do not want to write another snapshot, disable archiving:
  - Batch: NO_ARCHIVE=1 ./scripts/run_community_ranking_batch.sh --resume
  - Direct: python3 discovery_scraper_local.py ... --no-archive

Where snapshots go
- Snapshot folder: output/historical/community_ranking/<snapshot_id>
- For weekly refresh: output/historical/community_ranking/YYYY-WW

Behavior summary
- --resume: skip existing valid page outputs and continue from missing ones (idempotent).
- --overwrite: recompute and overwrite all pages in the specified range.
- ARCHIVE_GRANULARITY, ARCHIVE_OVERWRITE_SAME_PERIOD, ARCHIVE_ROTATE_DEPTH let you control snapshot behavior; default is clean weekly overwrite.

This covers interruption recovery: re-run the weekly command with --resume and it continues where it left off without redoing completed pages.