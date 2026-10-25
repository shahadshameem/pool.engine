# Deployment and Operations Guide

This guide describes operational architecture, configuration, health probes, and production deployment practices for the provider-independent ride-pooling engine.

---

## 1. Architecture & Hosting Topology

The ride-pooling engine is exposed as a pure Python standard-library **ASGI 3** application (`engine.service.app:create_app`). It has zero runtime framework lock-in (no FastAPI, Starlette, or Django dependencies).

```
[ Client / Ingress Gateway ]
          │ (HTTPS, JWT / API-Key)
          ▼
[ ASGI Server (Uvicorn / Hypercorn) ]
          │
  ┌───────┴───────────────────────┐
  │ PoolEngineService (ASGI 3)   │
  │  ├── Auth Boundary           │
  │  ├── Telemetry & Metrics     │
  │  ├── Coordinate Sanitization │
  │  └── DispatchOrchestrator    │
  └───────┬───────────────┬───────┘
          │               │
          ▼               ▼
[ PostgreSQL Storage ]  [ OSRM / Road Router ]
 (ACID & Seat Holds)     (Table & Distance Matrix)
```

### Supported ASGI Servers
- **Uvicorn** (Recommended for containerized Linux/Windows deployments):
  ```bash
  uvicorn "engine.service.app:create_app" --factory --host 0.0.0.0 --port 8000 --workers 4 --access-log
  ```
- **Hypercorn** (Recommended for HTTP/2 support):
  ```bash
  hypercorn "engine.service.app:create_app" --factory --bind 0.0.0.0:8000 --workers 4
  ```

---

## 2. Environment Variables & Configuration

The service is configured via `ServiceConfig` and standard environment variables:

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | string | *None (required in prod)* | PostgreSQL connection string (`postgresql://user:pass@host:5432/pool_db`). |
| `OSRM_BASE_URL` | string | `http://localhost:5000` | Base URL of the OSRM routing daemon. |
| `MAX_REQUEST_BODY_BYTES` | integer | `1048576` (1 MB) | Maximum permitted request body size to protect against denial-of-service. |
| `REQUIRE_AUTH` | boolean | `false` | When `true`, enforces `X-API-Key` or `Authorization: Bearer <token>` on all non-health endpoints. |
| `ALLOW_UNAUTHENTICATED_IN_PRODUCTION` | boolean | `false` | Explicit opt-out required if running in production without authentication. |
| `STRICT_ROUTING_READINESS` | boolean | `false` | When `true`, routing provider degradation causes readiness probe to fail (503). |
| `SHUTDOWN_TIMEOUT_SECONDS` | float | `5.0` | Grace period in seconds to await active requests during ASGI shutdown. |
| `MASK_COORDINATES_IN_LOGS` | boolean | `true` | When `true`, coarsens lat/lon to 2 decimal places (~1.1 km) in logs and telemetry. |
| `ENVIRONMENT` | string | `development` | Deployment environment name (`development`, `staging`, `production`). |
| `PORT` | integer | `8000` | HTTP service listening port. |
| `HOST` | string | `0.0.0.0` | Network interface binding. |

---

## 3. Database Setup & Schema Management

The engine requires PostgreSQL 14+. PostGIS is optional and will be utilized for spatial bounding if available, but standard composite indexing is fully supported.

### Schema Initialization
Initialize or verify schema on startup:
```python
from engine.adapters.postgres_storage import PostgresRideStorage

storage = PostgresRideStorage(dsn="postgresql://postgres:pass@localhost:5432/pool_db")
storage.init_db()
```

### Table Guarantees
- `pool_requests`: Strict constraints on time windows (`latest_dropoff_time >= earliest_pickup_time`).
- `pool_vehicles`: Current coordinates, driver references, and capacity constraints.
- `pool_rides`: Optimistic concurrency control via `version` column.
- `pool_route_stops`: Composite primary key `(ride_id, stop_order)` enforcing stop ordering invariants.
- `pool_seat_holds`: Row-level seat reservation locking for concurrency protection.

---

## 4. Health, Liveness, and Readiness Probes

The API exposes dedicated endpoints conforming to standard container orchestration probe specifications:

### Liveness Probe (`GET /v1/health/liveness`)
- **Purpose**: Verifies that the ASGI event loop and HTTP server process are alive and responsive.
- **Probe Interval**: Every 5-10 seconds.
- **Expected Status**: `200 OK`.
- **Response**:
  ```json
  {
    "status": "alive",
    "service": "pool-engine"
  }
  ```

### Readiness Probe (`GET /v1/health/readiness`)
- **Purpose**: Verifies end-to-end connectivity to essential dependencies before traffic is routed to the instance.
- **Dependency Isolation**:
  - **Storage (Essential)**: Storage failure marks `ready=False` (`503 Service Unavailable`).
  - **Routing (Optional/Degraded)**: Routing outage is reported as `"routing": "degraded"`. Under default configuration (`strict_routing_readiness=false`), `ready` remains `True` (HTTP 200) because fleet management, ride queries, and cached direct routes remain operational. Setting `strict_routing_readiness=true` causes routing degradation to return HTTP 503.
