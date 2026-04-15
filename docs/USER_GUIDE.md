# Lead Generation Engine - User Guide

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Creating Jobs](#creating-jobs)
5. [Understanding the Pipeline](#understanding-the-pipeline)
6. [Monitoring Progress](#monitoring-progress)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)
9. [API Reference](#api-reference)

---

## Overview

This is an automated lead generation system that:
1. **Discovers** companies from search results
2. **Browses** their websites to score quality
3. **Enriches** with contact emails
4. **Verifies** email validity

Each stage runs as an independent service that polls the database for work.

---

## Prerequisites

### Software Requirements
- **PostgreSQL** 12+ (running locally or remote)
- **Docker** (for theHarvester email extraction)
- **Python** 3.12

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

---

## Quick Start

### 1. Start All Services

Open 4-5 terminal windows:

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

# Terminal 4: Verification Service (optional)
cd ~/lead_gen2
./run_verification.sh

# Terminal 5: API (optional)
cd ~/lead_gen2
./run_api.sh
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

---

## Creating Jobs

### Job Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `keyword` | Yes | Search term for finding companies |
| `region` | No | Target region (e.g., "india", "china", "germany") |

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
- Contact page link: +2
- Physical address: +2
- Social links: +1
- Email on homepage: +2
- Language match: +1
- Page loaded: +1 (base)

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

---

## Configuration

### Service Settings

Each service can be configured via environment variables or `.env` files:

| Service | Key Settings |
|---------|--------------|
| Discovery | `DISCOVERY_POLL_INTERVAL`, `MAX_JOB_RETRIES` |
| Browsing | `BROWSING_TIMEOUT_DOMAIN`, `SCORE_MAX`, `BROWSING_WATCHDOG_MINUTES` |
| Enrichment | `TARGET_EMAILS_PER_DOMAIN`, `ENRICHMENT_TIMEOUT_DOMAIN` |
| Verification | `SMTP_TIMEOUT`, `VERIFIER_POLL_INTERVAL` |

### TLD and City Scoring

To modify scoring:
1. Edit `01_discovery/config/tld_scores.yaml`
2. Edit `01_discovery/config/city_keywords.yaml`
3. Changes are picked up automatically on next poll

---

## Troubleshooting

### Service Won't Start

```bash
# Check if port is already in use
lsof -i :8000

# Check Python environment
source venv/bin/activate
python -c "import sqlalchemy; print('OK')"
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
```
GET    /api/v1/jobs          - List all jobs
POST   /api/v1/jobs          - Create new job
GET    /api/v1/jobs/{id}    - Get job details
```

#### Companies
```
GET    /api/v1/companies             - List companies
GET    /api/v1/companies/{id}       - Get company details
```

#### Contacts
```
GET    /api/v1/contacts             - List contacts
GET    /api/v1/contacts/{id}        - Get contact details
```

### Example API Calls

```bash
# Create a job
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"keyword": "marketing agency", "region": "usa"}'

# List companies
curl http://localhost:8000/api/v1/companies?status=browsed&limit=10

# Check API health
curl http://localhost:8000/health
```

---

## Support

For issues or questions, check:
1. Service logs in terminal output
2. Database status queries above
3. PostgreSQL logs (`/var/log/postgresql/`)