# Reddit Community Discovery & Analysis

This repository provides tools for discovering and analyzing Reddit communities through multiple approaches:

1. **Community Ranking Discovery** - Discover subreddits from Reddit's "Best Communities" ranking pages
2. **Subreddit Content Analysis** - Scrape individual subreddit front pages and posts
3. **Historical Trend Analysis** - Track ranking and subscriber changes over time

## Repository Structure

### Community Discovery (Ranking Pages)
- `community_ranking_scraper_zenrows.py` — ZenRows API-based community ranking scraper (legacy)
- `community_ranking_scraper_local.py` — Local headless browser scraper with historical tracking
- `analyze_community_ranking_trends.py` — Week-over-week trend analysis

### Subreddit Content Collection
- `subreddit_frontpage_scraper.py` — Individual subreddit front page scraper
- `batch_scrape_subreddits.py` — Batch front page scraping
- `subreddit_posts_scraper.py` — Deep post + comments collection

### Documentation
- `doc/Subreddit Front Page Scraper.md` — Comprehensive front page scraper guide
- `doc/Subreddit Posts + Comments Scraper.md` — Posts scraper documentationit Scraper — ZenRows and Local Headless Browser

This repo scrapes Reddit “Best Communities” pages (e.g., `https://www.reddit.com/best/communities/{page}`) and parses subreddits from rendered HTML.

Two interchangeable ways to fetch pages:
- ZenRows API (existing approach)
- Local headless browser via Playwright (new approach) with basic stealth and optional proxy

Parsed results are written to the `output/` folder.

## Quick Start

### Community Discovery

Discover subreddits from Reddit's community ranking pages:

```zsh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# Discover communities with historical tracking
python community_ranking_scraper_local.py
```

This creates:
- `output/pages/page_N.json` — Per-page community data  
- `output/historical/community_ranking/YYYY-WW/` — Weekly archives for trend analysis
- `output/manifest.json` — Scraping metadata

### Subreddit Content Analysis

For detailed individual subreddit analysis, see **[Subreddit Front Page Scraper Guide](doc/Subreddit%20Front%20Page%20Scraper.md)** for:
- Multi-browser fingerprinting & anti-detection
- Bandwidth optimization & connectivity handling  
- Batch processing & error recovery
- Comprehensive configuration options

Quick example:
```zsh
python subreddit_frontpage_scraper.py --subs r/technology r/programming
```

### Historical Trend Analysis

Compare community ranking changes week-over-week:

```zsh
# Auto-compare latest two weeks
python analyze_community_ranking_trends.py --auto-compare

# Compare specific weeks  
python analyze_community_ranking_trends.py --weeks 2024-W45 2024-W46

# List available data weeks
python analyze_community_ranking_trends.py --list-weeks
```

## Data Organization

```
output/
├── pages/                                    # Current week's community ranking data
│   ├── page_1.json                          # Communities ranked 1-50
│   ├── page_2.json                          # Communities ranked 51-100
│   └── ...
├── historical/                              # Historical archives for trend analysis
│   └── community_ranking/
│       ├── 2024-W45/                       # Week 45 of 2024
│       │   ├── pages/                       # Archived ranking data
│       │   ├── manifest.json               # Archive metadata
│       │   └── archive_metadata.json       # Archive details
│       └── 2024-W46/
├── reports/                                 # Generated analysis reports
│   └── weekly_comparison/
│       └── 2024-W45_to_2024-W46.json      # Week-over-week analysis
├── subreddits/                             # Individual subreddit content
│   ├── <subreddit_name>/
│   │   ├── frontpage.json                  # Front page posts/metadata
│   │   └── posts/                          # Deep post collection
│   └── manifest.json
└── manifest.json                           # Main scraping metadata
```

## Historical Trend Analysis Features

The community ranking scraper now supports systematic historical tracking:

- **Weekly Archives**: Automatically archives existing data before refresh
- **Trend Analysis**: Compare ranking changes, subscriber growth, new communities
- **Week-over-Week Reports**: Automated insights on biggest movers
- **Data Preservation**: Never lose historical context for longitudinal studies

Example trends you can track:
- Which communities are growing fastest in subscribers?
- What new communities entered the top rankings?
- Which established communities are declining?
- How do rankings shift during major events?

## Advanced Usage

### Community Discovery Options

#### ZenRows API (Legacy)
For the original ZenRows-based approach:

```zsh
# Update API key in community_ranking_scraper_zenrows.py or use env var:
export ZENROWS_API_KEY="your_key_here"
python community_ranking_scraper_zenrows.py
```

#### Local Scraper (Recommended)
The local scraper supports proxy usage and historical tracking:

