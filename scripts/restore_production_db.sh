#!/usr/bin/env bash
# ==============================================================================
# Script: restore_production_db.sh
# Purpose: Restores a specified pg_dump custom archive into the production
#          Pool Engine database container with pre-restore validation.
# ==============================================================================

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <path_to_backup_file.dump>"
    exit 1
fi

BACKUP_FILE="$1"
CONTAINER_NAME="pool-engine-prod-postgres"
DB_USER="pool_prod_user"
DB_NAME="pool_engine_prod"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file '${BACKUP_FILE}' does not exist."
    exit 1
fi

echo "=== Restoring Pool Engine Database from ${BACKUP_FILE} ==="
read -rp "WARNING: This will restore database '${DB_NAME}'. Type 'RESTORE' to confirm: " CONFIRM
if [ "${CONFIRM}" != "RESTORE" ]; then
    echo "Restoration aborted."
    exit 1
fi

echo "Streaming backup into ${CONTAINER_NAME}..."
cat "${BACKUP_FILE}" | docker exec -i "${CONTAINER_NAME}" pg_restore -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists --no-owner

echo "=== Restoration Completed Successfully ==="
echo "Verifying tables..."
docker exec "${CONTAINER_NAME}" psql -U "${DB_USER}" -d "${DB_NAME}" -c "\dt"
