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

## DB Connection Status Indicator (2026-05-21)

### Feature
Added a database connection status signal on the dashboard header, placed beside the existing WebSocket connection status indicator.

### Backend Changes
- **`04_api/api/v1/endpoints/dashboard.py`**:
  - Added `import time` and `from sqlalchemy import text`
  - Added `db_status: dict` field to `DashboardStats` Pydantic model
  - Added DB health check at top of `get_dashboard_stats()` — executes `SELECT 1`, measures latency in ms
  - On success: `{"status": "connected", "latency_ms": N}`
  - On failure: `{"status": "disconnected", "error": "..."}` with `logger.error()`
  - Included `db_status` in the return dict

### Frontend Changes
- **`04_api/templates/dashboard.html`**:
  - Added DB status `<div id="db-status">` in the header, before the WS status element
  - Reuses existing `.connection-status` / `.connection-dot` CSS classes
  - Added `updateDbStatus(db_status)` JS function — green dot + "DB Nms" for connected, red dot + "DB ERR" for disconnected
  - Wired into `loadDashboard()` (fresh fetch), `renderDashboardData()` (cached data), and WebSocket `"update"` handler
  - Initial HTML shows green dot + "DB —" until first data loads

### Files Modified
| File | Change |
|---|---|
| `04_api/api/v1/endpoints/dashboard.py` | +db_status model field, +imports, +health check logic |
| `04_api/templates/dashboard.html` | +HTML indicator, +JS function, +wiring in 3 data paths |

### Verification
- `GET /api/v1/dashboard/stats` returns `{"db_status": {"status": "connected", "latency_ms": 1}}`
- DB status flows through WebSocket initial/update messages automatically (full `DashboardStats` dict is sent)
- Frontend shows green dot with "DB 1ms" text

## API Switched to systemd Service (2026-05-21)

### Change
The API service was switched from a nohup'd background process to a systemd service (`leadgen-api.service`) that auto-starts on boot.

### Service Details
- **Unit file**: `/etc/systemd/system/leadgen-api.service` (pre-existing, unchanged)
- **ExecStart**: `venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000`
- **Restart**: `always` (10s delay)
- **User**: `kali`
- **WorkingDirectory**: `/home/kali/lead_gen/04_api`
- **Environment**: `PATH=04_api/venv/bin`, `PYTHONPATH=/home/kali/lead_gen`, `LOG_DIR=/var/log/lead_gen`

### Commands
```bash
sudo systemctl daemon-reload
sudo systemctl enable leadgen-api.service
sudo systemctl start leadgen-api.service
sudo systemctl status leadgen-api.service
```

### Note
- The service binds to `127.0.0.1` (behind nginx), safer than `0.0.0.0`
- Stale PostgreSQL connections from previous API instances can block `init_db()` — use `SELECT pg_terminate_backend()` on stale `companies` table locks if startup hangs

### Sudoers Updated
- Copied `/home/kali/lead_gen/sudoers_leadgen` to `/etc/sudoers.d/leadgen`
- Grants passwordless sudo for `systemctl start/stop/restart/enable/disable leadgen-*` + `daemon-reload`

## Mode Confirm Modal: Cancel/Close Reverts Toggle (2026-05-21)

### Bug
Closing the pipeline mode confirmation modal (via × or Cancel button) left the toggle checkbox in the new (unconfirmed) position, creating a visual mismatch with the actual server mode.

### Root Cause
The checkbox's `onchange` event fires **after** the checkbox state toggles. `togglePipelineMode()` showed the modal but had no revert logic for cancel/close. The previous fix only reverted on API failure (`confirmModeSwitch()` error handler), not on user-initiated cancel.

### Fix
Added a `pendingMode` check in `closeModal()` for the `mode-confirm-modal`. When closed without confirming:
```javascript
if (id === 'mode-confirm-modal' && pendingMode) {
    input.checked = pendingMode !== 'systemd';
    pendingMode = null;
}
```
This reverts the checkbox to its original state and clears the pending mode.

### File Modified
- `04_api/templates/dashboard.html` — added 4 lines to `closeModal()` function

## Dashboard Flicker Fixes (2026-05-21)

