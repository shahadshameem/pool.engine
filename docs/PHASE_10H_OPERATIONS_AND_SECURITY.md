# Pool Engine — Phase 10H: Operations, Monitoring & Incident Recovery Guide

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 10H — Operations & Security  
**Date:** October 29, 2026  
**Auditor:** Senior SRE / Production Operations Lead (Pair-Programming Agent)  
**Target Environment:** Contabo Linux VPS (Ubuntu 24.04 LTS)  
**Status:** COMPLETE & DOCUMENTED  

---

## 1. Executive Summary

This operational runbook defines the monitoring safeguards, automated health probes, database backup scheduling, privacy controls, and incident response procedures for operating Pool Engine on the Contabo Linux VPS during the Kerala pilot.

---

## 2. Container Health Monitoring & Automated Recovery

All services declare Docker native health checks with `restart: unless-stopped` policies:

| Container | Health Probe Command | Interval | Timeout | Retries | Recovery Action |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`pool-engine-prod-postgres`** | `pg_isready -U pool_prod_user -d pool_engine_prod` | 5s | 3s | 5 | Docker auto-restart |
| **`pool-engine-prod-osrm-kerala`** | `wget -qO- 'http://127.0.0.1:5000/nearest/v1/driving/76.9366,8.5241?number=1'` | 5s | 3s | 5 | Docker auto-restart |
| **`pool-engine-prod-api`** | `python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health/liveness')"` | 10s | 3s | 3 | Docker auto-restart |

### Host-Level Health Monitoring
Coolify or host cron monitors overall container state:
```bash
docker ps --filter "name=pool-engine-prod" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

---

## 3. Privacy Controls & Log Hygiene

1. **Geospatial Privacy (Constitution Principle VIII):**
   - Exact passenger GPS coordinates are excluded from standard HTTP access logs.
   - Dispatch telemetry logging employs `mask_coordinate(lat, lon, precision=2)`, coarsening coordinates to ~1.1 km accuracy.
2. **Credential Redaction:**
   - Database DSN passwords are scrubbed via `sanitize_sensitive_strings()` (`postgresql://user:***@host`).
   - Authorization Bearer tokens are never printed in application logs or exception traces.

---

## 4. Automated Backup Scheduling

To safeguard ride data and passenger transaction history:
1. **Cron Configuration:** Add to the host VPS crontab (`sudo crontab -e`):
   ```cron
   # Nightly compressed database snapshot at 03:00 UTC
   0 3 * * * /path/to/pool-engine/scripts/backup_production_db.sh >> /var/log/pool_engine_backup.log 2>&1
   ```
2. **Backup Storage:** Snapshots are written to `/var/backups/pool_engine/pool_engine_prod_<TIMESTAMP>.dump`.
3. **Retention Policy:** `scripts/backup_production_db.sh` automatically prunes backups older than 14 days.

---

## 5. Incident Response & Rollback Procedures

### Scenario A: Routing Backend Degraded or Unreachable
- **Symptoms:** `/v1/health/readiness` returns HTTP 503; logs indicate `RouteTimeoutError` or connection refused on `osrm-kerala:5000`.
- **Diagnosis:**
  ```bash
  docker logs --tail 100 pool-engine-prod-osrm-kerala
  ```
- **Remediation:**
  ```bash
  docker restart pool-engine-prod-osrm-kerala
  ```

### Scenario B: Database Connection Exhaustion
- **Symptoms:** API logs report `psycopg_pool.PoolTimeout`.
- **Diagnosis:**
  ```bash
  docker exec pool-engine-prod-postgres psql -U pool_prod_user -d pool_engine_prod -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
  ```
- **Remediation:** Verify that idle connections are recycling; check if long-running transactions are locking tables; restart API container to drain the pool if necessary.

### Scenario C: Complete Application Rollback
If a newly deployed API image introduces a critical defect:
```bash
# 1. Stop current containers
docker compose -f deploy/docker/docker-compose.production.yml down

# 2. Revert to previous Git release tag
git checkout <PREVIOUS_STABLE_COMMIT>

# 3. Rebuild and launch previous image
docker compose -f deploy/docker/docker-compose.production.yml up --build -d

# 4. Verify readiness
curl -f http://127.0.0.1:8000/v1/health/readiness
```
*Note: Persistent data volumes (`pool_engine_pgdata_prod` and `pool_engine_osrm_kerala_data`) remain intact across image rollbacks.*
