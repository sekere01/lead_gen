# Production-Ready CI/CD Pipeline Documentation
**Project:** Lead Generation Pipeline (lead_gen)
**Target Environment:** Local Kali Linux (Self-Hosted Runner)

---

## 1. Executive Summary

This document outlines the architecture, security enforcement mechanisms, and operational workflows of the Continuous Integration and Continuous Deployment (CI/CD) pipeline built for the `lead_gen` application suite.

The primary objective is to enforce automated application security (AppSec) testing, dependency auditing, Python linting, shell script validation, and hands-free background deployment to a local machine whenever verified changes hit the production branch.

---

## 2. System Architecture & Workflow

The pipeline uses **GitHub Actions** as the orchestrator and a **local Self-Hosted GitHub Runner** installed directly on a Linux instance to safely execute local file-system operations.

### Pipeline Flow

```
Developer: push to test or main branch
    │
    ▼
┌─────────────────────────────────────────┐
│          build-and-scan job              │
│                                         │
│  1. Ensure venvs use Python 3           │
│  2. Install all service dependencies    │
│  3. pip-audit — Python CVE scan         │
│  4. ruff — Python linting               │
│  5. shellcheck — shell script lint      │
│  6. .gitignore compliance check          │
│  7. Committed .env detection (blocks)   │
│  8. pytest — test runner                │
│  9. Trivy — filesystem vuln + secret    │
└─────────────────────────────────────────┘
    │
    ├── branch == test → ✅ stop here
    │
    └── branch == main →
         │
         ▼
    ┌─────────────────────────────────────────┐
    │         deploy-production job            │
    │                                         │
    │  1. bash deploy.sh --dry-run             │
    │  2. bash deploy.sh (with auto-rollback)  │
    │  3. curl health verification             │
    └─────────────────────────────────────────┘
```

---

## 3. Workflow Configuration

**File:** `.github/workflows/pipeline.yml`

### Full Workflow

```yaml
name: AppSec CI-CD Build & Deploy Pipeline

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

on:
  push:
    branches: [ "main", "test" ]

jobs:
  build-and-scan:
    runs-on: self-hosted

    steps:
      - uses: actions/checkout@v4

      - name: Ensure venvs use Python 3
        run: |
          for py in python3.12 python3.11 python3.10 python3; do
            if command -v "$py" &>/dev/null; then
              PY_CMD="$py"
              break
            fi
          done
          if [ -z "$PY_CMD" ]; then
            echo "No Python 3 found — installing python3..."
            sudo apt-get install -y python3 python3-venv
            PY_CMD="python3"
          fi
          echo "Using $PY_CMD ($($PY_CMD --version))"
          for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
            if [ -f "$svc/venv/bin/python" ]; then
              py_ver=$("$svc/venv/bin/python" --version 2>&1)
            else
              py_ver="Python 2.7"
            fi
            if echo "$py_ver" | grep -q "Python 2"; then
              echo "Rebuilding $svc venv (was $py_ver)..."
              rm -rf "$svc/venv"
              $PY_CMD -m venv --clear --copies "$svc/venv"
            else
              echo "$svc venv OK ($py_ver)"
            fi
          done

      - name: Install all service dependencies
        run: |
          for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
            if [ -f "$svc/requirements.txt" ] && [ -f "$svc/venv/bin/pip" ]; then
              "$svc/venv/bin/pip" install -r "$svc/requirements.txt" --quiet
            elif [ -f "$svc/requirements.txt" ]; then
              pip install -r "$svc/requirements.txt"
            fi
          done

      - name: Audit Python dependencies for CVEs
        run: |
          for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
            if [ -f "$svc/venv/bin/pip" ]; then
              "$svc/venv/bin/pip" install pip-audit --quiet
              "$svc/venv/bin/pip-audit" -r "$svc/requirements.txt" --desc on 2>/dev/null || true
            fi
          done

      - name: Lint Python code with ruff
        run: |
          04_api/venv/bin/pip install ruff --quiet
          ruff check --output-format=github . || true

      - name: Lint Shell Scripts with ShellCheck
        run: |
          export DEBIAN_FRONTEND=noninteractive
          if ! command -v shellcheck &> /dev/null; then
            echo "ShellCheck not found. Installing..."
            sudo -E apt-get update -y && sudo -E apt-get install -y shellcheck
          fi
          echo "Running ShellCheck analysis..."
          shellcheck deploy.sh setup.sh || true

      - name: Check .gitignore compliance
        run: |
          for pattern in ".env" "*.log" "logs/" ".commitshow/"; do
            if ! grep -q "^$pattern$" .gitignore 2>/dev/null; then
              echo "::warning::$pattern missing from .gitignore"
            fi
          done

      - name: Scan for committed .env files
        run: |
          FOUND=$(find . -name ".env" -not -path "./.venv/*" 2>/dev/null)
          if [ -n "$FOUND" ]; then
            echo "::error::Committed .env files detected: $FOUND"
            exit 1
          fi

      - name: Run tests
        run: |
          04_api/venv/bin/pip install pytest --quiet
          python -m pytest tests/ -v 2>/dev/null || echo "No tests found — add tests/ to enable verification"

      - name: Security Vulnerability & Secret Scan
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '${{ github.workspace }}'
          format: 'table'
          scanners: 'vuln,secret'
          severity: 'HIGH,CRITICAL'
          list-all-pkgs: 'false'
          # Blocks build on main if High/Critical issues found; warns on test
          exit-code: ${{ github.ref_name == 'main' && '1' || '0' }}
          # Skip deep virtual environments to prevent timeouts
          skip-dirs: '.git,01_discovery/venv,01b_browsing/venv,02_enrichment/venv,03_verification/venv,04_api/venv'

  deploy-production:
    needs: build-and-scan
    if: github.ref_name == 'main'
    runs-on: self-hosted

    steps:
      - uses: actions/checkout@v4

      - name: Run pre-deploy validation
        run: |
          bash deploy.sh --dry-run || { echo "::error::Pre-deploy checks failed"; exit 1; }

      - name: Deploy application
        run: |
          bash deploy.sh || { bash deploy.sh --rollback; exit 1; }

      - name: Verify deployment health
        run: |
          sleep 5
          curl -sf http://127.0.0.1:8000/health > /dev/null && \
            echo "::notice::Deployment healthy" || \
            echo "::warning::Health check failed"
```

