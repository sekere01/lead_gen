# Lead Generation Engine + Sky Email Sorter

A multi-service lead generation pipeline that discovers companies, browses their websites for signals, enriches with contact emails, verifies email addresses, and sorts/classifies contacts by email provider.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                             │
│  discovery_jobs  companies  contacts  email_lists  service_metrics   │
│  extracted_emails  job_stats  job_templates                          │
└──────────────────────────────────────────────────────────────────────┘
         ↑          ↑           ↑          ↑           ↑          ↑
         │          │           │          │           │          │
    ┌────┴───┐ ┌───┴────┐ ┌───┴────┐ ┌──┴────┐ ┌───┴─────┐ ┌──┴──────┐
    │ 01_    │ │ 01b_   │ │ 02_    │ │ 03_   │ │ 04_     │ │ Sorter  │
    │discov- │ │brows-  │ │enrich- │ │verif- │ │  API    │ │ (built  │
    │ ery    │ │  ing   │ │  ment  │ │ication │ │         │ │ into API)│
    └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘ └──────────┘
                                                      ↑
                                              ┌───────┴───────┐
                                              │   WebSocket   │
                                              │  Real-time    │
                                              │  Dashboard    │
                                              └───────────────┘
```

## Pipeline

| Service | Directory | Description |
|---------|-----------|-------------|
| **Discovery** | `01_discovery/` | Finds companies by keyword/region via DuckDuckGo, SearXNG, CommonCrawl |
| **Browsing** | `01b_browsing/` | Browses company homepages, extracts signals, scores leads |
| **Enrichment** | `02_enrichment/` | Extracts emails via theHarvester + crawler (5 sources) |
| **Verification** | `03_verification/` | Verifies email validity via DNS MX + syntax checks |
| **Sorter** | `04_api/services/sorter_service.py` | MX-based email classification, dedup, export |
| **API** | `04_api/` | REST API + WebSocket + dashboard |

## CI/CD Pipeline

This project uses GitHub Actions with a self-hosted runner for automated AppSec scanning and deployment. See [CI/CD-Pipeline.md](CI/CD-Pipeline.md) for full documentation.

## Status Flow

```
discovered → browsing → browsed → enriching → enriched → verified
                            ↓ (if failed)
                          failed
```

## Email Classification (Sky Email Sorter)

Contacts are automatically classified by email provider during verification using MX record analysis:

| Provider | MX Domain Pattern |
|----------|------------------|
| **Gmail** | `*.google.com`, `*.googlemail.com` |
| **Outlook** | `*.outlook.com`, `*.hotmail.com` |
| **Yahoo** | `*.yahoo.com`, `*.yahoomail.com` |
| **ProtonMail** | `*.protonmail`, `*.proton.me` |
| **iCloud** | `*.icloud.com`, `*.me.com` |
| **Zoho** | `*.zoho`, `*.zohomail` |
| **Other** | Everything else |

Classification is automatic — no manual steps required. The verifier stores `provider` during verification. Provider data is stored in the `contacts.provider` column.

Use the **Sorter** button in the dashboard to:
- View provider breakdown (donut chart)
- Export per-provider TXT files as ZIP
- Save/lists searchable email lists
- Browse MX domains as compact tiles

## Scoring Tiers (Browsing)

| Score | Tier | Action |
|-------|------|--------|
| 0-1 | Filtered | Parked/invalid - skipped |
| 2-4 | Weak | Enriched, low priority |
| 5-7 | Good | Normal enrichment |
| 8-10 | Strong | Prioritized enrichment |

## Prerequisites

- **PostgreSQL** 12+ (database)
- **Docker** (for theHarvester email extraction + SearXNG meta search)
- **Python** 3.12+

### Database Setup

```bash
# Ensure PostgreSQL is running and accessible
psql -d leadgen_db -c "SELECT 1;"

# Create database if needed:
createdb lead_gen

# Grant permissions
psql -d lead_gen -c "GRANT ALL PRIVILEGES ON DATABASE lead_gen TO kali;"
```

### One-Click Setup

The project includes an automated setup script:

```bash
chmod +x setup.sh
./setup.sh --check   # dry-run to see what would be done
./setup.sh           # full setup
```

`setup.sh` handles: PostgreSQL config, Docker install, SearXNG container, Redis, nginx, virtual environments, and all dependencies.

## Quick Start

### Start Services

```bash
# Start all services via the API dashboard:
# 1. Start the API server
cd 04_api && PYTHONPATH=/home/kali/lead_gen ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000

