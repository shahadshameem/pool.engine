# Pool Engine — Containerized Staging Deployment

This directory contains the Docker and Docker Compose configuration for launching the multi-region Pool Engine staging topology on Linux / CI / Cloud environments.

## Services Defined
1. `postgres-staging` (PostgreSQL 16 on port 5432)
2. `osrm-manhattan` (OSRM backend with Manhattan Contraction Hierarchies graph on port 5000)
3. `osrm-kerala` (OSRM backend with Kerala Contraction Hierarchies graph on port 5001)
4. `pool-engine-api` (Pool Engine ASGI service on port 8000)

## Supplying OSRM Graphs
Before starting the containers, precompiled OSRM Contraction Hierarchies (`.osrm*` files) must be placed in the respective directories:
- `deploy/docker/osrm-data/manhattan/manhattan.osrm*`
- `deploy/docker/osrm-data/kerala/kerala.osrm*`

Alternatively, create symlinks to your existing compiled graphs:
```bash
ln -s /path/to/manhattan.osrm* deploy/docker/osrm-data/manhattan/
ln -s /path/to/kerala.osrm* deploy/docker/osrm-data/kerala/
```

## Running Staging
```bash
docker compose -f deploy/docker/docker-compose.staging.yml up --build -d
```

## Verifying Readiness
```bash
curl -f http://127.0.0.1:8000/v1/health/readiness
```
