# Lead Generation Engine + Sky Email Sorter — User Guide

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Creating Jobs](#creating-jobs)
5. [Understanding the Pipeline](#understanding-the-pipeline)
6. [Email Classification (Sky Email Sorter)](#email-classification-sky-email-sorter)
7. [Dashboard & Metrics](#dashboard--metrics)
8. [Monitoring Progress](#monitoring-progress)
9. [CI/CD Pipeline](#cicd-pipeline)
10. [Configuration](#configuration)
11. [Troubleshooting](#troubleshooting)
12. [API Reference](#api-reference)

---

## Overview

This is an automated lead generation + email sorting system that:

1. **Discovers** companies from search results (DuckDuckGo, SearXNG, CommonCrawl)
2. **Browses** their websites to score quality and extract signals
3. **Enriches** with contact emails (theHarvester + 4 other sources)
4. **Verifies** email validity (syntax + DNS MX records)
5. **Classifies** contacts by email provider (Gmail/Outlook/Yahoo/etc.) automatically

Each stage runs as an independent service that polls the database for work. Services communicate through PostgreSQL status columns — no message queue needed.

---

## Prerequisites

### Software Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| **PostgreSQL** | 12+ | Database |
| **Docker** | Latest | theHarvester email extraction + SearXNG meta search |
| **Python** | 3.12+ | Runtime |
| **SearXNG** | Docker | Meta search engine (auto-starts via setup.sh) |

### Database Setup

```bash
# Create the database
createdb lead_gen

# Grant permissions
psql -d lead_gen -c "GRANT ALL PRIVILEGES ON DATABASE lead_gen TO kali;"
```

---

## Quick Start

### 1. Start All Services

Open 5 terminal windows:

```bash
# Terminal 1: API Server
cd /home/kali/lead_gen/04_api && PYTHONPATH=/home/kali/lead_gen ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000

# Terminal 2: Discovery Service
./run_discovery.sh

# Terminal 3: Browsing Service
./run_browsing.sh

# Terminal 4: Enrichment Service
./run_enrichment.sh

# Terminal 5: Verification Service
./run_verification.sh
```

Or use the Dashboard to control services:
1. Open **http://localhost:8000/dashboard**
2. Set pipeline mode to **Manual**
3. Click **Start** on each pipeline node

### 2. Create a Discovery Job

```bash
curl -X POST http://localhost:8000/api/v1/discovery-jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "tech company", "region": "india"}'
```

### 3. Monitor Progress

```bash
# Check job status
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT keyword, region, status, results_count FROM discovery_jobs ORDER BY id DESC LIMIT 5;"

# Check companies found
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT domain, discovery_score, status FROM companies ORDER BY id DESC LIMIT 10;"

# Check contacts with provider classification
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT email, provider, verification_status FROM contacts ORDER BY id DESC LIMIT 10;"
```

### 4. View Dashboard

Open in browser: **http://localhost:8000/dashboard**

---

## Creating Jobs

### Job Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `keyword` | Yes | Search term for finding companies |
| `region` | No | Target region (e.g., "india", "china", "germany", "global") |

### Examples

```bash
# Create a single job via API
curl -X POST http://localhost:8000/api/v1/discovery-jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "software company", "region": "india"}'

# Bulk create jobs
curl -X POST http://localhost:8000/api/v1/discovery-jobs/bulk \
  -H "Content-Type: application/json" \
  -d '{"keywords": ["SaaS startup", "fintech company", "healthtech"], "region": "global"}'
```

### Region-Specific Scoring

The system scores companies higher based on:

- **TLD match**: `.in`, `.cn`, `.ng`, `.de` get +3 points
- **City keywords**: Names like "Mumbai", "Lagos", "Berlin" get +2 points
- **Generic TLD**: `.com`, `.org`, `.net` get +1 point

See `01_discovery/config/tld_scores.yaml` for full TLD list.

---

## Understanding the Pipeline

### Stage 1: Discovery

**Input**: `discovery_jobs` table (`status = 'pending'`)

**Process**:
1. Picks 1 pending job at a time (row-level lock via `FOR UPDATE SKIP LOCKED`)
2. Runs 3 sources in parallel: DuckDuckGo, SearXNG, CommonCrawl
3. Each source runs independently (one failure doesn't block others)
4. LLM generates optimized search queries (via Groq with static fallback)
5. Saves found domains to `companies` table in batches of 25
6. Reports live progress via WebSocket after each batch

**Output**: Companies with `status = 'discovered'`, `discovery_score >= 2`

---

### Stage 2: Browsing

**Input**: `companies` table (`status = 'discovered'` or `'requeued'`)

**Process**:
1. Picks up to 50 companies per cycle, processes with 5 concurrent workers
2. Each worker:
   a. Fetches homepage via **httpx** (fast HTTP)
   b. If HTML ≥ 2000 chars → rich content, skip Playwright
   c. If short/empty → retry with **Playwright** (JS rendering)
   d. Detects signals: contact links, addresses, social links, emails
   e. Calculates browsing score
   f. Extracts and saves emails
3. Two-phase retry: Phase 1 (3 attempts) → Phase 2 (2 attempts) → `failed`
4. Reports live progress after each company via WebSocket

**Output**: Companies with `status = 'browsed'` or `'requeued'` or `'failed'`

**Scoring**:

| Signal | Points |
|--------|--------|
| Contact page link | +2 |
| Physical address | +2 |
| Social links | +1 |
| Email on homepage | +2 |
| Language match | +1 |
| Page loaded | +1 (base) |

---

### Stage 3: Enrichment

**Input**: `companies` table (`status = 'browsed'` or `'enrich_requeued'`)

**Process**:
1. Picks up to 10 companies per cycle, 5 concurrent workers
2. Each worker runs all 5 sources sequentially:
   | # | Source | Method |
   |---|--------|--------|
   | 1 | **theHarvester** | Docker container (DuckDuckGo, Yahoo, CommonCrawl, etc.) |
   | 2 | **Google Dorking** | OSINT queries via `googlesearch-python` |
   | 3 | **Sitemap Crawl** | Parses `/sitemap.xml`, scrapes discovered pages |
   | 4 | **Explicit Pages** | Fetches `/contact`, `/about`, `/team`, etc. |
   | 5 | **Homepage Scan** | Direct homepage + footer email extraction |
3. Each source gets its own timeout budget (120s per source)
4. Reports live progress after each company via WebSocket

**Output**: Companies with `status = 'enriched'`

---

### Stage 4: Verification

**Input**: `contacts` table (`verification_status = 'pending'` or `'failed'`)

**Process**:
1. Picks up to 200 contacts per cycle, processes in chunks of 10
2. 10 concurrent workers, each runs:
   ```
   verify_email_fast(email):
     1. Noise/placeholder filter      → invalid_syntax
     2. Syntax validation             → invalid_syntax
     3. Disposable domain check       → informational only
     4. MX record lookup              → no_mx_records if none
     5. Provider classification       → Gmail/Outlook/Yahoo/etc.
     6. All checks pass               → verified
   ```
3. MX domain + provider are stored automatically in the DB
4. Reports live progress every 5 contacts via WebSocket
5. Failed contacts are retried automatically on next cycle

**Output**: Contacts with `is_verified = true/false`, `provider` set

---

## Email Classification (Sky Email Sorter)

Contacts are automatically classified by email provider during the verification stage. No manual steps needed.

### Provider Map

| Provider | MX Domain Contains | Badge Color |
|----------|-------------------|-------------|
| **Gmail** | `google.com`, `googlemail.com` | Red |
| **Outlook** | `outlook.com`, `hotmail.com` | Blue |
| **Yahoo** | `yahoo.com`, `yahoomail.com` | Purple |
| **ProtonMail** | `protonmail`, `proton.me` | Indigo |
| **iCloud** | `icloud.com`, `me.com` | Grey |
| **Zoho** | `zoho`, `zohomail` | Dark Red |
| **Other** | Everything else | Slate |

### Sorter Panel

Click the **Sorter** button in the dashboard header to open the classification panel:

**Stats Cards:**
- **Total Contacts** — all contacts in the database
- **Need MX Resolve** — contacts awaiting MX lookup (should be 0 normally)
- **Failed** — contacts with invalid syntax, no MX records, or verification errors
- **Duplicates** — duplicate email addresses (should be 0, prevented by UNIQUE constraint)

**Provider Breakdown:**
- Bar chart showing count per provider
- Donut chart (Chart.js) for visual distribution
- Each bar shows total and verified percentage

**MX Domain Tiles:**
- Compact pills showing provider badge, MX domain, and count
- Wraps naturally to fit panel width

**Saved Lists:**
- Save current provider selection as a named list
- Export any list as per-provider TXT files in a ZIP
- Delete lists when no longer needed

**Export:**
- Downloads a ZIP file containing one TXT file per provider
- Each TXT file has one email per line
- Filename: `emails_by_provider_YYYYMMDD.zip`

---

## Dashboard & Metrics

### Access

**Dashboard URL**: http://localhost:8000/dashboard

### Features

#### Stats Cards

| Card | Shows | Click Action |
|------|-------|-------------|
| **Companies** | Total companies in DB | Opens Companies modal |
| **Contacts** | Total contacts in DB | Opens Contacts modal |
| **Verified** | Verified contacts count | Opens Contacts modal (verified filter) |
| **Pending Jobs** | Pending + processing jobs | — |
| **Completed** | Completed jobs | Opens Jobs modal (completed filter) |
| **Failed** | Pipeline-wide failure total | Opens Pipeline Failures breakdown |

#### Pipeline Overview

4 pipeline nodes showing real-time status. Expand each node to see:

| Expanded View | Shows |
|--------------|-------|
| **Uptime** | How long running |
| **Processed** | Items completed |
| **Queue** | Items waiting |
| **Progress Bar** | Live progress with counts |
| **Source Breakdown** | Bar chart per data source |
| **Controls** | Start / Stop / Restart buttons |

#### Pipeline Failures Modal

Shows aggregate failures across all stages with drill-down:

| Stage | Counts | Click to |
|-------|--------|----------|
| Failed Discovery Jobs | N | Jobs modal (failed filter) |
| Failed Browsing Companies | N | Companies modal (status=failed) |
| Failed Enrichments | N | Companies modal (enriched + has_failure) |
| Failed Contacts (Pipeline) | N | Contacts modal (failed filter) |
| Failed Contacts (Imported) | N | — |
| **Total** | Sum | — |

#### Contacts Modal

| Feature | Description |
|---------|-------------|
| **Status Filter** | All, Pending, Verified, Failed, No MX, Invalid Syntax |
| **Provider Filter** | All, Gmail, Outlook, Yahoo, etc. (loaded dynamically) |
| **Source Filter** | All, Imported, Enriched |
| **Search** | Search by email, name, job title |
| **Sort** | Click any column header |
| **Provider Badges** | Color-coded by provider |
| **Tags Column** | Comma-separated tags displayed as badges |
| **Batch Actions** | Verify selected / Delete selected |

#### Live Metrics Chart

Interactive time-series chart with:

- **Time Window Filters**:
  - `5m` — Last 5 minutes
  - `1h` — Last 1 hour
  - `24h` — Last 24 hours

- **Service Selection**:
  - `Discovery`, `Browsing`, `Enrichment`, `Verification`, `All`

- **Real-time updates via WebSocket** (auto-refreshes every 30s)

#### WebSocket Real-time Updates

The dashboard connects via WebSocket for live data. Falls back to HTTP polling if disconnected.

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8000/api/v1/dashboard/ws');

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === 'initial' || msg.type === 'update') {
    console.log(msg.data); // Full dashboard stats
  }
  if (msg.type === 'verification_progress') {
    console.log(msg.data); // {processed, verified, failed, total, status}
  }
};
```

---

## Monitoring Progress

### Check Queue Status

```bash
# How many companies at each stage
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT status, COUNT(*) FROM companies GROUP BY status;"

# How many contacts verified with provider breakdown
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT provider, COUNT(*) FROM contacts WHERE provider IS NOT NULL GROUP BY provider ORDER BY COUNT(*) DESC;"

# How many jobs pending/processing/completed
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT status, COUNT(*) FROM discovery_jobs GROUP BY status;"

# How many contacts by verification status
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT verification_status, COUNT(*) FROM contacts GROUP BY verification_status ORDER BY COUNT(*) DESC;"
```

### View Specific Data

```bash
# View strong leads (score 8-10)
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT domain, discovery_score FROM companies WHERE discovery_score >= 8 ORDER BY discovery_score DESC;"

# View companies needing enrichment
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT domain, status FROM companies WHERE status = 'browsed' ORDER BY discovery_score DESC;"

# View verified Gmail contacts
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT email, provider FROM contacts WHERE provider = 'Gmail' AND is_verified = true LIMIT 20;"
```

### Metrics History

```bash
# View recent metrics
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT recorded_at, service, metric, value FROM service_metrics ORDER BY recorded_at DESC LIMIT 20;"

# View specific service metrics
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT recorded_at, metric, value FROM service_metrics WHERE service = 'discovery' ORDER BY recorded_at DESC LIMIT 10;"
```

---

## CI/CD Pipeline

This project uses **GitHub Actions** with a **self-hosted runner** for automated build, security scanning, and deployment.

### Workflow File

`.github/workflows/pipeline.yml`

### What Runs on Every Push (test + main branches)

| Step | Tool | Purpose |
|------|------|---------|
| Venv check | Custom script | Ensures all 5 venvs use Python 3 (rebuilds Python 2 venvs) |
| Dependency install | `pip install` | Installs all requirements |
| Python CVE audit | `pip-audit` | Scans requirements.txt for known vulnerabilities |
| Python lint | `ruff` | Code quality and style checks |
| Shell lint | `shellcheck` | Validates `deploy.sh` and `setup.sh` |
| .gitignore check | Custom script | Warns if `.env`, `*.log`, `logs/` patterns missing |
| .env detection | `find` | **Blocks** if any `.env` file is tracked in git |
| Tests | `pytest` | Runs test suite (warns if none found) |
| Vuln + secret scan | **Trivy** | Filesystem scan for HIGH/CRITICAL vulnerabilities and secrets |

### Deploy Gate

- **`test` branch** — scan only, no deployment
- **`main` branch** — scan + deploy (blocks on HIGH/CRITICAL)

### Deploy Sequence (main only)

1. `bash deploy.sh --dry-run` — 10 pre-flight checks (venvs, deps, PostgreSQL, Redis, Docker, Nginx, dashboard)
2. `bash deploy.sh` — backup code → git pull → install deps → reload systemd → restart services
3. `curl http://127.0.0.1:8000/health` — verify dashboard responds

On failure, auto-rolls back to the previous backup.

### SOP: Daily Workflow

```bash
# 1. Develop on test
git checkout test
# ... make changes ...
git push origin test    # scans only, no deploy

# 2. Ship to production
git checkout main
git merge test
git push origin main    # scans + deploys automatically
```

See [CI/CD-Pipeline.md](../CI/CD-Pipeline.md) for full documentation including runner setup, security guardrails, and deploy script reference.

---

## Configuration

### Service Settings

Each service can be configured via environment variables or `.env` files:

| Service | Key Settings |
|---------|--------------|
| Discovery | `DISCOVERY_POLL_INTERVAL=300`, `MAX_JOB_RETRIES=3`, `GROQ_QUERY_COUNT=50` |
| Browsing | `BROWSING_TIMEOUT_DOMAIN=45`, `BROWSING_WORKERS=5`, `MAX_RETRIES=3` |
| Enrichment | `ENRICHMENT_TIMEOUT_DOMAIN=120`, `ENRICHMENT_TIMEOUT_DOCKER=120`, `MAX_CONCURRENT_CONTAINERS=5` |
| Verification | `VERIFIER_POLL_INTERVAL=30` |
| API | `API_HOST=127.0.0.1`, `API_PORT=8000` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `API_BASE` | `http://localhost:8000/api/v1` | Internal API URL for service progress POSTs |
| `GROQ_API_KEY` | (required for discovery/enrichment) | LLM API key for query generation |
| `SEARXNG_URL` | `http://localhost:8080` | SearXNG meta search instance |

### TLD and City Scoring

To modify scoring:

1. Edit `01_discovery/config/tld_scores.yaml`
2. Edit `01_discovery/config/city_keywords.yaml`
3. Changes are picked up automatically on next poll

---

## Troubleshooting

### Service Won't Start

```bash
# Check if ports are in use
lsof -i :8000

# Check Python environment
cd 04_api && PYTHONPATH=/home/kali/lead_gen ./venv/bin/python -c "from database import init_db; print('DB OK')"

# Check PostgreSQL
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT 1;"
```

### No Companies Being Processed

```bash
# Check if there are companies with score >= 2
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT COUNT(*) FROM companies WHERE status = 'discovered' AND discovery_score >= 2;"

# Check if job completed
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT status, results_count FROM discovery_jobs ORDER BY id DESC LIMIT 1;"

# Check if discovery service is running
curl http://localhost:8000/api/v1/services/status
```

### Enrichment Not Finding Emails

```bash
# Check Docker is running
docker ps

# Check enrichment logs for timeout issues
tail -f /var/log/lead_gen/enrichment.log
```

Common cause: theHarvester Docker container takes 60-120s per company. The per-source timeout was set to 120s to accommodate this. If you see "harvester exceeded 120s" in logs, the domain genuinely takes too long.

### Dashboard Shows No Data

1. Ensure the API is running: `curl http://localhost:8000/health`
2. Open http://localhost:8000/dashboard
3. Check browser console for WebSocket errors
4. Verify stats endpoint returns data:
```bash
curl http://localhost:8000/api/v1/dashboard/stats
```

### Sorter Shows 0 Classified Contacts

If all contacts show as "Unknown" provider:

1. The verifier auto-classifies during verification — ensure it's running
2. Check the verifier log for progress:
```bash
tail -f /var/log/lead_gen/verification.log | grep "provider\|classified"
```

### Provider Not Showing in Contacts Modal

The provider filter dropdown loads dynamically from the API on modal open. If empty:

```bash
# Check if any contacts have provider set
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT provider, COUNT(*) FROM contacts WHERE provider IS NOT NULL AND provider != '' GROUP BY provider;"

# If empty, run resolve-mx to classify existing contacts
curl -X POST http://localhost:8000/api/v1/sorter/resolve-mx
```

### Database Connection Issues

```bash
# Connect via Unix socket (peer auth)
psql -h /var/run/postgresql -U kali -d lead_gen -c "SELECT 1;"

# Reset password if needed
psql -h /var/run/postgresql -U kali -d lead_gen -c "ALTER USER kali WITH PASSWORD 'yourpassword';"

# Test API database connection
curl http://localhost:8000/api/v1/discovery-jobs/_test-db
```

---

## API Reference

### Base URL

```
http://localhost:8000
```

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/discovery-jobs` | List jobs (filterable, sortable) |
| POST | `/api/v1/discovery-jobs` | Create new job |
| POST | `/api/v1/discovery-jobs/bulk` | Bulk create jobs |
| GET | `/api/v1/discovery-jobs/queue` | Get pending job queue |
| PATCH | `/api/v1/discovery-jobs/{id}` | Update job (retry) |
| DELETE | `/api/v1/discovery-jobs/pending/clear` | Clear pending jobs |
| DELETE | `/api/v1/discovery-jobs/failed/clear` | Clear failed jobs |

### Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/discovery-jobs/templates` | List templates |
| POST | `/api/v1/discovery-jobs/templates` | Create template |
| DELETE | `/api/v1/discovery-jobs/templates/{id}` | Delete template |
| POST | `/api/v1/discovery-jobs/templates/{id}/use` | Create job from template |

### Companies

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/companies` | List companies |
| GET | `/api/v1/companies/{id}` | Get company details |
| POST | `/api/v1/companies/batch/requeue` | Batch requeue |
| POST | `/api/v1/companies/batch/delete` | Batch delete |

**Query parameters for `GET /companies`:**
- `status` — filter by status
- `has_failure` — `true` to show enrichment failures
- `lead_source` — filter by source
- `search` — search domain/industry/name
- `sort_by` / `sort_order` — sort column and direction
- `page` / `limit` — pagination

### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/contacts` | List contacts |
| GET | `/api/v1/contacts/{id}` | Get contact details |
| POST | `/api/v1/contacts/import` | Import contacts (txt/csv) |
| POST | `/api/v1/contacts/batch/verify` | Verify selected contacts |
| POST | `/api/v1/contacts/batch/delete` | Batch delete |

**Query parameters for `GET /contacts`:**
- `verification_status` — filter by status (comma-separated)
- `source` — `imported` or `enriched`
- `provider` — `Gmail`, `Outlook`, `Yahoo`, etc.
- `is_verified` — `true`/`false`
- `search` — search email/name/title
- `sort_by` / `sort_order` — sort column
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
| GET | `/api/v1/services/mode` | Get control mode |
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

### Metrics Parameters

| Parameter | Options | Description |
|-----------|--------|-------------|
| `service` | `discovery`, `browsing`, `enrichment`, `verification`, `all` | Which service to query |
| `window` | `5m`, `1h`, `24h` | Time window |
| `limit` | Integer | Max results |

### Example API Calls

```bash
# Create a job
curl -X POST http://localhost:8000/api/v1/discovery-jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "marketing agency", "region": "usa"}'

# List companies with status
curl http://localhost:8000/api/v1/companies?status=browsed&limit=10

# List contacts by provider
curl "http://localhost:8000/api/v1/contacts?provider=Gmail&limit=10"

# Get dashboard stats
curl http://localhost:8000/api/v1/dashboard/stats

# Get metrics
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"

# Get sorter provider breakdown
curl http://localhost:8000/api/v1/sorter/provider-breakdown

# Export per-provider TXT files
curl http://localhost:8000/api/v1/sorter/export -o emails_by_provider.zip

# Check API health
curl http://localhost:8000/health
```

---

## Support

For issues or questions, check:

1. Service logs: `/var/log/lead_gen/*.log`
2. API logs: `/var/log/lead_gen/api.log`
3. Database status queries above
4. PostgreSQL logs: `tail -f /var/log/postgresql/postgresql-*.log`