# 2. Open http://localhost:8000/dashboard
# 3. Set pipeline mode to "Manual"
# 4. Click Start on each pipeline node
```

Or start individual services manually:

```bash
# Terminal 1: Discovery Service
./run_discovery.sh

# Terminal 2: Browsing Service
./run_browsing.sh

# Terminal 3: Enrichment Service
./run_enrichment.sh

# Terminal 4: Verification Service
./run_verification.sh

# Terminal 5: API Server
./run_api.sh
```

### Create a Discovery Job

```bash
curl -X POST http://localhost:8000/api/v1/discovery-jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "tech company", "region": "india"}'
```

### View Results

```bash
curl http://localhost:8000/api/v1/companies?limit=10
```

## Dashboard

Access the live dashboard at: **http://localhost:8000/dashboard**

### Pipeline Nodes

Each pipeline node expands to show:
- **Status**: Running / Stopped / Idle with pulsing indicator
- **Uptime**: How long the service has been running
- **Queue**: Items waiting to be processed
- **Processed**: Items completed
- **Progress Widget**: Live bar with counts — companies processed, emails collected, pages browsed, etc.
- **Source Breakdown**: Bar chart per data source (DDGS/SearXNG, httpx/Playwright, theHarvester/Google dorking, etc.)
- **Inline Controls**: Start / Stop / Restart buttons

### Sorter Panel

Click the **Sorter** button in the header to open the email classification panel:

- **Stats Cards**: Total Contacts, Need MX Resolve, Failed, Duplicates
- **Provider Breakdown**: Colored bar chart + donut chart for Gmail/Outlook/Yahoo/Other
- **MX Domain Tiles**: Compact pills showing provider + MX domain + count
- **Saved Lists**: Save/load named email lists with per-provider export
- **Export**: Download contacts grouped by provider as per-provider TXT files in a ZIP

Classification is automatic — the verifier stores provider during verification.

### Live Metrics Chart

Time-series visualization with:
- **Time Windows**: 5 minutes, 1 hour, 24 hours
- **Service Selection**: Discovery, Browsing, Enrichment, Verification, All
- **Real-time updates via WebSocket** (no polling)

### Stats Cards

| Card | Click Action |
|------|-------------|
| **Companies** | Opens Companies modal |
| **Contacts** | Opens Contacts modal |
| **Verified** | Opens Contacts modal (verified filter) |
| **Pending Jobs** | — |
| **Completed** | Opens Jobs modal (completed filter) |
| **Failed** | Opens Pipeline Failures breakdown modal |

### Pipeline Failures Modal

Shows aggregate failures across all pipeline stages:

| Stage | Count Source |
|-------|-------------|
| Failed Discovery Jobs | `discovery_jobs.status = 'failed'` |
| Failed Browsing Companies | `companies.status = 'failed'` |
| Failed Enrichments | `companies.status = 'enriched' AND failure_reason IS NOT NULL` |
| Failed Contacts (Pipeline) | `contacts.verification_status IN ('invalid_syntax','no_mx_records','failed')` AND non-imported |
| Failed Contacts (Imported) | Same but `source = 'imported'` |

Each row is clickable — opens the relevant modal with the correct filter.

### WebSocket Real-Time Updates

The dashboard uses WebSocket for live updates:

- `ws://host:8000/api/v1/dashboard/ws`
- Server sends `ping` every 30s
- Client sends `request_update` every 30s
- Graceful fallback to HTTP polling if WebSocket disconnects
- Verifier progress events trigger automatic sorter panel refresh

### Metrics Chart Parameters

| Parameter | Options | Description |
|-----------|--------|-------------|
| `service` | `discovery`, `browsing`, `enrichment`, `verification`, `all` | Which service to query |
| `window` | `5m`, `1h`, `24h` | Time window for data |

### Metrics Collected

| Service | Metrics |
|---------|---------|
| **Discovery** | `companies_total`, `jobs_pending`, `jobs_processing`, `jobs_completed`, `jobs_failed` |
| **Browsing** | `pages_browsed`, `domain_browsed`, `domain_failed`, `enrich_requeued` |
| **Enrichment** | `emails_collected`, `domains_processed`, `enrich_requeued`, `domain_enriching` |
| **Verification** | `contacts_total`, `verified_count`, `invalid_count`, `pending_count`, `needs_retry` |

### Contacts Modal Features

