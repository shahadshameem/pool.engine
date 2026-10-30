#!/usr/bin/env bash
# ==============================================================================
# WayMate Pool Engine — Automated VPS Setup & Deployment Script
# Operating System: Ubuntu 22.04 LTS / 24.04 LTS
# Tested on: Contabo VPS, DigitalOcean Droplet, Hetzner Cloud, AWS EC2
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}==============================================================================${NC}"
echo -e "${BLUE}        WayMate Pool Engine — Production VPS Deployment                       ${NC}"
echo -e "${BLUE}==============================================================================${NC}"

# Check running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Please run this script with sudo or as root.${NC}"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo -e "\n${YELLOW}[Step 1/6] Installing Essential Packages & Docker Engine...${NC}"
apt-get update -y
apt-get install -y ca-certificates curl gnupg lsb-release ufw wget git jq

# Install Docker if not installed
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    echo -e "${GREEN}✓ Docker installed successfully.${NC}"
else
    echo -e "${GREEN}✓ Docker already installed: $(docker --version)${NC}"
fi

# Configure UFW firewall
echo -e "\n${YELLOW}[Step 2/6] Configuring Host Firewall (UFW)...${NC}"
ufw allow 22/tcp comment 'SSH' || true
ufw allow 80/tcp comment 'HTTP / ACME' || true
ufw allow 443/tcp comment 'HTTPS' || true
ufw --force enable || true
echo -e "${GREEN}✓ Ports 22, 80, 443 active.${NC}"

# Configure Production Environment Variables
echo -e "\n${YELLOW}[Step 3/6] Configuring Production Environment (.env.production)...${NC}"
ENV_FILE="${PROJECT_ROOT}/.env.production"
if [ ! -f "${ENV_FILE}" ]; then
    echo "Generating new .env.production from template..."
    cp "${PROJECT_ROOT}/.env.production.example" "${ENV_FILE}"
    
    # Generate secure 32-character database password
    RANDOM_PASS=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 32 || openssl rand -base64 24 | tr -dc A-Za-z0-9 | head -c 32)
    sed -i "s/replace_with_strong_random_database_password_32chars/${RANDOM_PASS}/g" "${ENV_FILE}"
    
    # Generate secure random API key for frontend/admin dispatch
    RANDOM_API_KEY=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 32 || openssl rand -base64 24 | tr -dc A-Za-z0-9 | head -c 32)
    sed -i "s/API_KEYS=/API_KEYS=${RANDOM_API_KEY}:admin/g" "${ENV_FILE}"
    
    chmod 600 "${ENV_FILE}"
    echo -e "${GREEN}✓ Generated secure .env.production with random DB credentials and API key.${NC}"
else
    echo -e "${GREEN}✓ Existing .env.production preserved.${NC}"
fi

# Check OSRM Kerala Graph
echo -e "\n${YELLOW}[Step 4/6] Verifying Kerala OSRM Road Network...${NC}"
OSRM_DIR="${PROJECT_ROOT}/deploy/docker/osrm-data/kerala"
mkdir -p "${OSRM_DIR}"

if [ ! -f "${OSRM_DIR}/kerala.osrm.hsgr" ]; then
    echo "Compiled Kerala OSRM graph not found in ${OSRM_DIR}."
    
    if [ ! -f "${OSRM_DIR}/kerala.osm" ]; then
        echo "Downloading Kerala OpenStreetMap extract (Geofabrik / Indian subcontinent mirror)..."
        wget -q --show-progress -O "${OSRM_DIR}/kerala-latest.osm.pbf" \
          "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf" || \
          wget -q --show-progress -O "${OSRM_DIR}/kerala-latest.osm.pbf" \
          "https://download.geofabrik.de/asia/india-latest.osm.pbf" || true
        
        # If PBF is present, extract via osrm-extract directly
        if [ -f "${OSRM_DIR}/kerala-latest.osm.pbf" ]; then
            echo "Extracting road network from PBF..."
            docker run --rm -v "${OSRM_DIR}:/data" osrm/osrm-backend:v5.27.1 \
              osrm-extract -p /opt/car.lua /data/kerala-latest.osm.pbf
            mv "${OSRM_DIR}/kerala-latest.osrm" "${OSRM_DIR}/kerala.osrm" 2>/dev/null || true
            mv "${OSRM_DIR}/kerala-latest.osrm"* "${OSRM_DIR}/" 2>/dev/null || true
            rm -f "${OSRM_DIR}/kerala-latest.osm.pbf"
        fi
    else
        echo "Found raw kerala.osm. Compiling Contraction Hierarchies..."
        bash "${PROJECT_ROOT}/scripts/build_kerala_graph_docker.sh" "${OSRM_DIR}"
    fi

    if [ -f "${OSRM_DIR}/kerala.osrm" ] && [ ! -f "${OSRM_DIR}/kerala.osrm.hsgr" ]; then
        echo "Contracting road network..."
        docker run --rm -v "${OSRM_DIR}:/data" osrm/osrm-backend:v5.27.1 \
          osrm-contract /data/kerala.osrm
    fi
else
    echo -e "${GREEN}✓ Kerala OSRM graph ready (${OSRM_DIR}/kerala.osrm.hsgr present).${NC}"
fi

# Install and configure Caddy Reverse Proxy for Automatic HTTPS
echo -e "\n${YELLOW}[Step 5/6] Configuring Caddy Reverse Proxy with Automatic HTTPS...${NC}"
if ! command -v caddy &> /dev/null; then
    echo "Installing Caddy..."
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
    echo -e "${GREEN}✓ Caddy installed.${NC}"
else
    echo -e "${GREEN}✓ Caddy already installed.${NC}"
fi

# Copy Caddyfile
mkdir -p /etc/caddy
cp "${PROJECT_ROOT}/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
systemctl enable caddy
systemctl reload caddy 2>/dev/null || systemctl restart caddy

# Build and Launch Docker Services
echo -e "\n${YELLOW}[Step 6/6] Launching Production Multi-Container Topology...${NC}"
docker compose -f "${PROJECT_ROOT}/deploy/docker/docker-compose.production.yml" --env-file "${ENV_FILE}" up --build -d

echo -e "\n${BLUE}Waiting for services to become healthy...${NC}"
sleep 5

# Validate Health Status
echo "Checking Pool Engine Liveness..."
LIVENESS_STATUS=0
for i in {1..12}; do
    if curl -s -f http://127.0.0.1:8000/v1/health/liveness > /dev/null; then
        LIVENESS_STATUS=1
        break
    fi
    echo "Waiting for Pool Engine API... (${i}/12)"
    sleep 3
done

if [ "${LIVENESS_STATUS}" -eq 1 ]; then
    echo -e "${GREEN}==============================================================================${NC}"
    echo -e "${GREEN}✓ WayMate Pool Engine is ONLINE and HEALTHY on this VPS!                     ${NC}"
    echo -e "${GREEN}==============================================================================${NC}"
    echo -e "Liveness:  http://127.0.0.1:8000/v1/health/liveness"
    echo -e "Readiness: http://127.0.0.1:8000/v1/health/readiness"
    echo -e "Metrics:   http://127.0.0.1:8000/v1/metrics"
    echo -e "\n${YELLOW}Next Step: Point your DNS A-Record for api-pool.waymate.in to this VPS IP address.${NC}"
    echo -e "Caddy will automatically provision a free Let's Encrypt TLS certificate."
else
    echo -e "${RED}[WARNING] Service took longer than expected to report liveness.${NC}"
    echo "Inspect logs with: docker compose -f deploy/docker/docker-compose.production.yml logs -f"
fi
