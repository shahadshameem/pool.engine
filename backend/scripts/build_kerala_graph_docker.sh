#!/usr/bin/env bash
# ==============================================================================
# Script: build_kerala_graph_docker.sh
# Purpose: Compiles Kerala OSRM Contraction Hierarchies (CH) graph inside the
#          pinned Linux OSRM Docker container to guarantee binary fingerprint
#          compatibility on the Contabo VPS.
# ==============================================================================

set -euo pipefail

DATA_DIR="${1:-./deploy/docker/osrm-data/kerala}"
OSRM_IMAGE="osrm/osrm-backend:v5.27.1"

echo "=== Compiling Kerala OSRM CH Graph using Docker (${OSRM_IMAGE}) ==="
echo "Target data directory: ${DATA_DIR}"

if [ ! -f "${DATA_DIR}/kerala.osm" ]; then
    echo "ERROR: ${DATA_DIR}/kerala.osm not found."
    echo "Place the extracted kerala.osm file into ${DATA_DIR} before running."
    exit 1
fi

echo "Step 1: Extracting road network..."
docker run --rm -v "$(realpath "${DATA_DIR}"):/data" "${OSRM_IMAGE}" osrm-extract -p /opt/car.lua /data/kerala.osm

echo "Step 2: Contracting road network..."
docker run --rm -v "$(realpath "${DATA_DIR}"):/data" "${OSRM_IMAGE}" osrm-contract /data/kerala.osrm

echo "=== Compilation Complete! Generated files: ==="
ls -lh "${DATA_DIR}/kerala.osrm"*