- Status filter (Pending, Verified, Failed, No MX, Invalid Syntax)
- Provider filter (Gmail, Outlook, Yahoo, etc. — loaded dynamically)
- Source filter (Imported, Enriched)
- Tag column with badge display
- Provider badges with provider-specific colors
- Search by email, name, title
- Batch verify / batch delete

## Configuration

Each service has its own `.env` file and config.py:

| Service | Config File | Key Settings |
|---------|-------------|--------------|
| Discovery | `01_discovery/config.py` | `DISCOVERY_POLL_INTERVAL=300`, `MAX_JOB_RETRIES=3`, `GROQ_QUERY_COUNT=50` |
| Browsing | `01b_browsing/config.py` | `BROWSING_TIMEOUT_DOMAIN=45`, `BROWSING_WORKERS=5`, `MAX_RETRIES=3` |
| Enrichment | `02_enrichment/config.py` | `ENRICHMENT_TIMEOUT_DOMAIN=120`, `ENRICHMENT_TIMEOUT_DOCKER=120`, `MAX_CONCURRENT_CONTAINERS=5` |
| Verification | `03_verification/config.py` | `VERIFIER_POLL_INTERVAL=30` |
| API | `04_api/config.py` | `API_HOST=127.0.0.1`, `API_PORT=8000` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `API_BASE` | `http://localhost:8000/api/v1` | Internal API URL for service progress POSTs |
| `GROQ_API_KEY` | (required for discovery/enrichment) | LLM API key for query generation |
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG meta search instance |
| `PYTHONPATH` | project root | Required for all services to find shared_models |

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

## Email Verification Flow

```
verify_email_fast(email):
  1. Noise/placeholder filter      → invalid_syntax
  2. Syntax validation             → invalid_syntax
  3. Disposable domain check       → informational only
  4. MX record lookup              → no_mx_records if none
  5. Provider classification       → Gmail/Outlook/Yahoo/Other
  6. All checks pass               → verified
```

The `provider` and `mx_domain` are stored in the contacts table and are available for filtering, sorting, and export.

## Troubleshooting

### Services Not Starting

```bash
# Check if PostgreSQL is running
psql -d lead_gen -c "SELECT 1;"

# Check if Docker is running (required for theHarvester + SearXNG)
docker ps
```

### API Not Responding

```bash
# Start API with proper PYTHONPATH
cd 04_api && PYTHONPATH=/home/kali/lead_gen ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000

# Check health endpoint
curl http://127.0.0.1:8000/health
```

### No companies being discovered

```sql
SELECT COUNT(*) FROM companies WHERE status = 'discovered' AND discovery_score >= 2;
```

If 0, create a discovery job:
```bash
curl -X POST http://localhost:8000/api/v1/discovery-jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "software company", "region": "us"}'
```

### Enrichment stuck / timeout

```bash
# Check Docker is running
docker ps

# Check enrichment logs
tail -f /var/log/lead_gen/enrichment.log
```

Common cause: theHarvester Docker container takes 60-120s per company. The per-source timeout was increased from 60s → 120s to accommodate this.

### Dashboard Shows No Data

1. Ensure the API is running (`curl http://127.0.0.1:8000/health`)
2. Open http://localhost:8000/dashboard
3. Check browser console for WebSocket connection errors
4. Verify stats endpoint:
```bash
curl http://127.0.0.1:8000/api/v1/dashboard/stats
```

### Sorter Shows 0 Contacts Classified

The sorter panel shows provider breakdown. If all contacts show as "Unknown":

1. Run the verifier (it auto-classifies during verification)
2. Or run the resolve-mx endpoint directly:
```bash
curl -X POST http://localhost:8000/api/v1/sorter/resolve-mx
```

### Database Connection Issues

```bash
# Connect via Unix socket (peer auth)
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT 1;"

# Reset password if needed
psql -h /var/run/postgresql -U kali -d lead_gen -c "ALTER USER kali WITH PASSWORD 'newpassword';"
```

