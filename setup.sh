#!/bin/bash
#
# Lead Generation Pipeline - Setup Script
# Run as: sudo bash setup.sh [--check] [--force]
# Must be run as root/sudo
#

set -e

# =============================================================================
# Flags
# =============================================================================
DRY_RUN=false
FORCE=false

for arg in "$@"; do
    case $arg in
        --check)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --help)
            echo "Usage: sudo bash setup.sh [--check] [--force]"
            echo ""
            echo "Options:"
            echo "  --check   Dry run - show what would be done without making changes"
            echo "  --force   Override existing configurations"
            echo "  --help    Show this help message"
            exit 0
            ;;
    esac
done

# =============================================================================
# Auto-detect OS
# =============================================================================
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME=$ID
        OS_VERSION=$VERSION_ID
    else
        OS_NAME="unknown"
    fi
    echo "Detected OS: $OS_NAME $OS_VERSION"
}

# =============================================================================
# Health check functions
# =============================================================================
check_postgres() {
    if command -v psql &>/dev/null && systemctl is-active postgresql &>/dev/null; then
        echo "    [OK] PostgreSQL is running"
        return 0
    fi
    echo "    [FAIL] PostgreSQL is not running"
    return 1
}

check_docker() {
    if command -v docker &>/dev/null && systemctl is-active docker &>/dev/null; then
        echo "    [OK] Docker is running"
        return 0
    fi
    echo "    [FAIL] Docker is not running"
    return 1
}

check_redis() {
    if command -v redis-cli &>/dev/null && (systemctl is-active redis-server &>/dev/null || systemctl is-active redis &>/dev/null); then
        echo "    [OK] Redis is running"
        return 0
    fi
    echo "    [FAIL] Redis is not running"
    return 1
}

check_nginx() {
    if command -v nginx &>/dev/null && systemctl is-active nginx &>/dev/null; then
        echo "    [OK] Nginx is running"
        return 0
    fi
    echo "    [FAIL] Nginx is not running"
    return 1
}

# =============================================================================
# Backup function
# =============================================================================
backup_file() {
    local file="$1"
    if [ -f "$file" ]; then
        mkdir -p /var/backups/lead_gen
        local basename=$(basename "$file")
        cp "$file" "/var/backups/lead_gen/${basename}.bak.$(date +%Y%m%d%H%M%S)"
        echo "    Backed up: $file"
    fi
}

# =============================================================================
# Pre-flight checks
# =============================================================================
echo "=== Lead Generation Pipeline Setup ==="
echo ""

detect_os

# Check running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Must run as root (sudo bash setup.sh)"
    exit 1
fi

if [ "$DRY_RUN" = true ]; then
    echo "*** DRY RUN MODE - No changes will be made ***"
    echo ""
fi

# =============================================================================
# Interactive: Deploy user
# =============================================================================
read -p "Deploy username (non-root user who will run services): " DEPLOY_USER
[ -z "$DEPLOY_USER" ] && echo "ERROR: Deploy user required." && exit 1

# Create user if it doesn't exist
id "$DEPLOY_USER" &>/dev/null || useradd -m "$DEPLOY_USER"

echo "Deploy user: $DEPLOY_USER"
echo "Project dir: /home/$DEPLOY_USER/lead_gen"
echo ""

PROJECT_DIR="/home/$DEPLOY_USER/lead_gen"

# =============================================================================
# 1. Install system packages
# =============================================================================
echo "[1/15] Installing system packages..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would install: postgresql, postgresql-contrib, libpq-dev, docker.io, python3, python3-venv, python3-pip, nginx, redis-server, git, curl, build-essential"
else
    # Check Docker before installing
    if command -v docker &>/dev/null; then
        echo "    Docker already installed, skipping"
    else
        apt update
        apt install -y docker.io
        echo "    Docker installed"
    fi

    # Install remaining packages (idempotent - apt skips already installed)
    apt install -y \
        postgresql \
        postgresql-contrib \
        libpq-dev \
        python3 \
        python3-venv \
        python3-pip \
        nginx \
        redis-server \
        git \
        curl \
        build-essential

    echo "    System packages installed."