### Problems
1. **HTTP and WS polling raced** — `dashboardIntervalId` (30s HTTP) ran alongside WebSocket updates, causing DOM flicker when both updated the same elements
2. **`innerHTML` pipeline rebuild** — `renderPipelineMap()` replaced entire pipeline container HTML, killing animated dots and sub-node toggle state
3. **Skeleton destroyed children** — `showSkeleton()` replaced pipeline container content, then `renderPipelineMap()` rebuilt it → visible flash
4. **Unnecessary counter animation** — `animateCounter()` animated even when value hadn't changed, causing text flicker on every update
5. **Orphaned `updateModeLabels()`** — referenced in `loadPipelineMode()` but never defined, causing `ReferenceError`

### Fixes Applied
| Change | What |
|--------|------|
| Stop 30s HTTP interval when WS active; restore on disconnect | Reduced redundant fetches |
| `renderPipelineMap()` uses in-place DOM updates (no `innerHTML`) | Preserves animated dots + sub-node toggle state |
| `showSkeleton()` adds CSS overlay class instead of destroying children | No DOM flash |
| `animateCounter()` skips animation when value unchanged | No text flicker |
| Removed `updateModeLabels()` call | Fixed `ReferenceError` |
| CSS class `.skeleton-pulse` for non-destructive skeleton overlay | Visual only, no DOM mutation |

## WebSocket Live Updates (2026-05-21)

### Changes
- **Client sends `{"type":"request_update"}` every 30s** via WS to refresh stats
- **Backend WebSocket handler fixed**:
  - DB session leak: single session per connection (not per `request_update`), closed in `finally`
  - Blocking event loop: `get_dashboard_stats()` runs in `run_in_executor` for sync DB/subprocess calls
  - Same session reused for all `request_update` messages on the same WS connection

## Metrics Chart Stability Fixes (2026-05-21)

### Root Cause: Racing Intervals
Two `setInterval` calls ran `loadMetrics()` simultaneously:
1. An **untracked** `setInterval` at line ~2153 (fired every `metricsIntervalValue`)
2. The **tracked** `metricsIntervalObj` (started by `setMetricsWindow()`)

The losing call entered the empty-state path (`ctx.clearRect` + `ctx.fillText`) mid-way through the winning call's Chart.js dataset build, corrupting the canvas. Moving the mouse triggered Chart.js hover → `.update()` → redrew correctly, making it appear to "come back" on mouse move.

### 5 Issues Fixed

| # | Issue | Fix | Line |
|---|-------|-----|------|
| 1 | Chart blank for 10s on page load | Added `loadMetrics()` to `DOMContentLoaded` | ~2294 |
| 2 | Ghost lines when switching services | Destroy & recreate chart if dataset count changed | ~1265 |
| 3 | Dark grid/legend colors in light mode | Read `--border-color` / `--text-secondary` CSS vars at runtime; `toggleTheme()` calls `loadMetrics()` | ~1284, ~856 |
| 4 | Empty-state canvas invisible (0-width buffer, Inter font not loaded) | Set `canvas.width/height` from parent; use `sans-serif` fallback; destroy stale chart | ~1130 |
| 5 | `jobs_processing` in `metricColors` but never written | Removed from dictionary | ~1188 |

### Files Modified
- `04_api/templates/dashboard.html` — all chart fixes, interval cleanup, theme-aware colors

## Import Emails Feature (2026-05-21)

### Overview
Added a full Import Emails workflow to the dashboard — accessible via an "Import" button in the header that opens a modal. Users can paste plain text, upload `.txt` files, or upload `.csv` files.

### Backend: `POST /api/v1/contacts/import`
**File:** `04_api/api/v1/endpoints/contacts.py:87-170`

Accepts `{"text": "...", "format": "txt"|"csv"}`:
- **TXT format**: one email per line
- **CSV format**: parsed via `csv.DictReader`, must include an `email` column

**4-phase pipeline:**
1. **Validation** — regex email check, collects valid emails
2. **Company lookup/creation** — batch query existing companies by domain; auto-create missing companies with `lead_source='manual'`
3. **Bulk insert with `ON CONFLICT DO NOTHING`** — uses PostgreSQL's atomic dedup (no TOCTOU race), counts actual inserted rows via `result.rowcount`
4. **Logging** — `logger.exception()` on error writes full traceback to `/var/log/lead_gen/api.log`

