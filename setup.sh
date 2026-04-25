#!/bin/bash
#
# Lead Generation Pipeline - Setup Script
# Run as: sudo bash setup.sh
# Must be run as root/sudo
#

set -e

echo "=== Lead Generation Pipeline Setup ==="
echo ""
echo "NOTE: Run as: sudo bash setup.sh"
echo ""

read -p "Deploy username (non-root user who will run services): " DEPLOY_USER
[ -z "$DEPLOY_USER" ] && echo "ERROR: Deploy user required." && exit 1

# Create user if it doesn't exist
id "$DEPLOY_USER" &>/dev/null || useradd -m "$DEPLOY_USER"

echo "Deploy user: $DEPLOY_USER"
echo ""

# Check running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo bash setup.sh)"
    exit 1
fi

# =============================================================================
# 1. Install system packages
# =============================================================================
echo "[1/11] Installing system packages..."

apt update
apt install -y \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    docker.io \
    python3 \
    python3-venv \
    python3-pip \
    nginx \
    redis-server \
    git \
    curl \
    build-essential

echo "    System packages installed."

# =============================================================================
# 2. PostgreSQL setup
# =============================================================================
echo "[2/11] Configuring PostgreSQL..."

systemctl enable postgresql
systemctl start postgresql

# Generate random password
DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 16)

sudo -u postgres psql <<EOF
CREATE USER $DEPLOY_USER WITH PASSWORD '$DB_PASSWORD';
CREATE DATABASE lead_gen2 OWNER $DEPLOY_USER;
GRANT ALL PRIVILEGES ON DATABASE lead_gen2 TO $DEPLOY_USER;
EOF

# Grant schema privileges
sudo -u postgres psql -d lead_gen2 <<EOF
GRANT ALL ON SCHEMA public TO $DEPLOY_USER;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DEPLOY_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DEPLOY_USER;
EOF

echo "    PostgreSQL configured."

# =============================================================================
# 3. Docker setup
# =============================================================================
echo "[3/11] Configuring Docker..."

systemctl enable docker
systemctl start docker

# Add deploy user to docker group
usermod -aG docker $DEPLOY_USER

# Pull theHarvester image
docker pull ghcr.io/laramies/theharvester:latest

# Create shared volume directory
mkdir -p /tmp/leadgen_harvester
chown $DEPLOY_USER:$DEPLOY_USER /tmp/leadgen_harvester

echo "    Docker configured."

# =============================================================================
# 3b. Redis setup
# =============================================================================
echo "[3b/11] Configuring Redis..."

systemctl enable redis-server
systemctl start redis-server

echo "    Redis configured."

# =============================================================================
# 4b. SearXNG setup
# =============================================================================
echo "[4b/11] Configuring SearXNG..."

mkdir -p /etc/searxng

cat > /etc/searxng/settings.yml <<EOF
use_default_settings: true

server:
  secret_key: "$(openssl rand -hex 32)"
  limiter: false

search:
  safe_search: 0
  formats:
    - html
    - json

engines:
  - name: google
    disabled: false
  - name: bing
    disabled: false
  - name: duckduckgo
    disabled: false
EOF

docker pull searxng/searxng:latest

docker run -d \
    --name searxng \
    --restart always \
    -p 8080:8080 \
    -v /etc/searxng:/etc/searxng \
    searxng/searxng:latest

echo "    SearXNG running on http://localhost:8080"

# =============================================================================
# 4. Create project directory
# =============================================================================
echo "[4/11] Creating project directory..."

PROJECT_DIR="/home/$DEPLOY_USER/lead_gen2"
mkdir -p "$PROJECT_DIR"
chown -R $DEPLOY_USER:$DEPLOY_USER "$(dirname "$PROJECT_DIR")"

echo "    Project directory: $PROJECT_DIR"

# =============================================================================
# 5. Git clone (interactive)
# =============================================================================
echo "[5/11] Cloning repository..."
echo ""

read -p "GitHub repository URL: " REPO_URL
if [ -z "$REPO_URL" ]; then
    echo "ERROR: Repository URL is required."
    exit 1
fi

cd "$PROJECT_DIR"
sudo -u $DEPLOY_USER git clone -b test "$REPO_URL" .
echo "    Repository cloned (test branch)."

# =============================================================================
# 5b. Interactive configuration (required)
# =============================================================================
echo "[5b/11] configuration..."
echo ""

read -p "GROQ API Key: " GROQ_API_KEY
[ -z "$GROQ_API_KEY" ] && echo "ERROR: GROQ_API_KEY is required." && exit 1

read -p "GROQ Model [llama-3.1-8b-instant]: " GROQ_MODEL
GROQ_MODEL=${GROQ_MODEL:-llama-3.1-8b-instant}

read -p "GROQ Model [llama-3.1-8b-instant]: " GROQ_MODEL
GROQ_MODEL=${GROQ_MODEL:-llama-3.1-8b-instant}

