# Lead Generation Engine

A multi-service lead generation pipeline that discovers companies, browses their websites for signals, enriches with contact emails, and verifies email addresses.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  PostgreSQL Database                   │
│  - discovery_jobs  - companies  - contacts        │
│  - extracted_emails                                │
└─────────────────────────────────────────────────────┘
         ↑          ↑           ↑          ↑
         │          │           │          │
    ┌────┴───┐ ┌───┴────┐ ┌───┴────┐ ┌──┴──────┐
    │ 01_    │ │ 01b_   │ │ 02_    │ │ 04_     │
    │discov- │ │brows-  │ │enrich- │ │  API    │
    │ ery    │ │  ing   │ │  ment  │ │         │
    └────────┘ └────────┘ └────────┘ └─────────┘
```

## Pipeline

| Service | Directory | Description |
|---------|-----------|-------------|
| **Discovery** | `01_discovery/` | Finds companies by keyword/region via DuckDuckGo, SearXNG, CommonCrawl |
| **Browsing** | `01b_browsing/` | Browses company homepages, extracts signals, scores leads |
| **Enrichment** | `02_enrichment/` | Extracts emails via theHarvester + crawler |
| **Verification** | `03_verification/` | Verifies email validity via DNS + SMTP |
| **API** | `04_api/` | REST API for accessing data |

## Status Flow

```
discovered → browsing → browsed → enriching → enriched → verified
                            ↓ (if failed)
                          failed
```

## Scoring Tiers (Browsing)

| Score | Tier | Action |
|-------|------|--------|
| 0-1 | Filtered | Parked/invalid - skipped |
| 2-4 | Weak | Enriched, low priority |
| 5-7 | Good | Normal enrichment |
| 8-10 | Strong | Prioritized enrichment |

## Quick Start

### Prerequisites
- PostgreSQL database
- Docker (for theHarvester)
- Python 3.12

### Database Setup
```bash
# Ensure PostgreSQL is running and accessible
# Create database if needed:
createdb leadgen_db
```

### Start Services

```bash
# Terminal 1: Discovery
./run_discovery.sh

# Terminal 2: Browsing
./run_browsing.sh

# Terminal 3: Enrichment
./run_enrichment.sh

# Terminal 4: Verification
./run_verification.sh

# Terminal 5: API (optional)
./run_api.sh
```

### Create a Discovery Job

Via API:
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "tech company", "region": "india"}'
```

Via database:
```sql
INSERT INTO discovery_jobs (keyword, region) VALUES ('tech company', 'india');
```

### View Results

```bash
# Via API
curl http://localhost:8000/api/v1/companies?limit=10

# Via database
psql -d leadgen_db -c "SELECT domain, discovery_score, status FROM companies LIMIT 10;"
```

## Configuration

Each service has its own `.env` file:

| Service | Config File | Key Settings |
|---------|-------------|--------------|
| Discovery | `01_discovery/config.py` | `DISCOVERY_POLL_INTERVAL`, `MAX_JOB_RETRIES` |
| Browsing | `01b_browsing/config.py` | `BROWSING_TIMEOUT_DOMAIN`, `SCORE_MAX` |
| Enrichment | `02_enrichment/config.py` | `TARGET_EMAILS_PER_DOMAIN`, `ENRICHMENT_TIMEOUT_DOMAIN` |
| Verification | `03_verification/config.py` | `SMTP_TIMEOUT`, `VERIFIER_POLL_INTERVAL` |

## Scoring Configuration

The discovery service uses TLD scores and city keywords from config files:

- `01_discovery/config/tld_scores.yaml` - TLD scoring rules
- `01_discovery/config/city_keywords.yaml` - Regional city keywords

Edit these files to adjust scoring. Changes are picked up automatically on the next poll cycle.

## Email Cleaning (Browsing)

The browsing service filters extracted emails:

- Rejects file extensions (e.g., `image@file.jpg`)
- Rejects placeholder domains (e.g., `test@company.com`)
- Repairs concatenated TLDs (e.g., `info@site.com.ngcom` → `info@site.com.ng`)
- Validates TLD format (2-6 letters)

## Troubleshooting

### No companies being picked up
Check discovery score threshold:
```sql
SELECT COUNT(*) FROM companies WHERE status = 'discovered' AND discovery_score >= 2;
```

### Enrichment stuck
Check Docker is running:
```bash
docker ps
```

### Database issues
Verify connection:
```bash
psql -d leadgen_db -c "SELECT 1;"
```

## License

MIT