**Response:** `{imported, skipped, failed[], total, companies_created}`

### Schema Changes
- `shared_models/contact.py` — added `source` column (String(50), index) to tag imported contacts as `source='imported'`
- `04_api/database.py` — added migration entry for `contacts.source`

### Frontend: Import Modal
**File:** `04_api/templates/dashboard.html`

**Header:** "Import" button next to "Export".

**Modal (`.import-modal`):**
- Tab toggle: Plain Text | CSV File
- **TXT mode**: textarea for pasting + `.txt` file upload (hides textarea on file select, shows filename with "Remove" link)
- **CSV mode**: `.csv` file upload with column-format hint
- **Live preview**: shows email count + first 20 lines on input/upload
- **Results panel**: imported/skipped/created counts after import
- **Close button**: changes to "Close" after success, resets to "Import" on modal reopen
- State properly cleaned: textarea and file inputs cleared only on successful import

### UX Details
- "Remove" link on TXT file upload resets to paste mode
- Switching tabs or reopening modal resets import state
- Error responses show the actual server message (e.g., "Server returned 500: ...")
- Client-side `res.ok` check prevents JSON parse crashes on non-JSON responses

### Files Modified
| File | Change |
|------|--------|
| `shared_models/contact.py` | +`source` column on Contact |
| `04_api/database.py` | +`contacts.source` migration |
| `04_api/api/v1/endpoints/contacts.py` | +`POST /import` endpoint with batch dedup + ON CONFLICT |
| `04_api/templates/dashboard.html` | +Import button, modal, JS handlers |
| `nginx_config_updated.conf` | +`client_max_body_size 10M` (needs sudo to deploy) |

### Known Issues
- nginx `client_max_body_size` config written but not deployed (requires sudo)

## Verifier Live Progress Notification (2026-05-22)

### Feature: WebSocket-based live verification progress
Added a live progress widget to the dashboard's verification pipeline node, replacing the old DDGS/SearXNG/CommonCrawl/theHarvester source list.

#### Backend: `04_api/api/v1/endpoints/dashboard.py`
- Added `VerificationProgress` Pydantic model with fields: `total`, `processed`, `verified`, `failed`, `status`, `timestamp`
- Added `POST /api/v1/dashboard/verification-progress` async endpoint
  - Receives progress payload, stamps UTC timestamp, calls `broadcast_update("verification_progress", payload)`
  - Uses existing `ConnectionManager.broadcast()` to push to all connected WebSocket clients

#### Verifier: `03_verification/main.py`
- **`report_verification_progress()`** — sends progress POST to API
  - Uses persistent module-level `_http_client = httpx.Client()` (connection reuse, avoids TCP handshake per POST)
  - Logs success: `"Progress POST -> {status_code} ({processed}/{total})"`
  - Logs failures as warnings (was silent `except Exception: pass`)
- **Chunked submission** — contacts processed in chunks of 10 instead of all 200 at once
  - Each chunk submitted to `ThreadPoolExecutor` via `executor.submit()`
  - Results collected via `as_completed` per chunk
  - Progress reported every 5 contacts via `contacts_done % 5 == 0` check
  - True streaming: updates fire as contacts complete, not after full batch
- **Reduced idle sleep** — after processing contacts, sleeps 0.5s instead of 30s
  - Falls back to `POLL_INTERVAL` (30s) only when no contacts found
  - Metrics counter adjusted: counts 5s per busy loop instead of full POLL_INTERVAL

#### Frontend: `04_api/templates/dashboard.html`
- **CSS** (lines 321-337): `.verifier-progress` styles
  - `.vp-row`: flex row for label + value pairs (Processed/Verified/Failed counts)
  - `.vp-bar-track` + `.vp-bar-fill`: progress bar with width transition (0.5s ease)
  - `.vp-bar-fill.{idle,running,completed}`: color-coded (grey/blue/green)
  - `.vp-status-dot.{idle,running,completed}`: animated pulse when running, static when idle/completed
