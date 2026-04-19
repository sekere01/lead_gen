# Lead Generation Engine

A multi-service lead generation pipeline that discovers companies, browses their websites for signals, enriches with contact emails, and verifies email addresses.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL Database                          │
│  - discovery_jobs  - companies  - contacts                     │
│  - extracted_emails - service_metrics                          │
└─────────────────────────────────────────────────────────────────┘
         ↑          ↑           ↑          ↑           ↑
         │          │           │          │           │
    ┌────┴───┐ ┌───┴────┐ ┌───┴────┐ ┌──┴────┐ ┌───┴─────┐
    │ 01_    │ │ 01b_   │ │ 02_    │ │ 03_   │ │ 04_     │
    │discov- │ │brows-  │ │enrich- │ │verif- │ │  API    │
    │ ery    │ │  ing   │ │  ment  │ │ication │ │         │
    └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘
                                                    ↑
                                              ┌─────┴─────┐
                                              │  Celery   │
                                              │ Worker +  │
                                              │ Beat      │
                                              └───────────┘
                                                    ↑
                                              ┌─────┴─────┐
                                              │   Redis   │
                                              │ (Broker)  │
                                              └───────────┘
```

## Pipeline

| Service | Directory | Description |
|---------|-----------|-------------|
| **Discovery** | `01_discovery/` | Finds companies by keyword/region via DuckDuckGo, SearXNG, CommonCrawl |
| **Browsing** | `01b_browsing/` | Browses company homepages, extracts signals, scores leads |
| **Enrichment** | `02_enrichment/` | Extracts emails via theHarvester + crawler |
| **Verification** | `03_verification/` | Verifies email validity via DNS + SMTP |
| **API** | `04_api/` | REST API for accessing data, dashboard, and metrics |

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

## Prerequisites

- **PostgreSQL** 12+ (database)
- **Redis** (Celery message broker)
- **Docker** (for theHarvester email extraction)
- **Python** 3.12

### Database Setup

```bash
# Ensure PostgreSQL is running and accessible
# Create database if needed:
createdb leadgen_db

# Create user (or use existing)
createuser leadgen_user
psql -d leadgen_db -c "ALTER USER leadgen_user WITH PASSWORD 'leadgen_pass';"

# Grant permissions
psql -d leadgen_db -c "GRANT ALL PRIVILEGES ON DATABASE leadgen_db TO leadgen_user;"
```

### Redis Setup

```bash
# Install Redis if not already installed
# On Ubuntu/Debian:
sudo apt install redis-server

# Start Redis
redis-server

# Verify Redis is running
redis-cli ping
# Should return: PONG
```

## Quick Start

### Start Services

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

# Terminal 6: Celery Worker (processes tasks)
./run_celery_worker.sh

# Terminal 7: Celery Beat (schedules metrics collection)
./run_celery_beat.sh
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

## Dashboard

Access the live dashboard at: **http://localhost:8000/dashboard**

### Features

- **Pipeline Overview**: Real-time view of all 4 pipeline services
- **Job Queue**: Monitor pending/processing/completed jobs
- **Live Metrics Chart**: Time-series visualization with:
  - **Time Windows**: 5 minutes, 1 hour, 24 hours
  - **Service Selection**: Discovery, Browsing, Enrichment, Verification, All
  - **Auto-refresh**: Updates every 30 seconds via Celery Beat

### Dashboard API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/dashboard/stats` | Get pipeline statistics, job counts, service status |
| `GET /api/v1/dashboard/metrics?service=discovery&window=5m` | Get time-series metrics |
| `WS /api/v1/dashboard/ws` | WebSocket for real-time updates |

### Metrics Parameters

| Parameter | Options | Description |
|-----------|--------|-------------|
| `service` | `discovery`, `browsing`, `enrichment`, `verification`, `all` | Which service to query |
| `window` | `5m`, `1h`, `24h` | Time window for data |

### Example API Calls