- **Probe Interval**: Every 5-15 seconds.
- **Response when Ready**: `200 OK`:
  ```json
  {
    "ready": true,
    "status": "ready",
    "components": {
      "storage": "healthy",
      "routing": "healthy"
    }
  }
  ```
- **Response when Degraded/Unreachable**: `503 Service Unavailable`:
  ```json
  {
    "ready": false,
    "status": "not_ready",
    "components": {
      "storage": "unreachable",
      "routing": "degraded",
      "storage_error": "postgresql://postgres:***@db:5432/pool_db: connection refused"
    }
  }
  ```
> [!IMPORTANT]
> Readiness responses and server logs automatically sanitize credentials via `sanitize_sensitive_strings()`. Database passwords and secret tokens are never exposed in probe outputs.

---

## 5. Security & Authentication Boundary

1. **Authentication Boundary**:
   - `AuthProvider` abstracts identity verification.
   - `NoOpAuthProvider` passes requests through when identity is terminated at an external ingress gateway.
   - `ApiKeyAuthProvider` validates `X-API-Key` or `Authorization: Bearer <key>` against registered service accounts.
   - **Production Guard**: Setting `environment="production"` requires `require_auth=True` or explicit `allow_unauthenticated_in_production=True`. Accidental unauthenticated production deployment is rejected at startup.
2. **Payload Protection**:
   - Payloads exceeding `MAX_REQUEST_BODY_BYTES` (default 1 MB) are rejected with `413 Payload Too Large` immediately upon reading the `Content-Length` header or streaming chunks.
3. **Internal Error Sanitization**:
   - Unhandled exceptions return generic `500 Internal Server Error` envelopes (`"An unexpected internal error occurred."`).
   - Detailed stack traces and DSNs are sanitized and logged to internal logging sinks only.

---

## 6. Observability & Telemetry

The service integrates an `EngineTelemetryProvider` to monitor operations and dispatch health:

- **Dispatch Cycle Metrics**: Duration (ms), search status (`COMPLETE`, `APPROXIMATED`, `INCOMPLETE_DEADLINE_EXPIRED`, `INCOMPLETE_ROUTING_ERROR`), committed assignments, rejected assignments, unassigned requests, routing error count, and estimated VMT savings.
- **Concurrency Conflicts**: Optimistic lock collisions and retry events.
- **Idempotency Replays**: Tracked for duplicate request submissions and dispatch runs.
- **Privacy Enforcement**: Coordinates are masked using `mask_coordinate(lat, lon, precision=2)` (~1.1 km accuracy) before logging to satisfy location privacy requirements (Constitution Principle VIII).

---

## 7. Graceful Shutdown

The application implements the ASGI Lifespan protocol:
- On `lifespan.startup`, internal connections and thread pools are established.
- On `lifespan.shutdown` (triggered by `SIGTERM` or `SIGINT`):
  1. Service enters `is_shutting_down = True` state. Any new incoming requests are immediately rejected with `503 SERVICE_SHUTTING_DOWN`.
  2. Active in-flight requests are awaited up to `shutdown_timeout_seconds` (default 5.0s).
  3. Storage connections and routing network transports are closed cleanly via `service.close()`.
  4. ASGI server is notified with `lifespan.shutdown.complete`.

---

## 8. Performance Disclaimer: Warm-Cache vs. Cold-Start Latency

> [!WARNING]
> Road network routing backends (such as OSRM and Valhalla) rely on in-memory Contraction Hierarchies (CH) or Multi-Level Dijkstra (MLD) graph indices.
> - **Cold-Start Phase**: When routing containers or daemons first boot, graph files are paged into memory from disk on demand. During this period (first ~100–500 queries), matrix lookups may exhibit elevated latencies (1.0–3.0s).
> - **Warm-Cache Phase**: Once the road graph is resident in OS page cache, regional matrix throughput reaches sub-5ms per lookup, allowing the dispatch orchestrator to comfortably satisfy the sub-500ms regional SLA.
> - **Operational Recommendation**: Execute synthetic matrix warmup queries (e.g. against bounding box centroids) prior to marking the routing container ready in production.

---

## 9. Multi-Instance Deployment & State Boundaries

### Process-Local vs. Shared State
When scaling horizontally across multiple container instances or worker processes:

1. **Process-Local State (Do Not Share Across Instances)**:
   - `PoolEngineService._dispatch_cache`: In-memory dictionary caching the immediate HTTP response for duplicate idempotency tokens. This cache is strictly process-local.
   - `OsrmRoutingAdapter._cache`: In-memory LRU cache storing road-network leg distances and durations.
   - `InMemoryTelemetry`: Collects metrics within the process memory. In production, use `StructuredLoggerTelemetry` forwarding to an external log aggregator (e.g. Datadog, Vector, CloudWatch, Prometheus).