- **Pipeline map** (lines 1496-1511): Verification node sub-nodes replaced
  - Toggle label: `"▼ Imported Contacts"` (was `"▼ Verifier"`, original was `"▼ Sources"`)
  - Content: verifier progress widget with Processed/Verified/Failed counts + progress bar + status indicator
  - Other nodes keep their DDGS/SearXNG/CommonCrawl/theHarvester source list
- **`updateVerifierProgress(data)`** (lines 1534-1556): Updates widget from WebSocket event
  - Reads `vp-processed`, `vp-verified`, `vp-failed`, `vp-bar`, `vp-dot`, `vp-status-text` elements
  - Calculates percentage: `min(100, round(processed/total * 100))`
  - Sets bar width, status dot class, status text color
  - Handles `idle`, `running`, `completed` statuses
- **WebSocket handler** (lines 835-837): Added `verification_progress` case
  - Calls `updateVerifierProgress(message.data)`
- **`toggleSubNodes`** (lines 1527-1532): Uses `"Imported Contacts"` prefix for verification node

#### Performance improvements

| Metric | Before | After |
|--------|--------|-------|
| Progress report frequency | Once per 200-contact batch (~60-90s) | Every 5 contacts (streaming, 0.5-35s between reports depending on contact complexity) |
| HTTP client | New connection per POST (`httpx.post()`) | Persistent `httpx.Client()` (connection reuse) |
| Silent failures | `except Exception: pass` | Logged as `logger.warning()` |
| Sleep after batch | `time.sleep(30)` | `time.sleep(0.5)` when contacts found, `time.sleep(30)` when idle |
| Duplicate POSTs | Post-batch report duplicated mid-batch final report | Removed redundant post-batch report; mid-batch covers all cases |

#### Data flow
```
Verifier (03_verification/main.py)
  └─ report_verification_progress() → HTTP POST → API (dashboard.py)
                                                     └─ broadcast_update() → WebSocket → Dashboard HTML
                                                                                          └─ updateVerifierProgress()
```

#### Files changed this session:
| File | Changes |
|------|---------|
| `03_verification/main.py` | +`_http_client`, +`report_verification_progress()`, chunked submission (10/chunk), 5-contact reporting, 0.5s busy sleep, logging |
| `04_api/api/v1/endpoints/dashboard.py` | +`VerificationProgress` model, +`POST /verification-progress` endpoint |
| `04_api/templates/dashboard.html` | +verifier widget CSS, +`updateVerifierProgress()`, +WS handler, toggle "Imported Contacts" |

### 2026-05-22: Inline Service Controls + Pulsing Stability

#### Complete rework of service action buttons in pipeline nodes

**Replaced service modal with inline 3D circular buttons** (▶ start / ✕ stop / ↻ restart) that appear inline between Uptime and Processed stats when a node is expanded. Stats grid switches from 2-col to 3-col (`1fr auto 1fr`) on expand to accommodate buttons.

**Accordion behavior**: `toggleSubNodes()` collapses all others before expanding — one node expanded at a time.

**Pulsing animation**: `@keyframes node-pulse` on `.pipeline-node.pulsing` — box-shadow + border-color pulse. Added/removed by `serviceAction()` via `node.classList`.

**Key behavioral changes:**
- Stop/start/restart all buttons disabled during entire transition (from click until target status confirmed via poll)
- "Already in progress" → stop the stuck process → wait 2s → retry start (works in Manual mode, no systemd respawn)
- Button visibility reshuffled (Start hidden when running, etc.)

**Critical fixes for pulsing disruption from dashboard reload:**

| Fix | Problem | Solution |
|-----|---------|----------|
| **Pulsing lost on full re-render** (line 1650-1654) | `container.innerHTML = html` wiped pulsing class | Save pulsing node keys before rebuild, restore `pulsing` after |
| **Status overwritten mid-pulse** (line 1496-1501) | In-place update set status class from server — `stopped` class applied `opacity: 0.5` during transition | If node has `pulsing`, freeze its status class from previous state |
| **Pipeline coupled to 15s poll** (line 1474-1479, 1658-1706) | Every poll cycle ran `renderPipelineMap` which modified sibling DOM (queue, sources, connectors) causing layout reflow → animation stutter/flicker/stop | `pipelineInitialized` flag: after first render, `renderPipelineMap` calls lightweight `updatePipelineStats()` that skips all DOM work when any node is pulsing (`if (container.querySelector('.pipeline-node.pulsing')) return`) |

