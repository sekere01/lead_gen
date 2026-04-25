#!/bin/bash
#
# Lead Generation Pipeline - Deploy Script
# Run as: bash deploy.sh (after setup.sh + reboot)
#

set -e

# Detect the actual deploying user
DEPLOY_USER=${SUDO_USER:-$(whoami)}
if [ "$DEPLOY_USER" = "root" ] && [ -n "$SUDO_USER" ]; then
    DEPLOY_USER=$SUDO_USER
elif [ "$DEPLOY_USER" = "root" ]; then
    DEPLOY_USER="ubuntu"
fi

PROJECT_DIR="/home/$DEPLOY_USER/lead_gen2"

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
# 1. Git pull (update code)
# =============================================================================
echo "[1/5] Updating code..."

cd "$PROJECT_DIR"
git pull origin main 2>/dev/null || git pull 2>/dev/null || echo "    Git pull skipped (no remote or on main branch)"

echo "    Code updated."

# =============================================================================
# 2. Install Python dependencies
# =============================================================================
echo "[2/5] Installing Python dependencies..."

SERVICES="01_discovery 01b_browsing 02_enrichment 03_verification 04_api"
for svc in $SERVICES; do
    echo "    Installing $svc..."
    "$PROJECT_DIR/$svc/venv/bin/pip" install -r "$PROJECT_DIR/$svc/requirements.txt" --quiet
done

echo "    Python dependencies installed."

# =============================================================================
# 3. Reload systemd
# =============================================================================
echo "[3/5] Reloading systemd..."

sudo systemctl daemon-reload

echo "    Systemd reloaded."

# =============================================================================
# 4. Restart services
# =============================================================================
echo "[4/5] Restarting services..."

for svc in discovery browsing enrichment verification; do
    echo "    Restarting leadgen-$svc..."
    sudo systemctl restart leadgen-$svc || echo "    WARNING: Failed to restart leadgen-$svc"
done

echo "    Restarting leadgen-api..."
sudo systemctl restart leadgen-api || echo "    WARNING: Failed to restart leadgen-api"

echo "    Services restarted."

# =============================================================================
# 5. Status check
# =============================================================================
echo "[5/5] Service status..."
echo ""

for svc in discovery browsing enrichment verification api; do
    echo "--- leadgen-$svc ---"
    sudo systemctl status leadgen-$svc --no-pager 2>/dev/null || echo "    Service not running"
    echo ""
done

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