fi

# =============================================================================
# 2. PostgreSQL setup
# =============================================================================
echo "[2/15] Configuring PostgreSQL..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would enable and start PostgreSQL"
    echo "    Would create database and user"
else
    systemctl enable postgresql
    systemctl start postgresql

    # Check if database already exists
    DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='lead_gen'" 2>/dev/null || echo "0")
    if [ "$DB_EXISTS" = "1" ] && [ "$FORCE" = false ]; then
        echo "    Database 'lead_gen' already exists, skipping creation"
    else
        if [ "$DB_EXISTS" = "1" ] && [ "$FORCE" = true ]; then
            backup_file "/home/$DEPLOY_USER/lead_gen/.env"
        fi

        # Generate random password
        DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 16)

        # Check if user exists
        USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DEPLOY_USER'" 2>/dev/null || echo "0")
        if [ "$USER_EXISTS" = "1" ]; then
            sudo -u postgres psql -c "ALTER USER $DEPLOY_USER WITH PASSWORD '$DB_PASSWORD';"
        else
            sudo -u postgres psql -c "CREATE USER $DEPLOY_USER WITH PASSWORD '$DB_PASSWORD';"
        fi

        sudo -u postgres psql -c "CREATE DATABASE lead_gen OWNER $DEPLOY_USER;" 2>/dev/null || true
        sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE lead_gen TO $DEPLOY_USER;"

        # Grant schema privileges
        sudo -u postgres psql -d lead_gen -c "GRANT ALL ON SCHEMA public TO $DEPLOY_USER;"
        sudo -u postgres psql -d lead_gen -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DEPLOY_USER;"
        sudo -u postgres psql -d lead_gen -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DEPLOY_USER;"

        # Store password for .env
        echo "$DB_PASSWORD" > /tmp/leadgen_db_password
        chmod 600 /tmp/leadgen_db_password
    fi

    check_postgres
fi

# =============================================================================
# 3. Docker setup
# =============================================================================
echo "[3/15] Configuring Docker..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would enable and start Docker"
    echo "    Would add $DEPLOY_USER to docker group"
    echo "    Would pull theHarvester image"
else
    systemctl enable docker
    systemctl start docker

    # Add deploy user to docker group
    usermod -aG docker $DEPLOY_USER

    # Pull theHarvester image
    docker pull ghcr.io/laramies/theharvester:latest

    # Create shared volume directory
    mkdir -p /tmp/leadgen_harvester
    chown $DEPLOY_USER:$DEPLOY_USER /tmp/leadgen_harvester

    check_docker
fi

# =============================================================================
# 4. Redis setup
# =============================================================================
echo "[4/15] Configuring Redis..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would enable and start Redis"
else
    systemctl enable redis-server 2>/dev/null || systemctl enable redis 2>/dev/null || true
    systemctl start redis-server 2>/dev/null || systemctl start redis 2>/dev/null || true

    check_redis
fi

# =============================================================================
# 5. SearXNG setup with port detection
# =============================================================================
echo "[5/15] Configuring SearXNG..."

SEARXNG_PORT=8080

# Detect if port is already in use
while ss -tlnp | grep -q ":$SEARXNG_PORT "; do
    echo "    Port $SEARXNG_PORT is in use, trying next..."
    SEARXNG_PORT=$((SEARXNG_PORT + 1))
done

echo "    Using SearXNG port: $SEARXNG_PORT"

if [ "$DRY_RUN" = true ]; then
    echo "    Would create SearXNG config on port $SEARXNG_PORT"
    echo "    Would pull and run SearXNG Docker container"
else
    mkdir -p /etc/searxng

    # Backup existing config
    if [ -f /etc/searxng/settings.yml ]; then
        backup_file /etc/searxng/settings.yml
    fi

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

    # Check if container already running
    if docker ps --format '{{.Names}}' | grep -q searxng; then
        echo "    SearXNG container already running, restarting with new config"
        docker restart searxng
    else
        docker pull searxng/searxng:latest
        docker run -d \
            --name searxng \
            --restart always \
            -p $SEARXNG_PORT:8080 \
            -v /etc/searxng:/etc/searxng \
            searxng/searxng:latest
    fi

    echo "    SearXNG running on http://localhost:$SEARXNG_PORT"