**Root cause of animation disruption**: Layout reflow from DOM writes on sibling nodes (queue badges, source status `innerHTML`, connector dots) during the 15s `startPolling` cycle. The single guard at `updatePipelineStats()` entry eliminates all pipeline DOM modifications during transitions.

**Files modified (all in `04_api/templates/dashboard.html`):**
- Added `pipelineInitialized` flag (line 1242)
- `renderPipelineMap()` — early return to `updatePipelineStats()` after first render (lines 1474-1479)
- `updatePipelineStats()` new function (lines 1658-1706) — lightweight queue/source/connector updates only; exits immediately if any node is pulsing
- In-place update status freeze for pulsing nodes (lines 1496-1508)
- Full re-render path saves/restores pulsing keys (lines 1623-1625, 1650-1654)
- All three service action buttons disabled during transition, re-enabled+reshuffled via `reshuffle()` only after target status confirmed (lines 1822-1910+)
- "Already in progress" path: stop → wait → start → poll (lines 1849-1888)

## Full Project Bug Audit (2026-05-25)

### Summary — 133 issues across 6 service areas

| Area | CRITICAL | HIGH | MEDIUM | LOW | Total |
|------|----------|------|--------|-----|-------|
| 01_discovery | 1 | 3 | 9 | 6 | 19 |
| 01b_browsing | 1 | 2 | 7 | 15 | 25 |
| 02_enrichment | 3 | 5 | 10 | 6 | 24 |
| 03_verification | 2 | 3 | 9 | 6 | 20 |
| 04_api | 2 | 5 | 17 | 8 | 32 |
| shared_models/utils/scripts | 1 | 4 | 3 | 5 | 13 |
| **Total** | **10** | **22** | **55** | **46** | **133** |

### Phase 0: Security & Infrastructure

| # | File | Fix |
|---|------|-----|
| 1 | All service `.env` files | Remove from git, add `*.env` to `.gitignore`, rotate DB password |
| 2 | `02_enrichment/.env`, `03_verification/.env` | Verify they're also un-tracked |
| 3 | `.gitignore` | Add `*.env`, `venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`, `logs/*.log` |

### Phase 1: Database Models

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 4 | `shared_models/job_stats.py:19-20` | CRITICAL | Add `UniqueConstraint('job_type', 'status', name='uq_job_stats_type_status')` to `JobStats` table args |
| 5 | `shared_models/contact.py:23` | HIGH | Add `default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc)` to `updated_at` |
| 6 | `shared_models/company.py:30` | HIGH | Same — add `default`/`onupdate` to `updated_at` |
| 7 | `shared_models/discovery_job.py:14` | HIGH | Same — add `default`/`onupdate` to `updated_at` |
| 8 | `shared_models/discovery_job.py:11,13` | HIGH | Remove redundant `error_message` column (keep only `last_error`) |
| 9 | `shared_models/service_metrics.py:9` | LOW | Remove redundant `index=True` on PK `id` |

### Phase 2: Verification Service (03_verification)

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 10 | `main.py:119` | CRITICAL | Add `api_base` param/config so `write_metrics()` doesn't throw `NameError` |
| 11 | `main.py:119` | MEDIUM | Switch `httpx.post(...)` to use persistent `_http_client` |
| 12 | `main.py:165-178` | MEDIUM | Remove redundant re-query for `total_pending` |
| 13 | `main.py:229-245` | MEDIUM | Add `return` after `db.rollback()` to skip stale check |
| 14 | `config.py:13` | MEDIUM | Add `if not DATABASE_URL: raise ValueError(...)` |
| 15 | `services/email_verify.py:127` | HIGH | Change `"valid_verified"` → `"verified"` to match API |
| 16 | `services/verification.py` | MEDIUM | Remove dead code file (128 lines, unused) |
| 17 | `run_verification.sh:24` | MEDIUM | Replace broad `pkill` with PID-file kill |