## API Reference

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/discovery-jobs` | List jobs (filterable, sortable) |
| POST | `/api/v1/discovery-jobs` | Create new job |
| POST | `/api/v1/discovery-jobs/bulk` | Bulk create jobs |
| GET | `/api/v1/discovery-jobs/queue` | Get pending job queue |
| GET | `/api/v1/discovery-jobs/templates` | List templates |
| POST | `/api/v1/discovery-jobs/templates` | Create template |
| DELETE | `/api/v1/discovery-jobs/templates/{id}` | Delete template |
| POST | `/api/v1/discovery-jobs/templates/{id}/use` | Use template |
| PATCH | `/api/v1/discovery-jobs/{id}` | Update job (retry) |
| DELETE | `/api/v1/discovery-jobs/pending/clear` | Clear pending jobs |
| DELETE | `/api/v1/discovery-jobs/failed/clear` | Clear failed jobs |

### Companies

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/companies` | List companies (paginated, filterable, sortable) |
| GET | `/api/v1/companies/{id}` | Get company details |
| POST | `/api/v1/companies/batch/requeue` | Batch requeue |
| POST | `/api/v1/companies/batch/delete` | Batch delete |

**Query parameters for `GET /companies`:**
- `status` — filter by status
- `has_failure` — `true` to show companies with failure_reason set
- `lead_source` — filter by source
- `search` — search domain/industry/name
- `sort_by` / `sort_order` — sort column and direction
- `page` / `limit` — pagination

### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/contacts` | List contacts (paginated, filterable, sortable) |
| GET | `/api/v1/contacts/{id}` | Get contact details |
| POST | `/api/v1/contacts/import` | Import contacts (txt/csv) |
| POST | `/api/v1/contacts/batch/verify` | Verify selected contacts |
| POST | `/api/v1/contacts/batch/delete` | Batch delete |

**Query parameters for `GET /contacts`:**
- `verification_status` — filter by status
- `source` — `imported` or `enriched`
- `provider` — `Gmail`, `Outlook`, etc.
- `is_verified` — `true`/`false`
- `search` — search email/name/title
- `sort_by` / `sort_order` — sort column and direction
- `page` / `limit` — pagination

### Services (Process Manager)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/services/status` | Get all service statuses |
| GET | `/api/v1/services/health` | Pipeline health summary |
| GET | `/api/v1/services/logs` | Pipeline logs |
| GET | `/api/v1/services/{name}/logs` | Service-specific logs |
| POST | `/api/v1/services/{name}/start` | Start a service |
| POST | `/api/v1/services/{name}/stop` | Stop a service |
| POST | `/api/v1/services/{name}/restart` | Restart a service |
| GET | `/api/v1/services/mode` | Get control mode (Auto/Manual) |
| POST | `/api/v1/services/mode` | Set control mode |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/stats` | Full pipeline statistics + failure breakdown |
| GET | `/api/v1/dashboard/metrics` | Time-series metrics per service |
| POST | `/api/v1/dashboard/metrics` | Write a metric (internal) |
| WS | `/api/v1/dashboard/ws` | WebSocket real-time updates |
| POST | `/api/v1/dashboard/verification-progress` | Verifier progress (internal) |
| POST | `/api/v1/dashboard/enrichment-progress` | Enrichment progress (internal) |
| POST | `/api/v1/dashboard/browsing-progress` | Browsing progress (internal) |
| POST | `/api/v1/dashboard/discovery-progress` | Discovery progress (internal) |
| POST | `/api/v1/dashboard/source-status` | Per-source metrics (internal) |

### Sorter (Sky Email Sorter)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/sorter/stats` | Processing counts (unresolved, failed, duplicates) |
| GET | `/api/v1/sorter/provider-breakdown` | Count per provider with verification stats |
| GET | `/api/v1/sorter/providers` | List distinct providers |
| GET | `/api/v1/sorter/domains` | List MX domains with counts |
| GET | `/api/v1/sorter/contacts/{provider}` | Contacts for a specific provider |
| POST | `/api/v1/sorter/process` | Classify contacts with MX but no provider |
| POST | `/api/v1/sorter/resolve-mx` | DNS MX lookup + classify in one call |
| POST | `/api/v1/sorter/dedup` | Remove duplicate emails |
| GET | `/api/v1/sorter/export` | Download per-provider TXT files as ZIP |
| POST | `/api/v1/sorter/tags` | Bulk tag contacts |
| POST | `/api/v1/sorter/lists` | Save current selection as a list |
| GET | `/api/v1/sorter/lists` | List saved email lists |
| GET | `/api/v1/sorter/lists/{id}/export` | Export a saved list |
| DELETE | `/api/v1/sorter/lists/{id}` | Delete a saved list |

### Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/export/emails` | Export emails (csv/txt) |
| GET | `/api/v1/export/emails/preview` | Preview export |
| GET | `/api/v1/export/emails/jobs` | Recent export jobs |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/search/domains` | Search domains by keyword/region |

### Verification

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/verification/verify-single` | Verify a single email |

## License

MIT