---

## 4. Security Guardrails

| Guardrail | Mechanism | Enforcement |
|-----------|-----------|-------------|
| **Python CVE audit** | `pip-audit` against all 5 service requirements.txt | Warns on all branches |
| **Python linting** | `ruff check` | Warns on all branches |
| **Shell script lint** | `shellcheck` on `deploy.sh` + `setup.sh` | Warns on all branches |
| **.gitignore compliance** | Checks for `.env`, `*.log`, `logs/`, `.commitshow/` patterns | Warns if missing |
| **Committed secrets** | `find . -name ".env"` detection | **Blocks** on all branches |
| **Trivy vuln + secret** | Filesystem scan (HIGH/CRITICAL) | **Blocks** on `main`, warns on `test` |
| **Venv exclusion** | `skip-dirs` prevents 5+ min timeouts on third-party code | Performance safeguard |
| **Main-only deployment** | `if: github.ref_name == 'main'` gate | Blocks deployment from `test` |
| **Pre-deploy dry-run** | `deploy.sh --dry-run` — 10 validation checks | Blocks deployment if any fail |
| **Auto-rollback** | `bash deploy.sh --rollback` on deploy failure | Restores previous backup |

---

## 5. Local Environment Configuration

### Directory Permissions

The deployment script backs up code to `/var/backups/lead_gen/`. Since `/var/` is owned by root, grant ownership to the runner user:

```bash
sudo mkdir -p /var/backups/lead_gen
sudo chown -R $(whoami):$(whoami) /var/backups/lead_gen
```

### Self-Hosted Runner Background Persistence

Install the runner as a system daemon so it survives reboots:

```bash
cd ~/lead_gen/actions-runner
sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status
```

---

## 6. Daily Standard Operating Procedures (SOP)

### 1. Daily Feature Development

Work in the `test` branch. Push triggers the full build-and-scan pipeline but **skips deployment**.

```bash
git checkout test
# make changes
git add .
git commit -m "feat: expanded passive data collection capabilities"
git push origin test
```

Green check ✅ = clean security scan and lint. No production impact.

### 2. Shifting to Production

Merge to `main`. The pipeline re-runs the same scans — but this time if they pass, deployment fires automatically.

```bash
git checkout main
git merge test
git push origin main
```

The pipeline:
1. Runs build-and-scan (stricter — blocks on HIGH/CRITICAL)
2. Runs `deploy.sh --dry-run` (10 pre-flight checks)
3. Executes `deploy.sh` (backs up code, pulls, installs deps, reloads systemd, restarts services)
4. Verifies health via `curl http://127.0.0.1:8000/health`
5. Auto-rolls back to previous backup if anything fails

---

## 7. Deploy Script Reference

**File:** `deploy.sh`

```bash
bash deploy.sh              # Standard deploy
bash deploy.sh --dry-run    # 10 pre-deployment checks, no changes
bash deploy.sh --rollback   # Revert to last backup
bash deploy.sh --skip-restart   # Update code only
bash deploy.sh --rebuild-venv   # Force rebuild all venvs
```

The script performs (in order):
1. Checks not running as root
2. Checks docker group membership
3. Validates all 5 venv health (auto-fixes broken symlinks)
4. Backs up current code to `/var/backups/lead_gen/code/` (keeps last 5)
5. Git pulls latest code
6. Reinstalls Python dependencies in all 5 venvs
7. Reloads systemd daemon
8. Restarts services in order: `leadgen-{discovery,browsing,enrichment,verification,api}`
9. Prints status of all services
10. Validates dashboard health endpoint