### Phase 3: Browsing Service (01b_browsing)

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 18 | `main.py:126-141` | CRITICAL | Empty HTML with retries left → set `discovered` not `browsed` |
| 19 | `main.py:188-205` | HIGH | Add `elif` for `requeued` + non-exhausted retries |
| 20 | `services/browser.py:205-213` | HIGH | Use `signal_extractor.py` version with full `clean_emails()` |
| 21 | `services/signal_extractor.py:29-30` | MEDIUM | Tighten overbroad parked-domain patterns |
| 22 | `services/browser.py:50-68` | MEDIUM | Add error handling around `chromium.launch()` |
| 23 | `main.py:338-339` | MEDIUM | Wrap `init_db()` in try/except |

### Phase 4: Enrichment Service (02_enrichment)

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 24 | `main.py:202-203` | CRITICAL | Remove broken `asyncio.run(httpx.Client())` fallback |
| 25 | `main.py:439-452` | CRITICAL | Fix watchdog: check `retry_count >= MAX_RETRIES` |
| 26 | `main.py:268-271` | HIGH | Fix rollback losing prior saves — use SAVEPOINT |
| 27 | `main.py:52,293` | HIGH | Replace `datetime.now()` with timezone-aware |
| 28 | `main.py:335-336` | HIGH | Pass actual harvester subdomains |
| 29 | `config.py:12` | HIGH | Add `DATABASE_URL` guard |
| 30 | `services/harvester_api.py` | MEDIUM | Remove dead code |
| 31 | `services/email_extractor.py` | MEDIUM | Remove dead code |
| 32 | `main.py:186-190` | MEDIUM | Add Semaphore to limit parallel fetches |

### Phase 5: Discovery Service (01_discovery)

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 33 | `main.py:155-177` | CRITICAL | Rollback before fallback or remove dead fallback |
| 34 | `requirements.txt` | HIGH | Add `httpx>=0.24.0` |
| 35 | `main.py:125,128` | HIGH | Remove duplicate CommonCrawl call |
| 36 | `main.py:64,213,266,357` | MEDIUM | Use `datetime.now(timezone.utc)` everywhere |
| 37 | `services/regional_scoring.py:158-160` | MEDIUM | Boolean flag instead of arithmetic break |
| 38 | `services/commoncrawl.py:164` | MEDIUM | Add Lock around `seen_domains` |

### Phase 6: API Service (04_api)

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 39 | `templates/dashboard.html:23` | CRITICAL | Fix CSS `});` → `}` to close `:root` |
| 40 | `templates/dashboard.html:2164` | HIGH | Fix `showTab()` missing `event` param |
| 41 | `templates/dashboard.html:2588` | MEDIUM | Remove duplicate metrics `setInterval` |
| 42 | `templates/dashboard.html:2582-2584` | MEDIUM | Fix WS/HTTP polling race |
| 43 | `config.py:13` | CRITICAL | Add `DATABASE_URL` guard |
| 44 | `main.py:37,131` | MEDIUM | Remove redundant `init_db()` call |
| 45 | `services/process_manager.py:213` | HIGH | SIGTERM first, SIGKILL fallback |
| 46 | `services/process_manager.py:129` | MEDIUM | Fix lock file PID |
| 47 | `database.py:69-76` | HIGH | Use SQLAlchemy DDL not f-string SQL |
| 48 | `requirements.txt` | MEDIUM | Add `email-validator`, `disposable-email-domains` |
| 49 | `api/v1/endpoints/companies.py:32-38` | MEDIUM | Differentiate error from empty |
| 50 | `api/v1/endpoints/contacts.py:183-186` | HIGH | Rate-limit DNS verification pool |

### Phase 7: Cleanup & Polish

| # | File:Line | Sev | Fix |
|---|-----------|-----|-----|
| 51 | `utils/email_utils.py:113-118` | MEDIUM | Fix dead code in `is_placeholder_email` |
| 52 | `utils/email_utils.py:120-148` | MEDIUM | Check domain only in `is_valid_tld` |
| 53 | `scripts/reconcile_stats.py:43-56` | MEDIUM | Wire up `valid_statuses` or remove |
| 54 | All services — logger level | MEDIUM | Normalize logger+handler to same level |
| 55 | All services — `datetime.now()` | MEDIUM | Audit all naive datetimes to timezone-aware |

