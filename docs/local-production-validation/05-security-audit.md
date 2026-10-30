# Stage F — Security Validation & Threat Audit

**Date**: October 30, 2026  
**Security Scope**: API Authentication, Token Verification, Network Isolation, Ingress Defense, and Data Privacy.

---

## 1. Security Controls Verification Matrix

| Security Control | Implementation | Verification Method | Status |
|---|---|---|---|
| **Cryptographic Token Verification** | `FirebaseAuthProvider` in `security.py` | Unit tests verify signature, audience (`waymate-u`), issuer, expiry. | **VERIFIED** |
| **Server-to-Server API Keys** | `ApiKeyAuthProvider` in `security.py` | Evaluates `X-API-Key` or `Authorization: Bearer` against hashed role registry. | **VERIFIED** |
| **Production Fail-Fast Guard** | `build_auth_provider_from_env()` | Raises `ValueError` at startup if auth unconfigured in staging/prod. | **VERIFIED** |
| **Dev Credentials Exclusion** | `security.py` line 393 | Fallback key (`waymate-dev-secret-key-2026`) strictly blocked outside development. | **VERIFIED** |
| **Internal Port Isolation** | `docker-compose.production.yml` | PostgreSQL (5432) and OSRM (5000) have **no public host port mappings**. | **VERIFIED** |
| **CORS Ingress Restrictions** | `config.py` lines 162–174 | Wildcards (`*`) forbidden with auth; strictly restricted to `waymate-u` domains. | **VERIFIED** |
| **Rate Limiting & DoS Shield** | Reverse Proxy (Nginx/Caddy) | Capped at 30 req/s per IP with burst 20 (`limit_req_zone`). | **VERIFIED** |
| **Request Payload Size Cap** | ASGI Middleware + Nginx | 1 MB hard limit (`MAX_REQUEST_BODY_BYTES=1048576`); rejects larger with 413. | **VERIFIED** |
| **Telemetry & Log Sanitization**| `sanitize_sensitive_strings()` | Obfuscates passenger coordinates and strips passwords from connection strings. | **VERIFIED** |
| **Zero Secrets in Frontend** | Static asset audit of `dist/assets/` | Regex search for dev secrets, testing keys, and private passwords yields 0 hits. | **VERIFIED** |

---

## 2. Authentication Deep-Dive

### 1. Firebase ID Token Cryptographic Verification
[`src/engine/service/security.py`](file:///c:/Users/shaha/pool%20engine/src/engine/service/security.py#L104-L236) implements strict cryptographic validation:
1. **Audience Check**: Validates `aud == FIREBASE_PROJECT_ID` (`waymate-u`).
2. **Issuer Check**: Validates `iss == https://securetoken.google.com/waymate-u`.
3. **Signature Check**: Verified against Google's public x509 certs.
4. **Subject Check**: Extracts authenticated `uid` as caller subject ID.
5. **Role Check**: Roles (`admin`, `dispatch_operator`) are extracted strictly from server-signed custom claims, never from user-supplied request headers.

### 2. Startup Fail-Fast Verification (`test_security_and_capacity_hardening.py`)
```python
def test_production_environment_fails_fast_without_auth_provider():
    # If ENVIRONMENT=production and no FIREBASE_PROJECT_ID or API_KEYS are set:
    with pytest.raises(ValueError, match="Production environment requires a configured authentication provider"):
        build_auth_provider_from_env(env={"ENVIRONMENT": "production"})
```
- **Observed Behavior**: The application refuses to boot if security credentials are not explicitly supplied in production.

---

## 3. Network Isolation Architecture

```text
External Internet
      |
      X (Port 5432 Blocked - No Public Exposure)
      X (Port 5000/5001 Blocked - No Public Exposure)
      X (Port 8000 Blocked - Loopback Only)
      |
      v (Ports 80/443 Only)
Reverse Proxy (Nginx / Caddy)
      |
      | 127.0.0.1:8000
      v
Pool Engine ASGI Service
      |
      +----[Internal Bridge Network]----> Kerala OSRM (:5000)
      +----[Internal Bridge Network]----> PostgreSQL 16 (:5432)
```

- **UFW Firewall Rule**: Default deny incoming; allow 22 (SSH), 80 (HTTP), 443 (HTTPS).
- All internal services communicate over the isolated Docker bridge network `poolengine-prod-net`.

---

## 4. Privacy & Telemetry Protections (DPDPA 2023 Compliance)

1. **Geospatial Coordinate Truncation**:
   - `mask_coordinates_in_logs=true`: Raw latitude/longitude values logged during route snapping are masked (`lat: 8.5***, lon: 76.9***`) to prevent passenger telemetry tracking from server logs.
2. **Credential Redaction**:
   - `sanitize_sensitive_strings`: Automatically scans database connection strings and redacts passwords (`postgresql://pool_prod_user:***@host/db`).
3. **No PII In Dispatch Records**:
   - The Pool Engine processes canonical IDs (`rider_id`, `request_id`, `vehicle_id`) and spatial coordinates. Passenger names, phone numbers, and payment details are never passed to or stored by the DARP solver.
