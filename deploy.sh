#!/bin/bash
#
# Lead Generation Pipeline - Deploy Script
# Run as: bash deploy.sh [--dry-run] [--skip-restart] [--rollback] [--rebuild-venv] [--help]
#

set -e

# =============================================================================
# Flags
# =============================================================================
DRY_RUN=false
SKIP_RESTART=false
ROLLBACK=false
REBUILD_VENV=false

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --skip-restart)
            SKIP_RESTART=true
            shift
            ;;
        --rollback)
            ROLLBACK=true
            shift
            ;;
        --rebuild-venv)
            REBUILD_VENV=true
            shift
            ;;
        --help)
            echo "Usage: bash deploy.sh [--dry-run] [--skip-restart] [--rollback] [--rebuild-venv]"
            echo ""
            echo "Options:"
            echo "  --dry-run       Pre-deployment validation (10 checks, no changes)"
            echo "  --skip-restart  Update code only, don't restart services"
            echo "  --rollback      Revert to previous deployment backup"
            echo "  --rebuild-venv  Force rebuild all virtual environments"
            echo "  --help          Show this help message"
            exit 0
            ;;
    esac
done

# =============================================================================
# Detect the deploying user (no hardcoded ubuntu fallback)
# =============================================================================
DEPLOY_USER=$(whoami)
if [ "$DEPLOY_USER" = "root" ] && [ -n "$SUDO_USER" ]; then
    DEPLOY_USER=$SUDO_USER
fi

PROJECT_DIR="/home/$DEPLOY_USER/lead_gen"
BACKUP_DIR="/var/backups/lead_gen"
SERVICES="01_discovery 01b_browsing 02_enrichment 03_verification 04_api"

echo "=== Lead Generation Pipeline Deploy ==="
echo "Deploy user: $DEPLOY_USER"
echo "Project dir: $PROJECT_DIR"
echo ""

# Check NOT running as root
if [ "$(id -u)" -eq 0 ]; then
    echo "ERROR: Do NOT run as root. Run as $DEPLOY_USER: bash deploy.sh"
    exit 1
fi

# Check docker group membership
if ! groups | grep -q docker; then
    echo "ERROR: Not in docker group. Reboot first: sudo reboot"
    exit 1
fi

# =============================================================================
# Helper functions
# =============================================================================
check_venv_health() {
    local broken=0
    for svc in $SERVICES; do
        local venv_python="$PROJECT_DIR/$svc/venv/bin/python"
        if [ -L "$venv_python" ]; then
            echo "    [FAIL] $svc venv has symlinked Python (broken)"
            broken=$((broken + 1))
        elif [ ! -f "$venv_python" ]; then
            echo "    [FAIL] $svc venv Python not found"
            broken=$((broken + 1))
        else
            echo "    [OK] $svc venv is healthy"
        fi
    done
    return $broken
}

rebuild_venv() {
    local svc="$1"
    echo "    Rebuilding $svc venv..."
    rm -rf "$PROJECT_DIR/$svc/venv"
    python3 -m venv --clear --copies "$PROJECT_DIR/$svc/venv"
    "$PROJECT_DIR/$svc/venv/bin/pip" install --upgrade pip --quiet
    "$PROJECT_DIR/$svc/venv/bin/pip" install -r "$PROJECT_DIR/$svc/requirements.txt" --quiet
    echo "    $svc venv rebuilt."
}

backup_code() {
    mkdir -p "$BACKUP_DIR/code"
    local backup_name="code_backup_$(date +%Y%m%d_%H%M%S)"
    local backup_path="$BACKUP_DIR/code/$backup_name"
    
    echo "    Backing up code to $backup_path..."
    cp -r "$PROJECT_DIR" "$backup_path" 2>/dev/null || true
    
    # Keep only last 5 backups
    ls -dt "$BACKUP_DIR/code/"code_backup_* 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true
}

rollback_code() {
    local latest_backup=$(ls -dt "$BACKUP_DIR/code/"code_backup_* 2>/dev/null | head -1)
    if [ -z "$latest_backup" ]; then
        echo "ERROR: No backup found for rollback"
        exit 1
    fi
    
    echo "Rolling back to: $latest_backup"
    cp -r "$latest_backup/"* "$PROJECT_DIR/" 2>/dev/null || true
    echo "Rollback complete."
}

