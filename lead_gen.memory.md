---
# lead_gen — Project Memory

## Overview
- What this project does: Multi-service lead generation pipeline that discovers companies, browses their websites for signals, enriches with contact emails, and verifies email addresses
- Tech stack: Python, PostgreSQL, Redis, Celery, Docker, FastAPI
- Environment details: Linux (Kali/Ubuntu/Debian), Python 3.13, PostgreSQL 17, Redis
- Project goals: Automated lead generation through discovery, enrichment, and verification of business contacts

## Current Status
- [x] Project structure analyzed
- [x] Discovery service implementation reviewed
- [x] Browsing service implementation reviewed  
- [x] Enrichment service implementation reviewed
- [x] Verification service implementation reviewed
- [x] API service implementation reviewed
- [x] Memory file created and initialized
- [x] Setup process understood
- [x] All 5 service venvs rebuilt and validated
- [x] Dashboard API working (dashboard/stats returns data)
- [x] PostgreSQL authentication fixed
- [x] Pipeline Control toggle (Auto/Manual mode) implemented
- [x] Manual mode services not starting fixed (subprocess env + PATH)
- [x] Full logging audit and enhancement (15 files, 89 insertions)
- [x] Service log files normalized to INFO level (was WARNING only)
- [x] API endpoint logging added (7 endpoint files + process_manager lifecycle)
- [x] API log propagation fixed (root logger handler at INFO level)
- [x] Modal popups fixed - show immediately with loading spinner instead of waiting for API fetch
- [x] Service metrics fixed - all 4 services write metrics every 60s
- [x] Metric names aligned with frontend (companies_found → companies_total)
- [x] Timezone bug fixed in GET /dashboard/metrics (local → UTC)
- [x] Added write_metrics() to browsing, enrichment, verification services
- [x] Installed httpx in verification venv
- [x] process_manager PATH fix - always set standard dirs

## Architecture
- Services and how they connect: 5 microservices (Discovery, Browsing, Enrichment, Verification, API) communicating via PostgreSQL database and Redis/Celery
- Data flow: Discovery → Browsing → Enrichment → Verification, with status tracking in database
- Key files and their purpose:
  - 01_discovery/main.py: Discovery service entry point
  - 01b_browsing/main.py: Browsing service entry point
  - 02_enrichment/main.py: Enrichment service entry point
  - 03_verification/main.py: Verification service entry point
  - 04_api/main.py: API service entry point (FastAPI with lifespan context manager)
  - shared_models/: Shared database models across all services
  - setup.sh: Automated setup script for infrastructure
  - deploy.sh: Deployment script with venv health checks

## Key Decisions
- **Pipeline Architecture**: Using standalone polling services (NO Celery) for pipeline processing
- **Celery Infrastructure**: Exists but NOT integrated (optional for future distributed processing)
- Implementing two-phase retry system (discovered → requeued → failed) for resilience
- Using Docker container for theHarvester email extraction tool
- Heartbeat mechanisms to detect and recover from stalled processes
- Modular design with shared models ensuring data consistency
- Virtual environments must be proper isolated Python environments (not symlinks to system Python)
- WebSocket with HTTP polling fallback for dashboard real-time updates

## Setup & Deploy Scripts

### setup.sh
- `--check` flag for dry-run idempotency
- `--force` flag to override existing configs
- Auto-detect OS (Kali/Ubuntu/Debian)
- Backup existing files to `/var/backups/lead_gen/`
- Sequential numbering (1-15)
- Health check functions for PostgreSQL, Docker, Redis, Nginx
- Idempotent: checks existing state before creating
- Docker check with `command -v docker` before apt install
- Git clone: checks if repo exists, uses pull instead of clone
- **Venv creation fix**: Uses `--clear` flag and detects symlinked venvs (broken venvs)
- Clear port detection for SearXNG
- Pre-flight checks at startup

### deploy.sh
- `--dry-run` flag for pre-deployment validation (10 checks)
- `--skip-restart` flag for code-only updates
- `--rollback` flag to revert to previous deployment
- `--rebuild-venv` flag to force rebuild all virtual environments
- `--help` flag for usage info
- No hardcoded `ubuntu` fallback - uses proper user detection
- Sequential service restart with delays
- **Venv health check**: `check_venv_health()` detects symlinked (broken) venvs
- **Venv rebuild function**: `rebuild_venv()` recreates venv with proper isolated Python
- Venv health check runs in dry-run and auto-fixes on deploy
- Health check includes dashboard stats endpoint validation
- Code backup before git pull (keeps last 5 backups)
- Clear exit codes (0 success, 1 failure)

