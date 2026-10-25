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
| `MASK_COORDINATES_IN_LOGS` | boolean | `true` | When `true`, coarsens lat/lon to 2 decimal places (~1.1 km) in logs and telemetry. |
| `ENVIRONMENT` | string | `production` | Deployment environment name (`production`, `staging`, `test`). |
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
- **Purpose**: Verifies end-to-end connectivity to essential dependencies (PostgreSQL storage and road-network router) before traffic is routed to the instance.
- **Probe Interval**: Every 5-15 seconds.
- **Response when Ready**: `200 OK`:
  ```json
  {
    "ready": true,
    "status": "ready",
    "components": {
      "storage": "healthy",
      "routing": "configured"
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
      "routing": "configured",
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
2. **Payload Protection**:
   - Payloads exceeding `MAX_REQUEST_BODY_BYTES` (default 1 MB) are rejected with `413 Payload Too Large` immediately upon reading the `Content-Length` header or streaming chunks.
3. **Internal Error Sanitization**:
   - Unhandled exceptions return generic `500 Internal Server Error` envelopes (`"An unexpected internal error occurred."`).
   - Detailed stack traces and DSNs are sanitized and logged to internal logging sinks only.

---

## 6. Observability & Telemetry

The service integrates an `EngineTelemetryProvider` to monitor operations and dispatch health:

- **Dispatch Cycle Metrics**: Duration (ms), search status (`OPTIMAL`, `FEASIBLE`, `TIMEOUT`), committed assignments, rejected assignments, unassigned requests, routing error count, and estimated VMT savings.
- **Concurrency Conflicts**: Optimistic lock collisions and retry events.
- **Idempotency Replays**: Tracked for duplicate request submissions and dispatch runs.
- **Privacy Enforcement**: Coordinates are masked using `mask_coordinate(lat, lon, precision=2)` (~1.1 km accuracy) before logging to satisfy location privacy requirements (Constitution Principle VIII).

---

## 7. Graceful Shutdown

The application implements the ASGI Lifespan protocol:
- On `lifespan.startup`, internal connections and thread pools are established.
- On `lifespan.shutdown` (triggered by `SIGTERM` or `SIGINT`), active HTTP handlers and open transactions are permitted to complete cleanly before the server terminates.

---

## 8. Performance Disclaimer: Warm-Cache vs. Cold-Start Latency

> [!WARNING]
> Road network routing backends (such as OSRM and Valhalla) rely on in-memory Contraction Hierarchies (CH) or Multi-Level Dijkstra (MLD) graph indices.
> - **Cold-Start Phase**: When routing containers or daemons first boot, graph files are paged into memory from disk on demand. During this period (first ~100–500 queries), matrix lookups may exhibit elevated latencies (1.0–3.0s).
> - **Warm-Cache Phase**: Once the road graph is resident in OS page cache, regional matrix throughput reaches sub-5ms per lookup, allowing the dispatch orchestrator to comfortably satisfy the sub-500ms regional SLA.
> - **Operational Recommendation**: Execute synthetic matrix warmup queries (e.g. against bounding box centroids) prior to marking the routing container ready in production.
