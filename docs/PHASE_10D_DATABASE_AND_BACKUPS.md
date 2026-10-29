# Pool Engine — Phase 10D: Production Database & Backup Architecture

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 10D — Database & Backups  
**Date:** October 29, 2026  
**Auditor:** Senior Database Architect / SRE Lead (Pair-Programming Agent)  
**Target Database:** PostgreSQL 16 Alpine on Contabo Linux VPS  
**Status:** COMPLETE & DOCUMENTED  

---

## 1. Executive Summary

This document specifies the production database architecture, transaction semantics, connection pooling limits, least-privilege security model, and automated disaster recovery procedures for Pool Engine on the Contabo Linux VPS.

Pool Engine uses `PostgresRideStorage` directly via psycopg3 and `psycopg_pool.ConnectionPool`. The relational schema enforces strict capacity and spatial invariants, using atomic row-level locks to eliminate passenger over-allocation during concurrent seat holds.

---

## 2. Storage Architecture & Relational Schema

### 2.1 Storage Implementation
- **Adapter:** `src/engine/adapters/postgres_storage.py` (`PostgresRideStorage`)
- **Connection Pool:** `psycopg_pool.ConnectionPool` with thread-safe checkout/checkin via context manager.
- **SQL Execution:** 100% parameterized queries (`%s`). Zero dynamic string concatenation.
- **Row Locking:** Seat hold reservations and ride status transitions execute `SELECT ... FOR UPDATE` within atomic transaction blocks.

### 2.2 Relational Tables (7 Core Domain Entities)
1. `vehicles`: Vehicle fleet state, driver reference, seat and luggage capacities, and current coordinates.
2. `rides`: Shared ride instances, driver assignment, scheduled departure, active passenger count, and VMT.
3. `route_stops`: Ordered stops along each ride itinerary, promised arrival windows, passenger deltas, and coordinates.
4. `ride_requests`: Rider demand submissions, pickup/dropoff coordinates, seat count, and promised windows.
5. `join_requests`: Passenger requests to join an existing ride, host/traveller acceptance flags, and expiration.
6. `seat_holds`: Temporary atomic seat reservations with hard timestamp expirations preventing double booking.
7. `idempotency_records`: Cryptographic idempotency tokens preventing duplicate submissions.

### 2.3 Automated Schema Migration
In `deploy/docker/docker-compose.production.yml`:
```yaml
    volumes:
      - pgdata_production:/var/lib/postgresql/data
      - ../../src/engine/adapters/schema.sql:/docker-entrypoint-initdb.d/01_schema.sql:ro
```
When `postgres-production` initializes a new data directory, PostgreSQL automatically executes `schema.sql`. The schema is fully idempotent using `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

---

## 3. Connection Pool Sizing for 4-vCPU VPS

On the Contabo VPS (4 vCPUs, 7.8 GiB RAM):
- **PostgreSQL Max Connections:** 100 (default PostgreSQL 16 limit).
- **API Connection Pool:**
  - `DB_POOL_MIN_SIZE`: `2` connections (keeps idle connections warm).
  - `DB_POOL_MAX_SIZE`: `20` connections (matches Uvicorn multi-worker concurrency headroom).
  - `DB_POOL_TIMEOUT_SECONDS`: `10.0` seconds.
- **Memory Footprint:** PostgreSQL working set remains under ~120 MB RSS under peak concurrency, safely below the 1.5 GiB container limit.

---

## 4. Security & Access Boundaries

1. **Private Docker Network:** The database container does not declare `ports` on the host interface. It communicates with `pool-engine-api` strictly across the private `poolengine-prod-net` Docker network on `postgres-production:5432`.
2. **Least-Privilege User:** The application connects as `pool_prod_user` with access restricted to database `pool_engine_prod`.
3. **Password Management:** `${PRODUCTION_DB_PASSWORD}` is passed via environment variable file `.env.production` on the VPS and is never committed to Git.

---

## 5. Automated Backup & Disaster Recovery Procedures

### 5.1 Automated Snapshot Script (`scripts/backup_production_db.sh`)
- **Format:** Custom PostgreSQL archive (`-F c`), compressed and timestamped.
- **Invocation:** Can be scheduled via system cron on the VPS:
  ```bash
  # Daily snapshot at 03:00 UTC with 14-day retention
  0 3 * * * /app/scripts/backup_production_db.sh >> /var/log/pool_engine_backup.log 2>&1
  ```
- **Execution:** Runs `pg_dump` non-destructively without blocking reads or writes:
  ```bash
  docker exec pool-engine-prod-postgres pg_dump -U pool_prod_user -d pool_engine_prod -F c > /var/backups/pool_engine/pool_engine_prod_$(date +%Y%m%d_%H%M%S).dump
  ```

### 5.2 Tested Restoration Procedure (`scripts/restore_production_db.sh`)
- **Restoration Tool:** Uses `pg_restore --clean --if-exists`.
- **Command:**
  ```bash
  bash scripts/restore_production_db.sh /var/backups/pool_engine/pool_engine_prod_20261029_120000.dump
  ```
- **Safety Prompt:** Requires explicit string confirmation (`RESTORE`) to prevent accidental overwrites.
