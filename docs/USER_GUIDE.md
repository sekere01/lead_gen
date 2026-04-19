# Lead Generation Engine - User Guide

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Creating Jobs](#creating-jobs)
5. [Understanding the Pipeline](#understanding-the-pipeline)
6. [Celery Services](#celery-services)
7. [Dashboard & Metrics](#dashboard--metrics)
8. [Monitoring Progress](#monitoring-progress)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [API Reference](#api-reference)

---

## Overview

This is an automated lead generation system that:

1. **Discovers** companies from search results (DuckDuckGo, SearXNG, CommonCrawl)
2. **Browses** their websites to score quality and extract signals
3. **Enriches** with contact emails (theHarvester + custom crawler)
4. **Verifies** email validity (DNS + SMTP)

Each stage runs as an independent service that polls the database for work. The pipeline is orchestrated with:

- **PostgreSQL** - Data storage
- **Redis** - Message broker for Celery
- **Celery** - Async task processing
- **Celery Beat** - Scheduled task execution

---

## Prerequisites

### Software Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| **PostgreSQL** | 12+ | Database |
| **Redis** | 6+ | Celery message broker |
| **Docker** | Latest | theHarvester email extraction |
| **Python** | 3.12 | Runtime |

### Database Setup

```bash
# Create the database
createdb leadgen_db

# Create user (or use existing)
createuser leadgen_user
psql -d leadgen_db -c "ALTER USER leadgen_user WITH PASSWORD 'leadgen_pass';"

# Grant permissions
psql -d leadgen_db -c "GRANT ALL PRIVILEGES ON DATABASE leadgen_db TO leadgen_user;"
```

### Redis Setup

```bash
# Install Redis
# On Ubuntu/Debian:
sudo apt install redis-server

# Start Redis
redis-server

# Verify Redis is running
redis-cli ping
# Expected: PONG
```

---

## Quick Start

### 1. Start All Services

Open 7 terminal windows:

```bash
# Terminal 1: Discovery Service
cd ~/lead_gen2
./run_discovery.sh

# Terminal 2: Browsing Service
cd ~/lead_gen2
./run_browsing.sh

# Terminal 3: Enrichment Service
cd ~/lead_gen2
./run_enrichment.sh

# Terminal 4: Verification Service
cd ~/lead_gen2
./run_verification.sh

# Terminal 5: API Server
cd ~/lead_gen2
./run_api.sh

# Terminal 6: Celery Worker (task processing)
cd ~/lead_gen2
./run_celery_worker.sh

# Terminal 7: Celery Beat (scheduled metrics)
cd ~/lead_gen2
./run_celery_beat.sh
```

### 2. Create a Discovery Job

```bash
# Using the API
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "tech company", "region": "india"}'

# Or directly in the database
psql -d leadgen_db -c "INSERT INTO discovery_jobs (keyword, region) VALUES ('tech company', 'india');"
```

### 3. Monitor Progress

```bash
# Check job status
psql -d leadgen_db -c "SELECT keyword, region, status, results_count FROM discovery_jobs ORDER BY id DESC LIMIT 5;"

# Check companies found
psql -d leadgen_db -c "SELECT domain, discovery_score, status FROM companies ORDER BY id DESC LIMIT 10;"

# Check emails found
psql -d leadgen_db -c "SELECT c.domain, ct.email FROM contacts ct JOIN companies c ON ct.company_id = c.id ORDER BY ct.id DESC LIMIT 10;"
```

### 4. View Dashboard

Open in browser: **http://localhost:8000/dashboard**

The dashboard provides:

- Pipeline status overview
- Job queue management
- Live metrics chart with real-time updates

---

## Creating Jobs

### Job Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `keyword` | Yes | Search term for finding companies |
| `region` | No | Target region (e.g., "india", "china", "germany", "global") |

### Examples

```sql
-- Job for India tech companies
INSERT INTO discovery_jobs (keyword, region) VALUES ('software company', 'india');

-- Job for Nigerian companies
INSERT INTO discovery_jobs (keyword, region) VALUES ('tech startup', 'nigeria');

-- Global job (no region)
INSERT INTO discovery_jobs (keyword, region) VALUES ('SaaS company', 'global');
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

**Input**: `discovery_jobs` table (status = 'pending')

**Process**:

1. Polls DuckDuckGo, SearXNG, CommonCrawl for domain names
2. Calculates regional score based on TLD and city keywords
3. Saves companies to `companies` table

**Output**: Companies with `status = 'discovered'`, `discovery_score >= 2`

---

### Stage 2: Browsing

**Input**: `companies` table (`status = 'discovered'`, `discovery_score >= 2`)

**Process**:

1. Fetches company homepage via HTTP
2. Detects signals: contact links, addresses, social links, emails
3. Calculates browsing score (max 10)
4. Filters parked/invalid domains
5. Saves any emails found directly to contacts

**Output**: Companies with `status = 'browsed'`, updated `discovery_score`

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

**Input**: `companies` table (`status = 'browsed'`)

**Process**:

1. Runs theHarvester Docker container to find emails
2. Falls back to HTTP crawling if no results
3. Saves emails to `contacts` table

**Output**: Companies with `status = 'enriched'`

---

### Stage 4: Verification

**Input**: `contacts` table (`verification_status = 'pending'`)

**Process**:

1. Validates email syntax
2. Checks disposable email domains
3. Verifies MX records exist
4. Optionally tests SMTP delivery

**Output**: Contacts with `is_verified = true/false`

---

## Celery Services

The pipeline uses Celery for asynchronous task processing and scheduling.

### Task Queues

| Queue | Purpose | Tasks |
|-------|---------|-------|
| `discovery` | Discovery job processing | `process_discovery_job` |
| `browsing` | Company browsing | `process_browsing` |
| `enrichment` | Email enrichment | `process_enrichment` |
| `verification` | Email verification | `process_verification` |
| `default` | System tasks | `collect_metrics` |

### Celery Worker

The worker picks up tasks from the queues and processes them asynchronously.

```bash
# Start worker with all queues
./run_celery_worker.sh

# Or specify specific queues
./run_celery_worker.sh discovery,browsing,enrichment
```

**Configuration**:

- `concurrency=1` - One task at a time
- `prefetch_multiplier=1` - Don't prefetch tasks

### Celery Beat

The scheduler runs periodic tasks:

| Task | Schedule | Description |
|------|----------|-------------|
| `collect_metrics` | Every 30 seconds | Collects pipeline metrics |

```bash
# Start beat scheduler
./run_celery_beat.sh
```

### Managing Celery

```bash
# Check worker status
ps aux | grep celery

# Check queues for pending tasks
redis-cli LLEN discovery
redis-cli LLEN default

# View worker logs
tail -f /tmp/celery_worker.log

# View beat logs
tail -f /tmp/celerybeat.log
```

---

## Dashboard & Metrics

### Access

**Dashboard URL**: http://localhost:8000/dashboard

### Features

#### Pipeline Overview

Shows real-time status of all services:

| Service | Status | Queue Depth | Processed |
|---------|--------|------------|-----------|
| Discovery | running | 5 jobs | 150 |
| Browsing | running | 23 companies | 89 |
| Enrichment | running | 45 companies | 67 |
| Verification | running | 112 contacts | 234 |

#### Job Queue

- List of pending and processing jobs
- Create new jobs directly
- View job details

#### Live Metrics Chart

Interactive time-series chart with:

- **Time Window Filters**:
  - `5m` - Last 5 minutes (30-second intervals)
  - `1h` - Last 1 hour
  - `24h` - Last 24 hours

- **Service Selection**:
  - `Discovery` - Companies found, jobs completed
  - `Browsing` - Pages browsed, contacts found
  - `Enrichment` - Emails collected, domains processed
  - `Verification` - Contacts verified
  - `All` - Combined view of all services

- **Auto-refresh**: Updates every 30 seconds

### Metrics API

Get metrics programmatically:

```bash
# Get all services, last 5 minutes
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"

# Get specific service
curl "http://localhost:8000/api/v1/dashboard/metrics?service=discovery&window=1h"

# Get 24-hour view
curl "http://localhost:8000/api/v1/dashboard/metrics?service=enrichment&window=24h"
```

### Response Format

```json
{
  "data": [
    {
      "timestamp": "2026-04-19T10:24:41.855545-04:00",
      "discovery_companies_total": 1519,
      "discovery_jobs_completed": 56,
      "browsing_pages_browsed": 154,
      "enrichment_emails_collected": 1140,
      "verification_verified_count": 488,
      "label": "10:24 AM"
    }
  ]
}
```

### WebSocket Real-time Updates

Connect for live updates:

```javascript
// JavaScript example
const ws = new WebSocket('ws://localhost:8000/api/v1/dashboard/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data); // { type: 'initial'|'update', data: {...} }
};
```

---

## Monitoring Progress

### Check Queue Status

```sql
-- How many companies at each stage
SELECT status, COUNT(*) FROM companies GROUP BY status;

-- How many contacts verified
SELECT verification_status, COUNT(*) FROM contacts GROUP BY verification_status;

-- How many jobs pending/processing/completed
SELECT status, COUNT(*) FROM discovery_jobs GROUP BY status;
```

### View Specific Data

```bash
# View strong leads (score 8-10)
psql -d leadgen_db -c "SELECT domain, discovery_score FROM companies WHERE discovery_score >= 8 ORDER BY discovery_score DESC;"

# View companies needing enrichment
psql -d leadgen_db -c "SELECT domain, status FROM companies WHERE status = 'browsed' ORDER BY discovery_score DESC;"

# View verified emails
psql -d leadgen_db -c "SELECT c.domain, ct.email, ct.is_verified FROM contacts ct JOIN companies c ON ct.company_id = c.id WHERE ct.is_verified = true;"
```

### Metrics History

```bash
# View recent metrics
psql -d leadgen_db -c "SELECT recorded_at, service, metric, value FROM service_metrics ORDER BY recorded_at DESC LIMIT 20;"

# View specific service metrics
psql -d leadgen_db -c "SELECT recorded_at, metric, value FROM service_metrics WHERE service = 'discovery' ORDER BY recorded_at DESC LIMIT 10;"
```

---

## Configuration

### Service Settings

Each service can be configured via environment variables or `.env` files:

| Service | Key Settings |
|---------|--------------|
| Discovery | `DISCOVERY_POLL_INTERVAL`, `MAX_JOB_RETRIES`, `SEARCH_CACHE_HOURS` |
| Browsing | `BROWSING_TIMEOUT_DOMAIN`, `SCORE_MAX`, `BROWSING_WATCHDOG_MINUTES` |
| Enrichment | `TARGET_EMAILS_PER_DOMAIN`, `ENRICHMENT_TIMEOUT_DOMAIN`, `MAX_CONCURRENT_CONTAINERS` |
| Verification | `SMTP_TIMEOUT`, `VERIFIER_POLL_INTERVAL` |
| Celery | `REDIS_URL`, task routes, concurrency settings |

### Environment Variables

Create `.env` files in each service directory:

```bash
# Example: 01_discovery/.env
DATABASE_URL=postgresql://leadgen_user:leadgen_pass@localhost/leadgen_db
DISCOVERY_POLL_INTERVAL=300
MAX_JOB_RETRIES=3
```

```bash
# Example: 04_api/.env
DATABASE_URL=postgresql://leadgen_user:leadgen_pass@localhost/leadgen_db
REDIS_URL=redis://localhost:6379/0
API_HOST=0.0.0.0
API_PORT=8000
```

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
source .venv/bin/activate
python -c "import sqlalchemy; print('OK')"

# Check Redis
redis-cli ping
```

### No Companies Being Processed

```bash
# Check if there are companies with score >= 2
psql -d leadgen_db -c "SELECT COUNT(*) FROM companies WHERE status = 'discovered' AND discovery_score >= 2;"

# Check if job completed
psql -d leadgen_db -c "SELECT status, results_count FROM discovery_jobs ORDER BY id DESC LIMIT 1;"
```

### Enrichment Not Finding Emails

```bash
# Check Docker is running
docker ps

# Check for Docker permission
docker run hello-world
```

### Celery Worker Not Processing Tasks

```bash
# Check worker is running
ps aux | grep celery | grep worker

# Check queues for pending tasks
redis-cli LLEN discovery
redis-cli LLEN default

# Check worker logs
tail -f /tmp/celery_worker.log
```

### Metrics Not Updating

```bash
# Check Celery Beat is running
ps aux | grep celery | grep beat

# Check beat logs
tail -f /tmp/celerybeat.log

# Verify metrics in database
psql -d leadgen_db -c "SELECT recorded_at, service, metric, value FROM service_metrics ORDER BY recorded_at DESC LIMIT 10;"
```

### Dashboard Shows No Data

1. Ensure Celery Beat is running
2. Wait up to 30 seconds for first data point
3. Check browser console for errors
4. Verify API returns data:
```bash
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"
```

### Database Connection Issues

```bash
# Test connection
psql -d leadgen_db -c "SELECT 1;"

# Check database URL in .env files
cat 01_discovery/.env | grep DATABASE
```

---

## API Reference

### Base URL

```
http://localhost:8000
```

### Endpoints

#### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/jobs` | List all jobs |
| POST | `/api/v1/jobs` | Create new job |
| GET | `/api/v1/jobs/{id}` | Get job details |

#### Companies

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/companies` | List companies |
| GET | `/api/v1/companies/{id}` | Get company details |

#### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/contacts` | List contacts |
| GET | `/api/v1/contacts/{id}` | Get contact details |

#### Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/services/status` | Get all service statuses |
| POST | `/api/v1/services/{service}/start` | Start a service |
| POST | `/api/v1/services/{service}/stop` | Stop a service |

#### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/stats` | Get pipeline statistics |
| GET | `/api/v1/dashboard/metrics` | Get time-series metrics |
| WS | `/api/v1/dashboard/ws` | WebSocket for real-time |

### Metrics Parameters

| Parameter | Options | Description |
|-----------|--------|-------------|
| `service` | `discovery`, `browsing`, `enrichment`, `verification`, `all` | Which service to query |
| `window` | `5m`, `1h`, `24h` | Time window |
| `limit` | Integer | Max results |

### Example API Calls

```bash
# Create a job
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "marketing agency", "region": "usa"}'

# List companies
curl http://localhost:8000/api/v1/companies?status=browsed&limit=10

# Get dashboard stats
curl http://localhost:8000/api/v1/dashboard/stats

# Get metrics
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"

# Check API health
curl http://localhost:8000/health
```

---

## Support

For issues or questions, check:

1. Service logs in terminal output
2. Database status queries above
3. Celery worker/beat logs in `/tmp/`
4. PostgreSQL logs (`/var/log/postgresql/`)