2. **Shared State & Concurrency Safety**:
   - `PostgresRideStorage`: Acts as the canonical source of truth across all instances.
   - **Concurrency Safety**: Row-level locking (`SELECT ... FOR UPDATE` on vehicles, rides, and requests) and optimistic concurrency control (`version` checks) guarantee that concurrent dispatch runs on different instances cannot double-book seats, corrupt itineraries, or assign the same request twice.
   - **Idempotency Replay**: If a dispatch run is retried on a *different* instance with the same idempotency token, PostgreSQL's `idempotency_records` table prevents duplicate execution and rejects conflicting commits. However, replaying the full API response body across instances requires session stickiness at the ingress load balancer or an external distributed cache.

---

## 10. Production Deployment & Operations Checklist

### A. Edge Ingress & TLS Termination
- [ ] Deploy an edge reverse proxy / ingress controller (Envoy, NGINX, AWS ALB, Cloudflare).
- [ ] Enforce TLS 1.3 with modern cipher suites; configure ALPN for `h2, http/1.1`.
- [ ] Automate certificate renewal via ACME / Let's Encrypt / AWS Certificate Manager.
- [ ] Terminate TLS at the edge and forward sanitized `X-Forwarded-For` and `X-Forwarded-Proto` headers.

### B. Rate Limiting & Denial-of-Service Protection
- [ ] Configure token-bucket or leaky-bucket rate limiting at the ingress layer:
  - **Passenger Requests (`POST /v1/requests`)**: e.g., 50 requests/sec per API key, burst 100.
  - **Fleet Telemetry (`PATCH /v1/vehicles/{id}/location`)**: e.g., 200 requests/sec per driver/vehicle.
  - **Dispatch Solver (`POST /v1/dispatch`)**: e.g., 10 requests/sec (typically triggered by scheduled batch worker).
- [ ] Verify maximum body size is enforced at both ingress (e.g., `client_max_body_size 1m`) and application layer (`max_request_body_bytes = 1048576`).

### C. Secrets Management
- [ ] Inject `DATABASE_URL` and API keys via secure secrets management (HashiCorp Vault, AWS Secrets Manager, Kubernetes Secrets).
- [ ] Verify zero plaintext credentials, passwords, or tokens in source code, repository commits, or Docker images.
- [ ] Ensure `sanitize_sensitive_strings` remains enabled to prevent DSN credentials from appearing in error traces or readiness logs.

### D. PostgreSQL High-Availability & Backups
- [ ] Configure PostgreSQL 14+ in High-Availability mode (Patroni, AWS RDS Multi-AZ, or GCP Cloud SQL HA) with automated leader election.
- [ ] Deploy PgBouncer in transaction pooling mode between application instances and PostgreSQL to prevent connection exhaustion.
- [ ] Enable continuous WAL archiving to cloud object storage (S3/GCS) for Point-In-Time-Recovery (PITR).
- [ ] Schedule daily automated database snapshots and periodically verify backup restoration integrity.

### E. Routing Service Operations (OSRM / Valhalla)
- [ ] Provision sufficient RAM for road graph residency (Manhattan $\approx 200\text{MB}$; Regional State $\approx 4\text{–}8\text{GB}$; Continental $\approx 32\text{–}64\text{GB}$).
- [ ] Implement zero-downtime rolling container updates when updating OpenStreetMap graph data extracts (`osrm-extract` / `osrm-partition` / `osrm-customize`).
- [ ] Run synthetic matrix warmup queries against the routing backend before adding new routing instances to the load balancer pool.

### F. Monitoring, Alerting & SLIs
- [ ] **Dispatch SLA Alert**: Trigger P1 alert if p99 dispatch cycle latency exceeds $500\text{ms}$ over a 5-minute rolling window.
- [ ] **Readiness Probe Alert**: Trigger alert if `/v1/health/readiness` fails for 3 consecutive health checks on any node.
- [ ] **Routing Degradation Alert**: Trigger warning if `routing_errors_count > 5` in any dispatch cycle.
- [ ] **OCC Collision Alert**: Alert if `VERSION_CONFLICT` rejection rate exceeds $5\%$ of total dispatch batch assignments.

### G. Incident Response Runbook
1. **Degraded Routing Backend**:
   - Symptoms: `/v1/health/readiness` reports `"routing": "degraded"`; dispatch cycle durations increase; `routing_errors_count` spikes.
   - Action: Check OSRM container CPU/memory usage; verify network connectivity between ASGI instances and OSRM; scale OSRM replicas.
2. **Database Connection Exhaustion**:
   - Symptoms: Readiness probe returns 503 with `"storage": "unreachable"`; logs indicate `too many clients already`.
   - Action: Inspect PgBouncer client/server connection pools; check `pg_stat_activity` for stalled or long-running transactions; terminate idle connections.
3. **Dispatch Version Conflict Spikes**:
   - Symptoms: Increased `rejected_assignments` with reason `VERSION_CONFLICT`.
   - Action: Check vehicle update frequency; verify dispatch frequency is aligned with vehicle movement updates; ensure single dispatch batch worker is driving spatial partitions.
