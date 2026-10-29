# Pool Engine — Phase 9F: Production Architecture Gap Analysis & Pilot Roadmap

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 9F — Production Gap Analysis  
**Date:** October 29, 2026  
**Auditor:** Senior Backend Architect / SRE Lead (Pair-Programming Agent)  
**Status:** COMPLETE  

---

## 1. Executive Summary

This document establishes an objective, evidence-based gap analysis separating what is **currently implemented and verified** in Pool Engine from the **operational infrastructure and controls required before launching a controlled passenger pilot**.

The core dispatch and routing algorithms, bounded connection pooling, and multi-region boundary isolation are certified production-ready. However, taking the system from local staging to a live passenger pilot requires bridging gaps in process orchestration, external observability, graph lifecycle updates, and rate limiting.

---

## 2. Confirmed Implemented Capabilities (Baseline)

The following capabilities are fully built, unit-tested, and verified in staging:
1. **Multi-Region Spatial Routing:** Strictly disjoint boundary enforcement, live OSRM routing on Manhattan (:5000) and Kerala (:5001), and out-of-region rejection (HTTP 400).
2. **High-Performance LRU Caching:** Thread-safe, dataset-scoped route caching reducing median response latency to <15 ms.
3. **Bounded Database Pooling:** `psycopg_pool.ConnectionPool` with explicit thread checkouts, atomic transactions, row locking, and rollback recovery.
4. **Defensive API Architecture:** Strict Pydantic input models, request body size limits (1 MB), and non-root Docker packaging.
5. **Multi-Tenant Identity Architecture:** Plug-and-play Firebase ID token verification and API key providers with role-based dispatch gating.
6. **Sub-Second Dispatch Performance:** Verified throughput of >220 req/s with max latency <255 ms under 50 concurrent clients.

---

## 3. Production Gap Matrix

| Architectural Area | Implemented in Repository | Required for Controlled Pilot | Missing Production Control | Risk Level |
| :--- | :--- | :--- | :--- | :--- |
| **1. Process Lifecycle** | Python script runner (`run_staging_server.py`) and Compose file | Systemd units or container orchestrator (Kubernetes/ECS/Nomad) | Automated daemon supervisor with crash restart and health probes | **HIGH** |
| **2. Graph Storage & Updates** | Local `.osrm` files compiled via standalone Python scripts | Automated monthly OSM extract fetcher + pipeline runner | Hot-swapping OSRM graphs without restarting the routing daemon | **MEDIUM** |
| **3. Secrets Management** | Local `.env` files (git-ignored) and environment variables | Cloud Secret Manager (AWS Secrets Manager / GCP Secret Manager / Doppler) | Secret rotation, auditable access, zero plain-text storage | **MEDIUM** |
| **4. Ingress & TLS** | Plain HTTP on `127.0.0.1:8000` | TLS 1.3 termination at reverse proxy (Caddy / Nginx / Cloudflare / AWS ALB) | Valid SSL certificates, HSTS, HTTP-to-HTTPS redirect | **HIGH** |
| **5. Rate Limiting** | Body size limits (1 MB) and coordinate validation | Ingress rate limiting (Token bucket / Redis rate limiter) | Protection against API spam, request floods, and credential stuffing | **HIGH** |
| **6. Observability & Alerting**| In-memory structured telemetry and readiness endpoint | Prometheus metrics exporter + Grafana + PagerDuty / Sentry | Continuous time-series monitoring, latency alerting (p95 > 350ms), and error tracking | **HIGH** |
| **7. Database Backups** | Local PostgreSQL table schema with migrations | Automated WAL archiving + daily managed snapshots (e.g. AWS RDS / Supabase / pgBackRest) | Point-in-time recovery (PITR) and automated disaster recovery testing | **HIGH** |
| **8. Multi-Worker Concurrency**| Single-process Uvicorn (1 event loop) | Multi-worker process manager (Gunicorn with 4-8 Uvicorn workers) | Worker process recycling and multi-core API scaling | **MEDIUM** |
| **9. Data Retention & Privacy** | Coordinate coarsening utility (`precision=2`) | Automated 30-day ride data archival and user deletion pipeline | Scheduled GDPR / DPDP compliance data purging | **LOW** |

---

## 4. Work Required Before a Controlled Passenger Pilot

### 4.1 Tier 1: Mandatory Pre-Pilot Controls (Must complete before any live passengers)
1. **Reverse Proxy & Ingress TLS:**
   - Deploy Caddy or AWS ALB in front of the API.
   - Enforce HTTPS with TLS 1.3.
   - Enforce IP/token rate limits (e.g. max 20 requests/minute per rider IP).
2. **Production Authentication Enforcement:**
   - Run API with `AUTH_ENABLED=true` and `ENVIRONMENT=production`.
   - Connect to live Firebase Project (`waymate-v3` or equivalent) for mobile client JWT verification.
3. **Multi-Worker Server Configuration:**
   - Replace single-process `uvicorn.run()` with `gunicorn -w 4 -k uvicorn.workers.UvicornWorker` to eliminate GIL contention under multi-client bursts.
4. **Managed Database Persistence:**
   - Migrate from local portable PostgreSQL to managed PostgreSQL 16 (AWS RDS, Supabase, or hardened Linux VPS with automated daily snapshots).

### 4.2 Tier 2: Post-Pilot Operational Enhancements (Can defer during initial 10-car pilot)
1. **Automated OSRM Graph CI Pipeline:**
   - Monthly scheduled GitHub Action to download updated Geofabrik extracts, run OSRM extract/contract, and upload compressed `.osrm` graphs to S3/GCS.
2. **Blue-Green Container Deployments:**
   - Zero-downtime routing graph hot-swaps using two parallel OSRM backend pools behind an internal load balancer.
3. **Automated Data Retention Deletion:**
   - Nightly cron job to purge completed ride telemetry older than 30 days.

---

## 5. Capacity & Hosting Cost Analysis for Kerala Pilot

For a controlled regional pilot in Thiruvananthapuram (10–25 active vehicles, up to 500 ride requests/day):

| Component | Minimum Specification | Recommended Hosting Option | Estimated Monthly Cost |
| :--- | :--- | :--- | :--- |
| **Pool Engine API** | 2 vCPU, 2 GB RAM | Cloud Run / ECS Fargate / Small VPS | $10 – $20 |
| **Kerala OSRM Daemon** | 2 vCPU, 4 GB RAM | Dedicated VPS (Hetzner / DigitalOcean / AWS EC2 t4g.medium) | $12 – $25 |
| **PostgreSQL 16 DB** | 2 vCPU, 2 GB RAM, 20 GB SSD | Managed PostgreSQL (Supabase Pro / AWS RDS db.t4g.micro) | $15 – $30 |
| **Total Estimated Infrastructure** | | | **~$37 – $75 / month** |

*Note: Due to the high efficiency of OSRM Contraction Hierarchies, the entire Kerala road network fits in under 100 MB of RAM, allowing the pilot to run reliably on budget-tier virtual servers without requiring expensive high-memory instances.*

---

## 6. Decisions Requiring User Authorization

1. **Production Hosting Provider Selection:** Choice between AWS, GCP, or a dedicated Linux VPS provider (e.g. Hetzner / DigitalOcean).
2. **Firebase Project Integration:** Approval to link the production Firebase project credentials for authenticating live mobile apps.
3. **Domain & DNS Assignment:** Assignment of the production API hostname (e.g., `api.poolengine.io` or `api.waymate.in`).