## Dashboard & WebSocket

### Dashboard.py Fixes
- `ConnectionManager` class manages WebSocket connections
- `start_heartbeat()` uses `asyncio.get_running_loop()` instead of `asyncio.create_task()`
- Heartbeat pings clients every 30 seconds to keep connections alive
- `request_update` message handler for manual refresh requests
- Timeout handling (60s wait for client messages)

### Dashboard.html Fixes
- `wsMode` toggle ('websocket' or 'polling')
- `switchToPolling()` for graceful degradation
- `startPolling()` with 15s HTTP polling fallback
- `updateConnectionStatus()` indicator (WS Connected/Reconnecting/Polling)
- Improved reconnection using `setTimeout` instead of `setInterval`
- Handles server `ping`/`pong` messages
- Connection status indicator in top-right corner

### Main.py (API)
- Added `lifespan` async context manager for startup/shutdown
- Starts WebSocket heartbeat on app startup
- Stops heartbeat on app shutdown

### Nginx Config (in setup.sh)
- Explicit `/api/v1/dashboard/ws` location block
- 24-hour timeout for WebSocket connections (86400s)
- `proxy_http_version 1.1` for WebSocket upgrade
- `proxy_set_header Upgrade $http_upgrade` and `Connection "upgrade"`

## Known Issues
- PostgreSQL password stored in `.env` must match PostgreSQL user password
- Kali user may need peer auth via Unix socket: `psql -h /var/run/postgresql -U kali -d lead_gen`
- Nginx config update requires sudo (copy to /etc/nginx/sites-available/)
- Systemd service management requires sudo

## Celery Infrastructure (Not Active)

### Current Status
| Component | Status | Notes |
|-----------|--------|-------|
| Celery Beat | ❌ Not running | Would run periodic tasks |
| Celery Worker | ❌ Not running | Would process queue tasks |
| Redis | ✅ Running | Used for API (not Celery) |
| Tasks | ⚠️ Placeholder | Don't call actual services |

### Files (for future reference)
- `04_api/celery_tasks/` - Celery app and tasks
- `run_celery_beat.sh` - Beat scheduler script
- `run_celery_worker.sh` - Worker script

### Decision (2026-05-20)
**Keep current polling architecture.** Rationale:
- Services already have watchdog + heartbeat
- Single-server deployment (no distributed requirement)
- Simpler = less maintenance
- Celery tasks are incomplete placeholders

### When to Use Celery (Future)
- Multi-server distributed processing
- Task prioritization needed
- Celery's built-in retry/rate limiting required

### Cleanup (Optional)
To remove Celery code entirely:
- Delete `04_api/celery_tasks/`
- Delete `run_celery_beat.sh`
- Delete `run_celery_worker.sh`
- Update setup.sh to remove Celery installation

## Critical Fixes Applied (2026-05-20)

### 1. Venv Creation Issue (CRITICAL)
**Problem**: On some systems (Kali), `python3 -m venv` creates venvs with symlinks to system Python instead of proper isolated environments.

**Files affected**: setup.sh, deploy.sh

**Fix in setup.sh**:
```bash
# Detect broken venvs (symlinks)
if [ -L "$PROJECT_DIR/$svc/venv/bin/python" ]; then
    rm -rf "$PROJECT_DIR/$svc/venv"
fi

# Use --clear flag to force clean venv creation
python3 -m venv --clear "$PROJECT_DIR/$svc/venv"
```

**Fix in deploy.sh**:
```bash
# check_venv_health() - detects symlinked venvs
# rebuild_venv() - recreates with proper isolated Python
# --rebuild-venv flag for manual rebuild
```

### 2. WebSocket Heartbeat Issue
**Problem**: `asyncio.create_task()` called at module import time when no event loop exists.

**Files affected**: 04_api/api/v1/endpoints/dashboard.py, 04_api/main.py

**Fix**: Moved heartbeat start/stop to `lifespan` async context manager in main.py

