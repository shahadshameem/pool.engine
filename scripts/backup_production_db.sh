#!/usr/bin/env bash
# ==============================================================================
# Script: backup_production_db.sh
# Purpose: Creates a compressed, timestamped pg_dump backup of the production
#          Pool Engine database on the Contabo VPS without service interruption.
# ==============================================================================

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/pool_engine}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/pool_engine_prod_${TIMESTAMP}.dump"
CONTAINER_NAME="pool-engine-prod-postgres"
DB_USER="pool_prod_user"
DB_NAME="pool_engine_prod"

mkdir -p "${BACKUP_DIR}"

echo "=== Initiating Pool Engine Database Backup at ${TIMESTAMP} ==="
echo "Writing snapshot to ${BACKUP_FILE}..."

# Execute pg_dump inside container using custom archive format (-F c)
docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" -F c > "${BACKUP_FILE}"

# Verify backup size
FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "PASS: Backup complete! File size: ${FILE_SIZE}"

# Retention: Retain backups for 14 days, delete older snapshots
echo "Purging snapshots older than 14 days..."
find "${BACKUP_DIR}" -name "pool_engine_prod_*.dump" -mtime +14 -delete
echo "Retention policy applied."
