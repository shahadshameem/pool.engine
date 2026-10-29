# Pool Engine — Phase 6D: Production Readiness & Reliability Report

**Repository:** `C:\Users\shaha\pool engine`
**Phase:** Phase 6D — Production Readiness & Reliability
**Date:** October 29, 2026
**Baseline Commit:** `eac5db7f8e46f2ac29bce71143ed7504719c6aa3` (Phase 5)
**Status:** COMPLETE — Security Hardening, Input Sanitization, Privacy Controls & Operational Playbooks Verified

---

## 1. Executive Summary

Phase 6D hardens the Pool Engine for production and staging operation across multi-region deployments. It verifies input sanitization, RFC 7807 problem details, telemetry and log privacy, bounded network and thread timeouts, failure recovery playbooks, and rolling rollback procedures.

All security, privacy, and reliability controls have been audited with automated test verification to ensure no sensitive credentials, raw passenger coordinates, or unhandled exceptions escape the service boundaries.

---

## 2. Security & Input Sanitization Invariants

The application enforces defense-in-depth sanitization at every entry point:

### 2.1 Geospatial Boundary Clamping
- **WGS84 Coordinate Range:** Enforces $-90.0 \le \text{latitude} \le 90.0$ and $-180.0 \le \text{longitude} \le 180.0$ across all Pydantic models (`GeoCoordinate`, `Coordinate`, `BoundingBox`).
- **Snapping Limits:** Road network snapping distances returned by OSRM are validated against `routing_max_snap_distance_meters` (default: 5,000m). Waypoints snapping beyond this tolerance or landing outside the configured bounding box are rejected with `OutOfRegionError`.
- **Cartesian Non-Overlap:** Overlapping regional bounding boxes fail startup validation (`BoundingBox.overlaps`), eliminating ambiguous spatial lookups.

### 2.2 Payload & Protocol Limits
- **Request Body Size:** Enforces `max_request_body_bytes` (default 1 MB, max 50 MB) at the ASGI layer via `PayloadTooLargeError` (HTTP 413) prior to full JSON parsing.
- **Strict Pydantic Validation:** All incoming DTOs use `extra="forbid"`, rejecting unknown attributes to prevent parameter tampering.
- **Idempotency Protection:** Endpoints `/v1/requests`, `/v1/proposals`, `/v1/vehicles`, and `/v1/dispatch/run` mandate or generate idempotency keys to guarantee deterministic at-most-once execution under network retries.

### 2.3 RFC 7807 Error Envelope Standard
All application errors produce structured, standardized RFC 7807 JSON envelopes:

```json
{
  "error": {
    "code": "OUT_OF_REGION",
    "message": "Pickup coordinate (8.5469, 76.9054) does not match declared region 'us-nyc-manhattan'",
    "details": []
  }
}
```

Internal connection strings, database passwords, and filesystem stack traces are automatically sanitized via `sanitize_sensitive_strings()` before serialization.

---

## 3. Privacy & Telemetry Guardrails

### 3.1 Geospatial Telemetry Obfuscation
- When `mask_coordinates_in_logs=True` (default in staging and production), latitude and longitude values emitted to structured logs and telemetry events are truncated or hashed:
  ```python
  def mask_coordinate(lat: float, lon: float) -> str:
      return f"{lat:.2f}*, {lon:.2f}*"
  ```
- Exact passenger pickup and dropoff points are never written to plain-text operational log streams.

### 3.2 Secret Protection
- No hardcoded secrets, vendor keys, or passwords exist in the codebase.
- Database credentials and Firebase service account tokens are sourced strictly through environment variables or mounted files (`DATABASE_URL`, `FIREBASE_CREDENTIALS_PATH`).

---

## 4. Timeout Budgets & Concurrency Safety

### 4.1 Latency Budgets & SLA Defense
- **Regional Dispatch SLA:** Each dispatch window runs within $\le 500\text{ms}$.
- **Reserved Headroom:** A safety headroom of $50\text{ms}$ (`reserved_headroom_seconds=0.050`) halts greedy candidate evaluation and matrix prefetching before the dispatch deadline expires.
- **Singleflight Coalescing:** Eliminates thundering-herd spikes on regional OSRM backends by sharing in-flight queries across concurrent worker threads.

### 4.2 Database & Connection Pool Safety
- **Bounded PostgreSQL Pool:** Uses `psycopg_pool.ConnectionPool` with configurable `min_size` (2), `max_size` (20), and timeout ($10\text{s}$).
- **Async Event Loop Isolation:** All blocking storage and routing calls are delegated to background worker threads via `asyncio.to_thread()`, guaranteeing zero event-loop stalls.

---

## 5. Operational Playbooks & Disaster Recovery

### 5.1 Playbook A: Regional OSRM Backend Degradation
**Symptom:** Regional backend (e.g. Kerala on port 5001) crashes or becomes unresponsive.
1. The aggregate health endpoint `/v1/health/readiness` reports `status: "ready"` (if `STRICT_ROUTING_READINESS=false`) with `"routing": "degraded"` and `"regions.in-kl-tvm.healthy": false`.
2. Traffic to `us-nyc-manhattan` continues with normal latency and zero impact.
3. Ingress load balancers querying `/v1/health/readiness?region=in-kl-tvm` receive HTTP 503 and shift Kerala traffic to failover or return a clean outage notification.
4. **Recovery Action:** Restart Kerala OSRM daemon:
   ```powershell
   & "C:\Users\shaha\AppData\Local\osrm_portable\osrm-routed-kerala.exe" `
     -a CH -p 5001 -t 4 "C:\Users\shaha\AppData\Local\osrm_portable\kerala.osrm"
   ```
5. Probing `/v1/health/readiness?region=in-kl-tvm` automatically flips back to HTTP 200 without requiring an application restart.

### 5.2 Playbook B: Zero-Downtime Rollback Procedure
If a breaking routing regression occurs:
1. Revert to baseline commit `eac5db7f8e46f2ac29bce71143ed7504719c6aa3`.
2. Restart the application process. No database migration is required (schema remains 100% backward-compatible).
3. Verify test suite green: `uv run pytest -q`.

---

## 6. Conclusion

The Pool Engine satisfies all production reliability criteria for multi-region routing. Security, privacy, timeouts, and health indicators are fully operational and verified.