### 3. PostgreSQL Authentication
**Problem**: Password in `.env` didn't match PostgreSQL user password, causing 500 errors.

**Fix**: Connected via peer auth using Unix socket and reset password:
```bash
psql -h /var/run/postgresql -U kali -d lead_gen -c "ALTER USER kali WITH PASSWORD 'fjp6LWRYJWAYC7j5';"
```

## Session Log
### 2026-05-20
- Initial project analysis completed
- Project structure examined: 5 service directories, shared models, setup scripts
- Memory file created: lead_gen.memory.md
- README reviewed to understand architecture and pipeline flow
- Discovery service implementation reviewed in detail
- Browsing service implementation reviewed in detail
- Enrichment service implementation reviewed in detail
- Verification service implementation reviewed in detail
- API service implementation reviewed in detail
- Setup process understood by examining setup.sh

### 2026-05-20 (continued): Script Improvements
- Reviewed original setup.sh and deploy.sh
- Identified issues: no idempotency, hardcoded ubuntu, no health checks, no rollback
- Improved setup.sh with --check, --force flags, auto OS detection, backup
- Improved deploy.sh with --dry-run, --skip-restart, --rollback, --rebuild-venv flags
- Added venv health check and rebuild functions
- Fixed Docker install check and Git clone logic

### 2026-05-20 (debugging session): Dashboard Issues
- Dashboard returned Internal Server Error (500)
- Root cause identified: venvs were symlinks to system Python (broken)
- Root cause: PostgreSQL password didn't match
- Fixed all 5 service venvs by recreating with proper isolated environments
- Fixed PostgreSQL authentication via peer auth on Unix socket
- Added lifespan context manager to main.py for WebSocket heartbeat
- Dashboard now working: /api/v1/dashboard/stats returns data
- API health endpoint working: /health returns {"status":"healthy"}
- WebSocket with polling fallback implemented
- Nginx config needs sudo to update (WebSocket support)

### Commands to Fix Dashboard Issues
```bash
# Fix PostgreSQL password
psql -h /var/run/postgresql -U kali -d lead_gen -c "ALTER USER kali WITH PASSWORD 'fjp6LWRYJWAYC7j5';"

# Rebuild all venvs
for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
    rm -rf $svc/venv
    python3 -m venv --clear $svc/venv
    $svc/venv/bin/pip install --upgrade pip --quiet
    $svc/venv/bin/pip install -r $svc/requirements.txt --quiet
done

# Restart API
pkill -f 'uvicorn main:app'
cd /home/kali/lead_gen/04_api && ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000 &

# Update nginx (requires sudo)
sudo tee /etc/nginx/sites-available/lead_gen > /dev/null << 'NGINX'
server {
    listen 80;
    server_name _;
    proxy_connect_timeout 60s;
    proxy_send_timeout 3600s;
    proxy_read_timeout 86400s;
    location / { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_buffering off; }
    location /api/v1/dashboard/ws { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_set_header Host $host; proxy_buffering off; proxy_read_timeout 86400s; }
}
NGINX
sudo systemctl reload nginx
```

### 2026-05-20 (final): Celery Discussion
- Analyzed Celery Beat and Worker infrastructure
- Reviewed `04_api/celery_tasks/tasks.py` - found placeholder implementations
- Reviewed `run_celery_beat.sh` and `run_celery_worker.sh`
- **Decision**: Keep current polling architecture
- **Reason**: Services have robust watchdog/heartbeat, single-server deployment
- **Future**: Celery optional if distributed processing needed
- Updated memory with Celery decision and rationale

### 2026-05-20 (service management session): Process Manager & Run Scripts
- Fixed process_manager.py to properly handle service starting and status detection
- Fixed run_discovery.sh, run_browsing.sh, run_enrichment.sh, run_verification.sh to run from service directory
- Process detection now uses dual method: script name OR service_dir/main.py pattern
- Added SERVICE_DIR config mapping in SERVICES dict
- Services now track uptime and start_time correctly
- Fixed zombie process cleanup in ProcessManager

**Files modified**:
- 04_api/services/process_manager.py - major refactor
- run_*.sh scripts - fixed cwd to service directories
- setup.sh - added --copies flag for venv
- deploy.sh - added --copies flag for venv