```bash
# Get dashboard stats
curl http://localhost:8000/api/v1/dashboard/stats

# Get metrics for last 5 minutes (all services)
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"

# Get metrics for last 1 hour (specific service)
curl "http://localhost:8000/api/v1/dashboard/metrics?service=discovery&window=1h"

# Get metrics for last 24 hours
curl "http://localhost:8000/api/v1/dashboard/metrics?service=enrichment&window=24h"
```

### Metrics Collected

| Service | Metrics |
|---------|---------|
| **Discovery** | `companies_total`, `jobs_pending`, `jobs_completed`, `jobs_failed` |
| **Browsing** | `pages_browsed`, `contacts_found` |
| **Enrichment** | `emails_collected`, `domains_processed` |
| **Verification** | `contacts_total`, `verified_count` |

## Celery Services

The pipeline uses Celery for asynchronous task processing and scheduling.

### Celery Worker

Processes tasks from multiple queues:

| Queue | Purpose |
|-------|---------|
| `discovery` | Discovery job processing |
| `browsing` | Company browsing tasks |
| `enrichment` | Email enrichment tasks |
| `verification` | Email verification tasks |
| `default` | System tasks (metrics collection) |

```bash
# Start Celery worker
./run_celery_worker.sh

# Or with specific queues:
./run_celery_worker.sh discovery,browsing,enrichment,verification,default
```

### Celery Beat

Scheduler that triggers periodic tasks:

- **Metrics Collection**: Every 30 seconds, collects current pipeline metrics and stores them in `service_metrics` table
- **Auto-cleanup**: Removes metrics data older than 24 hours

```bash
# Start Celery Beat
./run_celery_beat.sh
```

## Configuration

Each service has its own `.env` file and config.py:

| Service | Config File | Key Settings |
|---------|-------------|--------------|
| Discovery | `01_discovery/config.py` | `DISCOVERY_POLL_INTERVAL`, `MAX_JOB_RETRIES` |
| Browsing | `01b_browsing/config.py` | `BROWSING_TIMEOUT_DOMAIN`, `SCORE_MAX` |
| Enrichment | `02_enrichment/config.py` | `TARGET_EMAILS_PER_DOMAIN`, `ENRICHMENT_TIMEOUT_DOCKER` |
| Verification | `03_verification/config.py` | `SMTP_TIMEOUT`, `VERIFIER_POLL_INTERVAL` |
| API | `04_api/config.py` | `REDIS_URL`, `API_HOST`, `API_PORT`, `ALLOWED_ORIGINS` |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | (required) | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for Celery |
| `API_HOST` | `0.0.0.0` | API server host |
| `API_PORT` | `8000` | API server port |

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

### Services Not Starting

```bash
# Check if PostgreSQL is running
psql -d leadgen_db -c "SELECT 1;"

# Check if Redis is running
redis-cli ping

# Check if Docker is running
docker ps
```

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

### Celery Worker Not Processing Tasks

```bash
# Check worker is running
ps aux | grep celery

# Check queues
redis-cli LLEN discovery
redis-cli LLEN browsing
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

1. Ensure Celery Beat is running to collect metrics
2. Wait up to 30 seconds for first data point
3. Check browser console for errors
4. Verify API returns data:
```bash
curl "http://localhost:8000/api/v1/dashboard/metrics?service=all&window=5m"
```

### Database Connection Issues

Verify connection:
```bash
psql -d leadgen_db -c "SELECT 1;"
```

## API Reference

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/jobs` | List all jobs |
| POST | `/api/v1/jobs` | Create new job |
| GET | `/api/v1/jobs/{id}` | Get job details |

### Companies

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/companies` | List companies |
| GET | `/api/v1/companies/{id}` | Get company details |

### Contacts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/contacts` | List contacts |
| GET | `/api/v1/contacts/{id}` | Get contact details |

### Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/services/status` | Get all service statuses |
| POST | `/api/v1/services/{service}/start` | Start a service |
| POST | `/api/v1/services/{service}/stop` | Stop a service |

### Dashboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/dashboard/stats` | Get pipeline statistics |
| GET | `/api/v1/dashboard/metrics` | Get time-series metrics |
| WS | `/api/v1/dashboard/ws` | WebSocket for real-time updates |

## License

MIT
