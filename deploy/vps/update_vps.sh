#!/usr/bin/env bash
# ==============================================================================
# WayMate Pool Engine — Fast VPS Update Script
# Updates repository, rebuilds containers, and validates health
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo -e "${BLUE}=== Updating WayMate Pool Engine on VPS ===${NC}"

# Pull latest Git commits
echo "Pulling latest code from origin/master..."
git pull origin master

# Rebuild and restart API container
ENV_FILE="${PROJECT_ROOT}/.env.production"
echo "Rebuilding and restarting production containers..."
docker compose -f "${PROJECT_ROOT}/deploy/docker/docker-compose.production.yml" --env-file "${ENV_FILE}" up --build -d pool-engine-api

# Validate health
echo "Verifying health..."
sleep 3
curl -s -f http://127.0.0.1:8000/v1/health/liveness && echo -e "\n${GREEN}✓ API is Healthy!${NC}"
curl -s -f http://127.0.0.1:8000/v1/health/readiness && echo -e "\n${GREEN}✓ API is Ready for Dispatch!${NC}"