**Key fixes**:
1. Service scripts must be in both project root AND service directories
2. process_manager.py starts services with `cwd=service_dir` for correct venv resolution
3. Status detection fallback checks for service_dir/venv/bin/python pattern
4. Venvs must use --copies flag to avoid symlinks on Kali

### 2026-05-20 (service management fix): Critical Run Script Bug Fixed

**Problem Found**: The run scripts had `SERVICE_DIR="$SCRIPT_DIR/01_discovery"` which created wrong paths like `/home/kali/lead_gen/01_discovery/01_discovery`.

**Fix Applied**: Changed all run scripts to use `SERVICE_DIR="$SCRIPT_DIR"` since scripts are already in the service directory.

**Test Results**:
- Stop/Start all services via API: ✅ Working
- Dashboard reflects correct status: ✅ Working
- Process detection accurate: ✅ Working
- Need 1-2 second delay between consecutive starts to avoid lock conflicts

### 2026-05-20 (systemd conflict fix): Services Respawning After Stop

**Problem**: Services kept coming back up after being stopped via API. Systemd services had `Restart=always` which caused them to respawn.

**Root Cause**: Systemd services with `Restart=always` and `RestartSec=10` were monitoring and restarting killed processes.

**Solution**: Disabled systemd services so API has full control:
```bash
# Stop and disable all systemd services
for svc in discovery browsing enrichment verification api; do
    sudo systemctl stop leadgen-$svc.service
    sudo systemctl disable leadgen-$svc.service
done
```

**Verification**: Services now stay stopped when API stop is called. No respawning.

### 2026-05-20 (pipeline control toggle): Auto/Manual Mode Toggle

**Feature**: Added 3D toggle switch in the pipeline section to switch between Auto (systemd) and Manual (API) control modes.

**Location**: Left side of pipeline section, above the pipeline nodes
- Title: "Control" with ⓘ info icon
- Toggle: 3D pill switch with "Auto" and "Manual" labels (appear on hover)
- Badge: Shows current mode (Manual/blue or Auto/green)

**Layout**: Grid-based responsive design
```
┌──────────────────────────────────────────────────────────────────────┐
│ Control │        gap        │        Nodes (centered)               │
│   40px  │      (auto)       │     ←—— centered ———→                 │
└──────────────────────────────────────────────────────────────────────┘
```

**CSS Structure**:
```css
.pipeline-container {
    display: grid;
    grid-template-columns: 40px auto 1fr;
    grid-template-areas: "control gap nodes";
    align-items: center;
}
```

**Files Modified**:
1. `04_api/services/process_manager.py` - Added `get_mode()` and `set_mode()` functions
2. `04_api/api/v1/endpoints/services.py` - Added `GET /services/mode` and `POST /services/mode`
3. `04_api/templates/dashboard.html` - Toggle UI, CSS, JS, confirmation modal

**Backend Endpoints**:
- `GET /api/v1/services/mode` - Returns `{"mode": "api" | "systemd"}`
- `POST /api/v1/services/mode` - Body: `{"mode": "api" | "systemd"}`

**Mode Behavior**:
| Mode | Label | Badge | Behavior |
|------|-------|-------|----------|
| Manual (api) | Blue | Blue glow | API controls services |
| Auto (systemd) | Green | Green glow | Systemd auto-restarts |

**When switching to Auto (systemd)**:
1. Enable all 4 systemd services: `leadgen-{discovery,browsing,enrichment,verification}.service`
2. Already running services → just enable
3. Stopped services → enable AND start

**When switching to Manual (api)**:
1. Stop all systemd services
2. Disable all systemd services

**Info Icon Tooltip** (hover):
> **Manual:** You control when services run. Good for debugging.
> **Auto:** Services restart automatically if they crash. Good for production.

**Responsive Breakpoints**:
| Screen | Control Width | Layout |
|--------|--------------|--------|
| Desktop (>900px) | 40px | Grid: control + gap + centered nodes |
| Tablet (600-900px) | 40px | Same grid |
| Mobile (<600px) | 100% | Stacked vertically |

**Toggle Styling** (3D effect):
- Toggle size: 40x22px (reduced from 56x30px)
- Knob: 14px circle with gradient and shadow
- Smooth animation: 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55)
- Glow effect on track when in Auto mode
- Labels visible on hover with opacity transition

## Reconstruction Log (2026-05-21)