check_dashboard() {
    echo "    Checking dashboard endpoint..."
    local response=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null || echo "000")
    if [ "$response" = "200" ]; then
        echo "    [OK] Dashboard health endpoint responding"
        return 0
    else
        echo "    [FAIL] Dashboard health endpoint not responding (HTTP $response)"
        return 1
    fi
}

# =============================================================================
# Rollback mode
# =============================================================================
if [ "$ROLLBACK" = true ]; then
    echo "--- ROLLBACK MODE ---"
    rollback_code
    echo "Restarting services with rolled-back code..."
    for svc in discovery browsing enrichment verification api; do
        echo "    Restarting leadgen-$svc..."
        sudo systemctl restart leadgen-$svc 2>/dev/null || echo "    WARNING: Failed to restart leadgen-$svc"
        sleep 2
    done
    echo "Rollback complete."
    exit 0
fi

# =============================================================================
# Dry-run mode: 10 pre-deployment checks
# =============================================================================
if [ "$DRY_RUN" = true ]; then
    echo "--- DRY RUN: Pre-deployment validation ---"
    echo ""
    
    local_pass=0
    local_fail=0
    
    # Check 1: Project directory exists
    if [ -d "$PROJECT_DIR" ]; then echo "[1/10] [OK] Project directory exists"; local_pass=$((local_pass+1)); else echo "[1/10] [FAIL] Project directory missing"; local_fail=$((local_fail+1)); fi
    
    # Check 2: Git repo exists
    if [ -d "$PROJECT_DIR/.git" ]; then echo "[2/10] [OK] Git repo exists"; local_pass=$((local_pass+1)); else echo "[2/10] [FAIL] Git repo missing"; local_fail=$((local_fail+1)); fi
    
    # Check 3: All service directories exist
    all_svc_ok=true
    for svc in $SERVICES; do [ -d "$PROJECT_DIR/$svc" ] || all_svc_ok=false; done
    if $all_svc_ok; then echo "[3/10] [OK] All service directories exist"; local_pass=$((local_pass+1)); else echo "[3/10] [FAIL] Missing service directories"; local_fail=$((local_fail+1)); fi
    
    # Check 4: Venv health
    if check_venv_health; then echo "[4/10] [OK] All venvs healthy"; local_pass=$((local_pass+1)); else echo "[4/10] [FAIL] Broken venvs detected"; local_fail=$((local_fail+1)); fi
    
    # Check 5: .env files exist
    env_ok=true
    for svc in $SERVICES; do [ -f "$PROJECT_DIR/$svc/.env" ] || env_ok=false; done
    if $env_ok; then echo "[5/10] [OK] All .env files exist"; local_pass=$((local_pass+1)); else echo "[5/10] [FAIL] Missing .env files"; local_fail=$((local_fail+1)); fi
    
    # Check 6: PostgreSQL running
    if systemctl is-active postgresql &>/dev/null; then echo "[6/10] [OK] PostgreSQL running"; local_pass=$((local_pass+1)); else echo "[6/10] [FAIL] PostgreSQL not running"; local_fail=$((local_fail+1)); fi
    
    # Check 7: Redis running
    if systemctl is-active redis-server &>/dev/null || systemctl is-active redis &>/dev/null; then echo "[7/10] [OK] Redis running"; local_pass=$((local_pass+1)); else echo "[7/10] [FAIL] Redis not running"; local_fail=$((local_fail+1)); fi
    
    # Check 8: Docker running
    if systemctl is-active docker &>/dev/null; then echo "[8/10] [OK] Docker running"; local_pass=$((local_pass+1)); else echo "[8/10] [FAIL] Docker not running"; local_fail=$((local_fail+1)); fi
    
    # Check 9: Nginx running
    if systemctl is-active nginx &>/dev/null; then echo "[9/10] [OK] Nginx running"; local_pass=$((local_pass+1)); else echo "[9/10] [FAIL] Nginx not running"; local_fail=$((local_fail+1)); fi
    
    # Check 10: Dashboard endpoint
    if check_dashboard; then echo "[10/10] [OK] Dashboard responding"; local_pass=$((local_pass+1)); else echo "[10/10] [FAIL] Dashboard not responding"; local_fail=$((local_fail+1)); fi
    
    echo ""
    echo "Results: $local_pass passed, $local_fail failed"
    
    if [ $local_fail -gt 0 ]; then
        echo ""
        echo "WARNING: Some checks failed. Run without --dry-run to auto-fix where possible."
        exit 1
    fi
    
    echo "All checks passed. Ready to deploy."
    exit 0