fi

# =============================================================================
# 6. Git clone or pull
# =============================================================================
echo "[6/15] Setting up project directory..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would clone repository to $PROJECT_DIR"
else
    mkdir -p "$PROJECT_DIR"

    if [ -d "$PROJECT_DIR/.git" ]; then
        echo "    Repository already exists, pulling latest..."
        cd "$PROJECT_DIR"
        sudo -u $DEPLOY_USER git pull origin test 2>/dev/null || sudo -u $DEPLOY_USER git pull 2>/dev/null || echo "    Pull skipped (not on test branch)"
    else
        echo "    Repository will be cloned during deploy (interactive step)"
    fi

    chown -R $DEPLOY_USER:$DEPLOY_USER "$PROJECT_DIR"
fi

# =============================================================================
# 7. Interactive configuration
# =============================================================================
echo "[7/15] Configuration..."

read -p "GROQ API Key: " GROQ_API_KEY
[ -z "$GROQ_API_KEY" ] && echo "ERROR: GROQ_API_KEY is required." && exit 1

read -p "GROQ Model [llama-3.1-8b-instant]: " GROQ_MODEL
GROQ_MODEL=${GROQ_MODEL:-llama-3.1-8b-instant}

read -p "SearXNG URL [http://localhost:$SEARXNG_PORT]: " SEARXNG_URL
SEARXNG_URL=${SEARXNG_URL:-http://localhost:$SEARXNG_PORT}

echo "    Configuration collected."

# =============================================================================
# 8. Create virtual environments with --clear and symlink detection
# =============================================================================
echo "[8/15] Creating virtual environments..."

SERVICES="01_discovery 01b_browsing 02_enrichment 03_verification 04_api"

for svc in $SERVICES; do
    VENV_DIR="$PROJECT_DIR/$svc/venv"

    if [ -L "$VENV_DIR/bin/python" ]; then
        echo "    WARNING: $svc venv has symlinked Python, removing..."
        if [ "$DRY_RUN" = false ]; then
            rm -rf "$VENV_DIR"
        fi
    fi

    if [ -d "$VENV_DIR" ] && [ "$FORCE" = false ]; then
        echo "    $svc venv already exists, skipping"
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "    Would create $svc venv with --clear --copies"
    else
        echo "    Creating $svc venv..."
        sudo -u $DEPLOY_USER python3 -m venv --clear --copies "$VENV_DIR"
    fi
done

if [ "$DRY_RUN" = false ]; then
    echo "    Virtual environments created."
fi

# =============================================================================
# 9. Install Python dependencies
# =============================================================================
echo "[9/15] Installing Python dependencies..."

for svc in $SERVICES; do
    if [ "$DRY_RUN" = true ]; then
        echo "    Would install $svc dependencies"
    else
        echo "    Installing $svc..."
        sudo -u $DEPLOY_USER "$PROJECT_DIR/$svc/venv/bin/pip" install -r "$PROJECT_DIR/$svc/requirements.txt" --quiet
    fi
done

if [ "$DRY_RUN" = false ]; then
    echo "    Python dependencies installed."
fi

# =============================================================================
# 10. Write .env files
# =============================================================================
echo "[10/15] Writing .env files..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would write .env files for all services"
else
    # Read DB password
    if [ -f /tmp/leadgen_db_password ]; then
        DB_PASSWORD=$(cat /tmp/leadgen_db_password)
    else
        read -p "Database password: " DB_PASSWORD
    fi

    # All 5 services get DATABASE_URL
    for svc in 01_discovery 01b_browsing 02_enrichment 03_verification 04_api; do
        echo "DATABASE_URL=postgresql://$DEPLOY_USER:$DB_PASSWORD@localhost:5432/lead_gen" > "$PROJECT_DIR/$svc/.env"
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
fi

# =============================================================================
# 11. Install Playwright
# =============================================================================
echo "[11/15] Installing Playwright..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would install Playwright and Chromium"
else
    sudo -u $DEPLOY_USER "$PROJECT_DIR/01b_browsing/venv/bin/pip" install playwright
    sudo -u $DEPLOY_USER "$PROJECT_DIR/01b_browsing/venv/bin/python" -m playwright install chromium
    apt install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 >/dev/null 2>&1 || true

    echo "    Playwright installed."
fi

# =============================================================================
# 12. Write systemd service files
# =============================================================================
echo "[12/15] Creating systemd services..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would create systemd service files for all services"
else
    LOG_DIR="/var/log/lead_gen"
    mkdir -p "$LOG_DIR"
    chown $DEPLOY_USER:$DEPLOY_USER "$LOG_DIR"

    for svc_name in discovery browsing enrichment verification api; do
        case $svc_name in
            discovery) svc_dir="01_discovery" ;;
            browsing) svc_dir="01b_browsing" ;;
            enrichment) svc_dir="02_enrichment" ;;
            verification) svc_dir="03_verification" ;;
            api) svc_dir="04_api" ;;
        esac

        # Backup existing service file
        if [ -f "/etc/systemd/system/leadgen-$svc_name.service" ]; then
            backup_file "/etc/systemd/system/leadgen-$svc_name.service"
        fi

        cat > /etc/systemd/system/leadgen-$svc_name.service <<EOF