### Incident: VM crash + deploy.sh overwrote uncommitted changes
- User pulled from `test` branch via deploy.sh after VM restart
- All changes from 2026-05-20 session were lost (never committed)
- Reconstruction performed from memory file documentation
- All 8 phases completed successfully

### Files Reconstructed
1. **04_api/services/process_manager.py** - Full rewrite
   - Added `service_dir` to SERVICES config
   - Fixed `start_service()` cwd to use service_dir
   - Dual process detection (script name + main.py pattern)
   - Added `get_mode()` and `set_mode()` functions
   - Fixed zombie process cleanup with dual kill patterns
   
2. **04_api/api/v1/endpoints/services.py** - Added mode endpoints
   - `GET /services/mode` returns current control mode
   - `POST /services/mode` switches between api/systemd
   
3. **04_api/main.py** - Added lifespan context manager
   - `async def lifespan(app)` for startup/shutdown
   - WebSocket heartbeat started on app startup
   - Heartbeat stopped on app shutdown
   
4. **04_api/api/v1/endpoints/dashboard.py** - Fixed WebSocket
   - Added `request_update` message handler
   - Added 60s timeout for client messages
   - Fixed `broadcast_update()` to use `asyncio.get_running_loop()`
   - Removed bare `asyncio.create_task()` at module level
   
5. **04_api/templates/dashboard.html** - Major UI updates
   - Added pipeline control toggle (Auto/Manual mode)
   - Added connection status indicator (WS Connected/Reconnecting/Polling)
   - Added `wsMode` toggle with `switchToPolling()` fallback
   - Added `startPolling()` with 15s HTTP polling
   - Changed reconnection from `setInterval` to `setTimeout`
   - Added ping/pong handler
   - Added mode confirmation modal
   - Grid layout for pipeline: `"control gap nodes"`
   
6. **setup.sh** - Complete rewrite
   - `--check` flag for dry-run idempotency
   - `--force` flag to override existing configs
   - Auto-detect OS (Kali/Ubuntu/Debian)
   - Backup to `/var/backups/lead_gen/`
   - Sequential numbering (1-15)
   - Health check functions (PostgreSQL, Docker, Redis, Nginx)
   - Docker check with `command -v docker`
   - Git clone: checks if repo exists, uses pull
   - Venv: `--clear --copies` + symlink detection
   - SearXNG port detection
   - Pre-flight checks
   
7. **deploy.sh** - Complete rewrite
   - `--dry-run` flag (10 pre-deployment checks)
   - `--skip-restart` flag
   - `--rollback` flag
   - `--rebuild-venv` flag
   - `--help` flag
   - No hardcoded `ubuntu` fallback
   - `check_venv_health()` function
   - `rebuild_venv()` function
   - Code backup before pull (keeps 5)
   - Sequential restart with 2s delays
   - Dashboard endpoint validation
   - Clear exit codes
   
8. **nginx config** - WebSocket block added
   - Dedicated `/api/v1/dashboard/ws` location
   - 86400s timeout for WebSocket
   - 60s connect timeout, 3600s send timeout
   
9. **run_*.sh scripts** (root level) - Fixed from service dir copies

### Nginx Update Required (manual)
Run: `sudo cp /home/kali/lead_gen/nginx_config_updated.conf /etc/nginx/sites-available/lead_gen && sudo systemctl reload nginx`

## WebSocket Reconnection Fix (2026-05-21)

### Problem
WebSocket kept disconnecting and reconnecting in a loop.

### Root Causes
1. **Missing `import asyncio` in dashboard.py** - The file used `asyncio.wait_for()` and `asyncio.sleep()` but never imported asyncio, causing a `NameError` that crashed the WebSocket handler immediately after connection.

2. **Double Heartbeat Conflict** - Two separate heartbeat mechanisms running simultaneously:
   - `main.py` lifespan started `ws_heartbeat()` function that pinged every 30s
   - `dashboard.py` endpoint handler had a 60s timeout that also sent pings
   - Race conditions between the two caused connection drops.

3. **`start_heartbeat()` Method Never Used** - The `ConnectionManager.start_heartbeat()` method was defined but never called. Instead, main.py created its own separate heartbeat function.

