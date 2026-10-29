# Pool Engine — Phase 10E: Production API Deployment & Authentication Architecture

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 10E — API & Authentication  
**Date:** October 29, 2026  
**Auditor:** Senior Security Architect / Backend Lead (Pair-Programming Agent)  
**Status:** COMPLETE & DOCUMENTED  

---

## 1. Executive Summary

This document specifies the production configuration, process management, identity verification, role-based authorization, and request lifecycle boundaries for the Pool Engine API container on the Contabo Linux VPS.

In production mode (`ENVIRONMENT=production`), the API activates strict defensive security policies: `NoOpAuthProvider` is prohibited, request body sizes are strictly capped at 1 MB, end-user identity is cryptographically validated via Firebase Auth ID tokens, and administrative dispatch operations require explicit operator roles.

---

## 2. Process Manager & Concurrency Architecture

### 2.1 Multi-Worker Uvicorn Execution
In `deploy/docker/docker-compose.production.yml`:
```yaml
command: ["uvicorn", "engine.service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```
- **Concurrency Scaling:** 4 worker processes run concurrently under Uvicorn's master process on Linux, mapping directly to the 4 vCPUs of the Contabo VPS.
- **Resource Utilization:** Each worker process uses ~60–75 MB RSS, yielding a total API footprint of ~250–300 MB RAM—well within the 2.0 GiB container limit.
- **Graceful Lifecycle:** Docker delivers `SIGTERM` on container stop. The master process forwards signals to workers, granting up to `SHUTDOWN_TIMEOUT_SECONDS=5.0` to finish in-flight requests and close connection pools before termination.

---

## 3. Cryptographic Authentication & Role-Based Access Control

### 3.1 Firebase ID Token Verification (`FirebaseAuthProvider`)
- **Library:** Google `firebase-admin` SDK.
- **Mechanism:**
  1. Extracts `Authorization: Bearer <token>` from HTTP request headers.
  2. Verifies cryptographic signature using Google's public key certificates.
  3. Verifies token expiration (`exp`) and not-before (`nbf`) claims.
  4. Enforces project ID matching:
     ```python
     if aud != self._project_id and tenant != self._project_id:
         logger.warning("Token audience '%s' does not match '%s'", aud, self._project_id)
         return AuthContext(authenticated=False)
     ```
  5. Enforces issuer matching: `https://securetoken.google.com/<project_id>`.
  6. Extracts authenticated user ID (`uid`) and server-set custom claims (`admin`, `dispatch_operator`).

### 3.2 Production Guardrail Fail-Closed Policy
In `src/engine/service/security.py`:
```python
if is_prod and not allow_unauth:
    raise ValueError(
        "Production environment requires a configured authentication provider (Firebase or API keys). "
        "NoOpAuthProvider is prohibited in production unless allow_unauthenticated_in_production=True."
    )
```
If `ENVIRONMENT=production` is launched without `FIREBASE_PROJECT_ID` or `API_KEYS`, the API server aborts startup immediately with a descriptive exception, preventing accidental unauthenticated operation.

### 3.3 Authorization Enforcement Matrix

| API Action / Endpoint | Permitted Roles / Identifiers | Enforced Rule |
| :--- | :--- | :--- |
| `POST /v1/requests` (Create Ride Request) | Authenticated `rider` or `admin` | Non-admin riders cannot submit requests for other user IDs (`user_id == subject_id`). |
| `GET /v1/requests/{id}` | Request Owner or `admin` | Riders can view only their own active or pending ride requests. |
| `POST /v1/host-rides` | Authenticated `driver` or `admin` | Drivers can publish routes for their registered vehicle. |
| `POST /v1/dispatch` | `dispatch_operator` or `admin` | End users cannot trigger automated batch dispatch solving. |
| `GET /v1/health/liveness` | Public | Unauthenticated probe reporting process responsiveness. |
| `GET /v1/health/readiness` | Public | Probes PostgreSQL connectivity and OSRM Kerala routing health. |

---

## 4. Input Validation & Request-Size Limits

- **Maximum Request Body:** 1,048,576 bytes (1 MB default). Requests with `Content-Length > 1 MB` are rejected immediately with HTTP 413 `PayloadTooLargeError`.
- **Coordinate Boundaries:** Coordinates must strictly satisfy `-90 <= lat <= 90` and `-180 <= lon <= 180`. Non-numeric or non-finite coordinates are rejected with HTTP 400.
- **Regional Containment:** Coordinates outside the Kerala pilot bounding box (`[8.18, 76.80, 8.65, 77.05]`) are rejected with HTTP 400 (`OUT_OF_REGION`).
- **Pydantic Model Validation:** Extra fields are strictly prohibited (`extra="forbid"`), preventing JSON parameter injection.