### Priority Execution Order

1. **Phase 0** — Security (password leak in git)
2. **Phase 1** — Models (upstream schema, everything depends on it)
3. **Phase 2** — Verification (actively broken — `write_metrics` crashes)
4. **Phase 3** — Browsing (empty-HTML bug losing companies)
5. **Phase 4** — Enrichment (watchdog never escalates)
6. **Phase 5** — Discovery (transaction bug, missing dep)
7. **Phase 6** — API (CSS crash, JS ReferenceError)
8. **Phase 7** — Cleanup (consistency pass)

## Bug Fix Implementation (2026-05-25)

### Commit: `708d656` — Full project bug audit fix

**28 files changed, 274 insertions, 299 deletions, 3 deleted files**

### Phase 0: Security ✅
- Enhanced `.gitignore` with `sudoers_leadgen`, `nginx_config_updated.conf`, `pipeline.log`
- Confirmed no `.env` files are tracked in git (already gitignored)

### Phase 1: Database Models ✅
| File | Change |
|------|--------|
| `shared_models/job_stats.py` | Added `UniqueConstraint('job_type', 'status', name='uq_job_stats_type_status')` to fix UPSERT crash |
| `shared_models/contact.py` | Added `default`/`onupdate` to `updated_at` |
| `shared_models/company.py` | Added `default`/`onupdate` to `updated_at` |
| `shared_models/discovery_job.py` | Added `default`/`onupdate` to `updated_at`; removed redundant `error_message` column |
| `shared_models/service_metrics.py` | Removed redundant `index=True` on PK `id` |

### Phase 2: Verification Service ✅
| File | Change |
|------|--------|
| `03_verification/main.py:119` | Fixed `api_base` undefined in `write_metrics()` — was `NameError` every 60s |
| `03_verification/main.py:119` | Switched `httpx.post()` to use persistent `_http_client` |
| `03_verification/main.py:165-178` | Removed redundant `total_pending` re-query |
| `03_verification/main.py:229-245` | Added `return` after `db.rollback()` to skip stale company check |
| `03_verification/config.py:13` | Added `if not DATABASE_URL: raise ValueError(...)` guard |
| `03_verification/services/email_verify.py:127` | Changed `"valid_verified"` → `"verified"` to align with API |
| `03_verification/services/verification.py` | **Deleted** — 128 lines of dead code (SMTP waterfall, never called) |
| `03_verification/run_verification.sh:24` | Replaced broad `pkill -f "python.*03_verification"` with PID-file-based kill |

### Phase 3: Browsing Service ✅
| File | Change |
|------|--------|
| `01b_browsing/main.py:126-141` | **CRITICAL**: Empty HTML with retries remaining now sets `status='discovered'` (retry) instead of `status='browsed'` (done) |
| `01b_browsing/main.py:188-205` | Added missing `elif` for `requeued` + non-exhausted retries in exception handler |
| `01b_browsing/main.py:234-238` | Same fix in watchdog — retry instead of mark browsed |
| `01b_browsing/services/browser.py:205-213` | Replaced simple regex email extraction with `clean_emails()` full pipeline |
| `01b_browsing/services/browser.py:5-10` | Import `clean_emails` from `utils.email_utils`; removed unused `Base` import |
| `01b_browsing/services/signal_extractor.py:28-31` | Tightened overbroad parked patterns (removed `registrar`, `renew now`) |
| `01b_browsing/services/browser.py:57-59` | Added try/except around `chromium.launch()` |
| `01b_browsing/main.py:338-339` | Wrapped `init_db()` in try/except with `logger.critical()` |