read -p "SearXNG URL [http://localhost:8080]: " SEARXNG_URL
SEARXNG_URL=${SEARXNG_URL:-http://localhost:8080}

echo "    Configuration collected."

# =============================================================================
# 6. Create virtual environments
# =============================================================================
echo "[6/11] Creating virtual environments..."

SERVICES="01_discovery 01b_browsing 02_enrichment 03_verification 04_api"
for svc in $SERVICES; do
    echo "    Creating $svc venv..."
    sudo -u $DEPLOY_USER python3 -m venv "$PROJECT_DIR/$svc/venv"
done

echo "    Virtual environments created."

# =============================================================================
# 7. Install Python dependencies
# =============================================================================
echo "[7/11] Installing Python dependencies..."

for svc in $SERVICES; do
    echo "    Installing $svc..."
    sudo -u $DEPLOY_USER "$PROJECT_DIR/$svc/venv/bin/pip" install -r "$PROJECT_DIR/$svc/requirements.txt" --quiet
done

echo "    Python dependencies installed."

# =============================================================================
# 7b. Write .env files
# =============================================================================
echo "[7b/11] Writing .env files..."

# All 5 services get DATABASE_URL
for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
    echo "DATABASE_URL=postgresql://$DEPLOY_USER:$DB_PASSWORD@localhost:5432/lead_gen2" > "$PROJECT_DIR/$svc/.env"
done

# Discovery gets GROQ + SEARXNG
cat >> "$PROJECT_DIR/01_discovery/.env" <<EOF
GROQ_API_KEY=$GROQ_API_KEY
GROQ_MODEL=$GROQ_MODEL
SEARXNG_URL=$SEARXNG_URL
EOF

# API gets Redis + defaults
cat >> "$PROJECT_DIR/04_api/.env" <<EOF
REDIS_URL=redis://localhost:6379/0
API_HOST=0.0.0.0
API_PORT=8000
ALLOWED_ORIGINS=*
EOF

echo "    .env files written."

# =============================================================================
# 8. Install Playwright
# =============================================================================
echo "[8/11] Installing Playwright..."

sudo -u $DEPLOY_USER "$PROJECT_DIR/01b_browsing/venv/bin/pip" install playwright
sudo -u $DEPLOY_USER "$PROJECT_DIR/01b_browsing/venv/bin/python" -m playwright install chromium
apt install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 >/dev/null 2>&1 || true

echo "    Playwright installed."

# =============================================================================
# 9. Write systemd service files
# =============================================================================
echo "[9/11] Creating systemd services..."

LOG_DIR="/var/log/lead_gen2"
mkdir -p "$LOG_DIR"
chown $DEPLOY_USER:$DEPLOY_USER "$LOG_DIR"

# Discovery service
cat > /etc/systemd/system/leadgen-discovery.service <<EOF
[Unit]
Description=Lead Gen Discovery Service
After=network.target postgresql.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/01_discovery
Environment="PATH=$PROJECT_DIR/01_discovery/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/01_discovery/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Browsing service
cat > /etc/systemd/system/leadgen-browsing.service <<EOF
[Unit]
Description=Lead Gen Browsing Service
After=network.target postgresql.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/01b_browsing
Environment="PATH=$PROJECT_DIR/01b_browsing/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/01b_browsing/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enrichment service
cat > /etc/systemd/system/leadgen-enrichment.service <<EOF
[Unit]
Description=Lead Gen Enrichment Service
After=network.target postgresql.service docker.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/02_enrichment
Environment="PATH=$PROJECT_DIR/02_enrichment/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/02_enrichment/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Verification service
cat > /etc/systemd/system/leadgen-verification.service <<EOF
[Unit]
Description=Lead Gen Verification Service
After=network.target postgresql.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/03_verification
Environment="PATH=$PROJECT_DIR/03_verification/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/03_verification/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# API service
cat > /etc/systemd/system/leadgen-api.service <<EOF
[Unit]
Description=Lead Gen API Service
After=network.target postgresql.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/04_api
Environment="PATH=$PROJECT_DIR/04_api/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/04_api/venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

echo "    Systemd services created."

# =============================================================================
# 10. Nginx configuration
# =============================================================================
echo "[10/11] Configuring nginx..."

cat > /etc/nginx/sites-available/lead_gen2 <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        chunked_transfer_encoding on;
    }
}
EOF

ln -sf /etc/nginx/sites-available/lead_gen2 /etc/nginx/sites-enabled/lead_gen2
rm -f /etc/nginx/sites-enabled/default

systemctl enable nginx
systemctl restart nginx

echo "    nginx configured."

# =============================================================================
# 10b. Sudoers entry for deploy user
# =============================================================================
echo "$DEPLOY_USER ALL=(ALL) NOPASSWD: /bin/systemctl start leadgen-*, /bin/systemctl stop leadgen-*, /bin/systemctl restart leadgen-*" > /etc/sudoers.d/leadgen
chmod 440 /etc/sudoers.d/leadgen

echo "    Sudoers entry added."

# =============================================================================
# 11. Complete
# =============================================================================
echo "[11/11] Setup complete!"
echo ""
echo "========================================"
echo "IMPORTANT NEXT STEPS:"
echo "========================================"
echo ""
echo "1. REBOOT required for docker group membership:"
echo "   sudo reboot"
echo ""
echo "2. .env files have been created automatically."
echo "   You can review them in each service directory."
echo ""
echo "3. Run deploy.sh:"
echo "   bash deploy.sh"
echo ""
echo "========================================"
echo "DETAILS:"
echo "========================================"
echo "Database: postgresql://$DEPLOY_USER:***@localhost:5432/leadgen2"
echo "GROQ Model: $GROQ_MODEL"
echo "SearXNG: $SEARXNG_URL"
echo "========================================"