### Fixes Applied
1. **dashboard.py**: Added `import asyncio` to imports
2. **dashboard.py**: Simplified WebSocket handler - removed the 60s timeout logic, now just waits for messages indefinitely. The heartbeat task handles keep-alive.
3. **main.py**: Removed the standalone `ws_heartbeat()` function. Changed lifespan to call `manager.start_heartbeat()` instead (uses ConnectionManager's built-in method).

### Verification
- WebSocket connects successfully
- Server sends ping after ~30s
- Client responds with pong
- Connection stays stable without reconnection loops

### Important Note
When running uvicorn, do NOT use `reload=True` in production as it spawns multiple worker processes that can cause database connection pool exhaustion. Use `reload=False` or omit the flag.

## Control Toggle Fix (2026-05-21)

### Problem 1: HTTP Error on Mode Switch
**Error:** `{"detail":"[Errno 2] No such file or directory: 'sudo'"}`

**Root cause:** `process_manager.py:set_mode()` calls `subprocess.run(['sudo', 'systemctl', ...])` but `sudo` may not be available in the API's PATH. The error caused a 500 response.

**Fix:** Wrapped systemd commands in try/except FileNotFoundError. Mode file is always saved first, then systemd commands are attempted. If sudo is missing, returns success with a warning field.

### Problem 2: Toggle Checkbox Didn't Revert on Failure
**Root cause:** JavaScript `confirmModeSwitch()` caught the error but left the checkbox in the new (failed) position.

**Fix:** Save `previousMode` before attempting switch. On error, revert checkbox: `input.checked = previousMode === 'systemd'`.

### Problem 3: Toggle Labels Not Visible
**Root cause:** CSS used sibling selectors (`~`) with incorrect HTML structure. Labels were nested inside `<label>` element but CSS expected them as siblings of `<input>`.

**Fix:** Simplified CSS - labels always visible below toggle, color changes based on state. Removed broken opacity-based hover effect.

### Verification
- `POST /api/v1/services/mode` returns `{"mode":"api"}` or `{"mode":"systemd"}` successfully
- When sudo unavailable: returns `{"mode":"api","warning":"Mode saved, but systemd commands skipped..."}`
- Dashboard toggle checkbox reverts correctly on failure
- Toggle labels display correctly

### Manual Action Required: Update Sudoers File
The existing `/etc/sudoers.d/leadgen` file (created May 20) only has start/stop/restart commands. It needs enable/disable commands for the mode toggle to work properly.

**Run this command:**
```bash
sudo cp /home/kali/lead_gen/sudoers_leadgen /etc/sudoers.d/leadgen && sudo chmod 440 /etc/sudoers.d/leadgen
```

**Verify with:**
```bash
sudo -l | grep leadgen
```
Should show: `NOPASSWD: /bin/systemctl start leadgen-*, /bin/systemctl stop leadgen-*, /bin/systemctl restart leadgen-*, /bin/systemctl enable leadgen-*, /bin/systemctl disable leadgen-*, /bin/systemctl daemon-reload`

## Manual Mode Services Not Starting Fix (2026-05-21)

### Problem
Services showed as "started" via API but immediately died. Dashboard showed all services as "stopped" in manual mode.

### Root Cause
`subprocess.Popen()` in `process_manager.py` created child processes with a minimal environment:
- `PATH` was empty or incomplete → `dirname`, `sleep`, `cat`, `rm` commands not found
- `PYTHONPATH` was not set → `shared_models` module not importable
- `pgrep` and `pkill` used without absolute paths → not found in minimal PATH

### Fix
1. Pass `env=os.environ.copy()` to `subprocess.Popen()` in `start_service()`
2. Explicitly set `env['PYTHONPATH'] = self.project_dir`
3. Ensure `env['PATH']` includes standard directories
4. Use absolute paths: `/usr/bin/pgrep`, `/usr/bin/pkill`

### Verification
All 4 services start and stay running in manual mode:
```
discovery:    running (uptime: 21s)
browsing:     running (uptime: 7s)
enrichment:   running (uptime: 5s)
verification: running (uptime: 4s)
```

## Logging Audit & Enhancement (2026-05-21)

### Problem
1. **Service log files** (`logs/discovery.log`, etc.) only captured WARNING+ messages — normal operation logs (jobs processed, companies browsed, emails saved) were lost on restart
2. **API endpoints had no logging** — 7 of 7 endpoint files lacked `import logging` entirely
3. **process_manager.py** logged nothing for start/stop/restart/health lifecycle events
4. **dashboard.py** used `print()` instead of proper logging
5. **API file handler** was attached only to `uvicorn.error`/`uvicorn.access` — endpoint module logs were silently dropped

### Changes Made

#### 1. Normalized file handler levels (WARNING → INFO)
- `01_discovery/main.py:40`
- `01b_browsing/main.py:36`
- `02_enrichment/main.py:45`
- `03_verification/main.py:36`
- `04_api/main.py:82`

#### 2. Added logging to all API endpoints (+ lifecycle logging)
| File | What is logged |
|---|---|
| `endpoints/services.py` | Start/stop/restart requests + results, mode changes, health checks, log requests |
| `endpoints/dashboard.py` | WebSocket connect/disconnect/errors (replaced `print()`) |
| `endpoints/companies.py` | Company list errors, specific company lookups |
| `endpoints/contacts.py` | Contact list errors, specific contact lookups |
| `endpoints/search.py` | Search failures |
| `endpoints/export.py` | Export/preview email counts |
| `endpoints/verification.py` | Single email verify results |
| `services/process_manager.py` | Start/stop/restart entry + success/PID + errors, health checks |

#### 3. Fixed API log propagation
- Added file handler to root logger with level INFO so module loggers propagate through
- Converted `print()` calls in `main.py` lifespan to `logger.info()`

#### 4. Minor module logging
- Added `import logging` to `email_extractor.py`, `job_stats_service.py`

### Verification
- `api.log` now shows endpoint-specific messages:
  - `"Health check: healthy (2/4 running)"`
  - `"Start requested: discovery"` → `"Starting service: discovery"` → `"Service discovery started (PID: 212170)"` → `"Start succeeded: discovery"`
  - `"Email verify: test@example.com -> valid_verified"`
  - `"Preview 386 emails (verified=True, limit=5, search=None)"`
- `discovery.log` has INFO entries (previously only WARNING+)

## Service Metrics Debug & Fix (2026-05-21)

### Problems Found
1. **Only discovery wrote metrics** — browsing, enrichment, verification had no `write_metrics()` functions
2. **Metric name mismatch** — discovery wrote `companies_found` but frontend expected `companies_total`
3. **Timezone bug** — `GET /dashboard/metrics` used `datetime.now()` (local) for cutoff instead of UTC, causing wrong data window
4. **Duplicate code in browsing** — `run_browser()` had duplicate company processing blocks after metrics write
5. **Metrics skipped on idle** — enrichment and verification used `continue` in idle branches, skipping metrics writes
6. **Missing httpx** — verification service venv lacked httpx dependency
7. **PATH issue** — process_manager only set PATH when empty, causing `dirname/sleep/cat not found` errors

### Fixes Applied
| File | Change |
|---|---|
| `01_discovery/main.py` | Renamed `companies_found`→`companies_total`, added `jobs_processing`, `jobs_completed`, `jobs_failed` |
| `01b_browsing/main.py` | Added `write_metrics()` (pages_browsed, domain_browsed, domain_failed, enrich_requeued), fixed duplicate code |
| `02_enrichment/main.py` | Added `write_metrics()` (emails_collected, domains_processed, enrich_requeued, domain_enriching), removed idle skip |
| `03_verification/main.py` | Added `write_metrics()` (contacts_total, verified_count, invalid_count, pending_count, needs_retry), removed idle skip |
| `04_api/api/v1/endpoints/dashboard.py` | Fixed timezone: `datetime.now()` → `datetime.now(timezone.utc)` |
| `dashboard.html` | Added `jobs_processing`, `domain_enriching`, `needs_retry` to metricColors |
| `process_manager.py` | Always set PATH (prepend standard dirs to existing PATH) |
| `03_verification/venv` | Installed httpx |

### Verified
All 4 services writing metrics every 60 seconds:
- Discovery: companies_total, jobs_pending, jobs_processing, jobs_completed, jobs_failed
- Browsing: pages_browsed, domain_browsed, domain_failed, enrich_requeued
- Enrichment: emails_collected, domains_processed, enrich_requeued, domain_enriching
- Verification: contacts_total, verified_count, invalid_count, pending_count, needs_retry
- "All services" view works with service-prefixed metric keys