```zsh
# Use proxy (optional)
export PROXY_SERVER="http://user:pass@host:port"

# Full community discovery with archiving
python community_ranking_scraper_local.py

# Disable archiving for testing
python -c "
from community_ranking_scraper_local import CommunityRankingScraper, LocalScraperConfig
cfg = LocalScraperConfig(headless=True)
scraper = CommunityRankingScraper(cfg)
scraper.scrape_all_pages(start_page=1, end_page=5, archive_existing=False)
"
```

### Content Collection

For comprehensive subreddit content collection, refer to the **[Front Page Scraper Documentation](doc/Subreddit%20Front%20Page%20Scraper.md)** which covers:

- Browser fingerprinting & stealth techniques
- Multi-profile rotation & persistent sessions  
- Bandwidth optimization for residential proxies
- Error recovery & batch processing strategies
- Network connectivity monitoring

### Legacy Migration

Resume or migrate from old scraper outputs:

```zsh
# Resume interrupted scrape
python resume_local_scrape.py --end 1000 --save-every 25

# Migrate legacy JSON files to per-page format
python migrate_outputs_to_pages.py

# Verify data integrity
python verify_output.py output/pages
```

## Keyword Extraction

The keyword extraction pipeline extracts relevant keywords from community data:

```zsh
# Single page file
python3 -m src.keyword_extraction --input-file output/pages/page_60.json --output-dir output/keywords

# Many page files  
python3 -m src.keyword_extraction --input-glob "output/pages/page_*.json" --output-dir output/keywords

# Include frontpage data for better keywords
python3 -m src.keyword_extraction \
  --input-glob "output/pages/page_*.json" \
  --frontpage-glob "output/subreddits/*/frontpage.json" \
  --output-dir output/keywords_final \
  --topk 25
```

For technical details: [Keyword Extraction Pipeline](doc/Subreddit%20Keyword%20Extraction%20Pipeline.md)

# Subreddit Scraper Reorganization 

## File Reorganization

The repository has been reorganized with better naming and enhanced functionality:

### Renamed Files
- `reddit_scraper.py` → `community_ranking_scraper_zenrows.py` (ZenRows API version)
- `local_reddit_scraper.py` → `community_ranking_scraper_local.py` (Local browser version)

### Updated Class Names
- `LocalRedditCommunitiesScraper` → `CommunityRankingScraper`

### Enhanced Historical Tracking

The local community ranking scraper now includes:

1. **Automatic Archiving**: Preserves existing data before each weekly refresh
2. **Week-over-Week Analysis**: Compare ranking and subscriber changes
3. **Systematic Data Organization**: Historical data stored by ISO week

## New Data Structure

```
output/
├── pages/                              # Current week's data
├── historical/                         # Weekly archives for trends
│   └── community_ranking/
│       ├── 2024-W45/                  # Week 45 of 2024
│       ├── 2024-W46/                  # Week 46 of 2024  
│       └── ...
├── reports/                            # Generated analysis reports
│   └── weekly_comparison/
└── subreddits/                         # Individual subreddit content
```

## Migration Required

If you have existing scripts, update imports:

```python
# OLD
from local_reddit_scraper import LocalRedditCommunitiesScraper, LocalScraperConfig

# NEW  
from community_ranking_scraper_local import CommunityRankingScraper, LocalScraperConfig
```

## Enhanced Usage

### Weekly Community Discovery with Historical Tracking
```bash
# Full discovery with archiving (recommended for weekly refreshes)
python3 community_ranking_scraper_local.py --start-page 1 --end-page 1000

# Test run without archiving
python3 community_ranking_scraper_local.py --end-page 5 --no-archive

# Use proxy
python3 community_ranking_scraper_local.py --proxy "http://user:pass@host:port"
```

### Trend Analysis
```bash
# Compare latest two weeks automatically
python3 analyze_community_ranking_trends.py --auto-compare

# Compare specific weeks
python3 analyze_community_ranking_trends.py --weeks 2024-W45 2024-W46

# List available weeks
python3 analyze_community_ranking_trends.py --list-weeks
```

## Benefits of New Structure

1. **Clear Purpose**: File names clearly indicate what each scraper does
2. **Historical Context**: Never lose ranking/subscriber data for trend analysis
3. **Weekly Insights**: Automatically identify fastest-growing communities, biggest ranking changes
4. **Data Preservation**: Systematic archiving prevents accidental data loss
5. **Better Documentation**: Focused guides for each component

## Backward Compatibility

The reorganization maintains the same output formats, so existing analysis scripts should continue working. Only import statements need updating.