fi

# =============================================================================
# Rebuild venvs if requested
# =============================================================================
if [ "$REBUILD_VENV" = true ]; then
    echo "--- REBUILDING ALL VIRTUAL ENVIRONMENTS ---"
    for svc in $SERVICES; do
        rebuild_venv "$svc"
    done
    echo "All venvs rebuilt. Run deploy again to restart services."
    exit 0
fi

# =============================================================================
# Auto-fix broken venvs before deploy
# =============================================================================
echo "[0/6] Checking venv health..."
if ! check_venv_health; then
    echo "    Auto-fixing broken venvs..."
    for svc in $SERVICES; do
        local venv_python="$PROJECT_DIR/$svc/venv/bin/python"
        if [ -L "$venv_python" ] || [ ! -f "$venv_python" ]; then
            rebuild_venv "$svc"
        fi
    done
fi
echo "    Venv health check passed."

# =============================================================================
# 1. Code backup + Git pull
# =============================================================================
echo "[1/6] Backing up and updating code..."

backup_code

cd "$PROJECT_DIR"
git pull origin main 2>/dev/null || git pull 2>/dev/null || echo "    Git pull skipped (not on main branch)"

echo "    Code updated."

# =============================================================================
# 2. Install Python dependencies
# =============================================================================
echo "[2/6] Installing Python dependencies..."

for svc in $SERVICES; do
    echo "    Installing $svc..."
    "$PROJECT_DIR/$svc/venv/bin/pip" install -r "$PROJECT_DIR/$svc/requirements.txt" --quiet
done

echo "    Python dependencies installed."

# =============================================================================
# 3. Reload systemd
# =============================================================================
echo "[3/6] Reloading systemd..."

sudo systemctl daemon-reload

echo "    Systemd reloaded."

# =============================================================================
# 4. Restart services (with delays)
# =============================================================================
if [ "$SKIP_RESTART" = true ]; then
    echo "[4/6] Skipping service restart (--skip-restart)"
else
    echo "[4/6] Restarting services..."

    for svc in discovery browsing enrichment verification; do
        echo "    Restarting leadgen-$svc..."
        sudo systemctl restart leadgen-$svc 2>/dev/null || echo "    WARNING: Failed to restart leadgen-$svc"
        sleep 2
    done

    echo "    Restarting leadgen-api..."
    sudo systemctl restart leadgen-api 2>/dev/null || echo "    WARNING: Failed to restart leadgen-api"
    sleep 2

    echo "    Services restarted."
fi

# =============================================================================
# 5. Status check
# =============================================================================
echo "[5/6] Service status..."
echo ""

for svc in discovery browsing enrichment verification api; do
    echo "--- leadgen-$svc ---"
    sudo systemctl status leadgen-$svc --no-pager 2>/dev/null || echo "    Service not running"
    echo ""
done

# =============================================================================
# 6. Dashboard validation
# =============================================================================
echo "[6/6] Validating dashboard..."

if check_dashboard; then
    echo "    Dashboard is healthy."
else
    echo "    WARNING: Dashboard not responding yet. Services may still be starting."
fi

echo ""
echo "========================================"
echo "DEPLOY COMPLETE"
echo "========================================"
echo ""
echo "Dashboard: http://<VPS_IP>/dashboard"
echo "API docs: http://<VPS_IP>/docs"
echo ""
echo "Service management:"
echo "  sudo systemctl status leadgen-discovery"
echo "  sudo systemctl status leadgen-browsing"
echo "  sudo systemctl status leadgen-enrichment"
echo "  sudo systemctl status leadgen-verification"
echo "  sudo systemctl status leadgen-api"
echo ""
echo "Logs:"
echo "  sudo journalctl -u leadgen-discovery -f"
echo "  sudo journalctl -u leadgen-browsing -f"
echo "  sudo journalctl -u leadgen-enrichment -f"
echo "  sudo journalctl -u leadgen-verification -f"
echo "  sudo journalctl -u leadgen-api -f"

exit 0