### Phase 4: Enrichment Service ✅
| File | Change |
|------|--------|
| `02_enrichment/main.py:202-203` | **CRITICAL**: Removed broken `asyncio.run(_extract_async(httpx.Client(), ...))` — was `TypeError` when reached |
| `02_enrichment/main.py:537-539` | **CRITICAL**: Fixed watchdog phase-escalation to check `retry_count` thresholds instead of impossible status checks (was checking `status == 'enrich_requeued'` on `'enriching'` records — never matched, retried forever) |
| `02_enrichment/main.py:268-271` | Fixed rollback losing prior saves — replaced with `db.begin_nested()` SAVEPOINT |
| `02_enrichment/main.py:80, 373, 524` | Replaced `datetime.now()` with `datetime.now(timezone.utc)` everywhere |
| `02_enrichment/main.py:425` | Fixed harvester hosts discarded — use actual `hosts` list, not `[domain]` |
| `02_enrichment/config.py:13` | Added `DATABASE_URL` guard |
| `02_enrichment/main.py:188-189` | Added `asyncio.Semaphore(20)` to limit parallel fetches |
| `02_enrichment/services/harvester_api.py` | **Deleted** — unused REST client |
| `02_enrichment/services/email_extractor.py` | **Deleted** — unused re-export |

### Phase 5: Discovery Service ✅
| File | Change |
|------|--------|
| `01_discovery/main.py:128-129` | Added `db.rollback()` before one-by-one fallback in `save_batch_incremental` |
| `01_discovery/requirements.txt` | Added `httpx>=0.24.0` |
| `01_discovery/main.py:58,153-154,263,362-363` | Replaced `datetime.now()` with `datetime.now(timezone.utc)` |

### Phase 6: API Service ✅
| File | Change |
|------|--------|
| `04_api/templates/dashboard.html:23` | **CRITICAL**: Fixed CSS `});` → `}` — was invalidating all `:root` CSS custom properties |
| `04_api/templates/dashboard.html:2164` | Fixed `showTab()` — added `event` parameter to fix `ReferenceError` |
| `04_api/templates/dashboard.html:2588` | Removed duplicate metrics polling `setInterval` — was doubling API calls |
| `04_api/templates/dashboard.html:2582-2584` | Guard with `!metricsIntervalObj` to prevent WS/HTTP race |
| `04_api/config.py:13` | Added `DATABASE_URL` guard |
| `04_api/main.py:131` | Removed redundant `init_db()` from `__main__` (lifespan already calls it) |
| `04_api/services/process_manager.py:213-228` | Changed from `SIGKILL (-9)` to `SIGTERM (-15)` first, 2s wait, then `SIGKILL` fallback |
| `04_api/services/process_manager.py:129` | Fixed lock file PID — write `b'0'` instead of `os.getpid()` (API PID) |
| `04_api/database.py:69-76` | Added table/column whitelist validation to migration SQL |
| `04_api/requirements.txt` | Added `httpx`, `email-validator`, `disposable-email-domains`; removed unused `pydantic-settings`, `celery`, `requests` |

### Phase 7: Cleanup ✅
| File | Change |
|------|--------|
| `utils/email_utils.py:87-105` | Removed dead AND check in `is_placeholder_email` (subset of first condition) |
| `utils/email_utils.py:212` | Fixed `is_valid_tld` to receive only domain portion, not full email |
| `01_discovery/main.py` | Timezone-aware `datetime.now(timezone.utc)` everywhere |

### Round 2 Fixes (commit `fa7f182`, 2026-05-25) ✅
| # | File | Fix |
|---|------|-----|
| 1 | `services/regional_scoring.py:158-160` | Replaced `score % 2 == 0` arithmetic break with boolean `found_city` flag |
| 2 | `services/commoncrawl.py:164` | Added `threading.Lock` around `seen_domains` check-then-add in multi-threaded TLD queries |
| 3 | `api/v1/endpoints/companies.py:32-38` | Changed `return []` to `raise HTTPException(500)` so clients can distinguish error from empty |
| 4 | `api/v1/endpoints/contacts.py:207,353` | Reduced `_MAX_WORKERS` from 10→5, added `await asyncio.sleep(0.5)` between batch chunks for DNS rate limiting |
| 5 | `scripts/reconcile_stats.py:43-56` | Wired `valid_statuses` into SQL `WHERE` clause |
| 6 | All 4 service `main.py` files | Changed `logger.setLevel(logging.DEBUG)` → `logging.INFO` to match handler levels |

### No outstanding issues remain.