[Unit]
Description=Lead Gen ${svc_name^} Service
After=network.target postgresql.service

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$PROJECT_DIR/$svc_dir
Environment="PATH=$PROJECT_DIR/$svc_dir/venv/bin"
Environment="PYTHONPATH=$PROJECT_DIR"
Environment="LOG_DIR=$LOG_DIR"
ExecStart=$PROJECT_DIR/$svc_dir/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    done

    # API service uses uvicorn
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
fi

# =============================================================================
# 13. Nginx configuration with WebSocket support
# =============================================================================
echo "[13/15] Configuring nginx..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would configure nginx with WebSocket support"
else
    # Backup existing config
    if [ -f /etc/nginx/sites-available/lead_gen ]; then
        backup_file /etc/nginx/sites-available/lead_gen
    fi

    cat > /etc/nginx/sites-available/lead_gen <<EOF
server {
    listen 80;
    server_name _;
    proxy_connect_timeout 60s;
    proxy_send_timeout 3600s;
    proxy_read_timeout 86400s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_buffering off;
    }

    location /api/v1/dashboard/ws {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_buffering off;
        proxy_read_timeout 86400s;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/lead_gen /etc/nginx/sites-enabled/lead_gen
    rm -f /etc/nginx/sites-enabled/default

    systemctl enable nginx
    systemctl restart nginx

    check_nginx
fi

# =============================================================================
# 14. Sudoers entry
# =============================================================================
echo "[14/15] Configuring sudoers..."

if [ "$DRY_RUN" = true ]; then
    echo "    Would add sudoers entry for $DEPLOY_USER"
else
    if [ -f /etc/sudoers.d/leadgen ]; then
        echo "    Sudoers file already exists, backing up..."
        cp /etc/sudoers.d/leadgen "/etc/sudoers.d/leadgen.bak.$(date +%Y%m%d%H%M%S)"
    fi
    echo "$DEPLOY_USER ALL=(ALL) NOPASSWD: /bin/systemctl start leadgen-*, /bin/systemctl stop leadgen-*, /bin/systemctl restart leadgen-*, /bin/systemctl enable leadgen-*, /bin/systemctl disable leadgen-*, /bin/systemctl daemon-reload" > /etc/sudoers.d/leadgen
    chmod 440 /etc/sudoers.d/leadgen

    echo "    Sudoers entry added."
fi

# =============================================================================
# 15. Complete
# =============================================================================
echo "[15/15] Setup complete!"
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
echo "Database: postgresql://$DEPLOY_USER:***@localhost:5432/lead_gen"
echo "GROQ Model: $GROQ_MODEL"
echo "SearXNG: $SEARXNG_URL"
echo "========================================"

# Cleanup
rm -f /tmp/leadgen_db_password
