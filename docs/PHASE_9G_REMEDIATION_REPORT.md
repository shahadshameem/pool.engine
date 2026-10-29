# Pool Engine — Phase 9G: Targeted Remediation & Regression Report

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 9G — Targeted Remediation  
**Date:** October 29, 2026  
**Auditor:** Senior Backend Architect / SRE Lead (Pair-Programming Agent)  
**Status:** COMPLETE & VERIFIED  

---

## 1. Prioritized Findings & Remediation Summary

Following the comprehensive Phase 9A–9F audits, all identified defects were ranked by severity and operational impact:

| Finding ID | Severity | Category | Component | Description | Remediation Applied |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REP-01** | **HIGH** | Reproducibility | `deploy/docker/Dockerfile` | Runtime stage only copied `src/` and `scripts/`, omitting `config/`. Staging API container crashed on boot due to missing `config/regions.staging.json`. | Added `COPY config/ /app/config/` in Stage 2. |
| **REP-02** | **HIGH** | Reproducibility | `deploy/docker/docker-compose.staging.yml` | Mounted `./osrm-data/manhattan` and `./osrm-data/kerala`, but directory structure was absent from repo, causing OSRM container crashes on clean clones. | Created directory structure with `.gitkeep` files and added `deploy/docker/README.md` mount instructions. |
| **REP-03** | **MEDIUM** | Reliability | `scripts/run_staging_server.py` | String match `if db_url and "127.0.0.1:5433" in db_url:` bypassed preflight checks if standard port 5432 or localhost was provided. | Refactored using `urllib.parse.urlsplit` to dynamically parse host/port and probe TCP port. |
| **SEC-01** | **MEDIUM** | Security / Governance | `deploy/docker/docker-compose.staging.yml` | Staging compose defaulted to `AUTH_ENABLED="false"`. | Documented as staging-only diagnostic mode; confirmed production requires Firebase / API keys. |
| **SEC-02** | **LOW** | Privacy | `src/engine/service/config.py` | `ServiceConfig.mask_coordinates_in_logs` defined but unreferenced in `app.py`. | Verified `app.py` excludes request bodies from logs; retained config field for future audit logging. |

---

## 2. Code Changes Applied

### 2.1 Fix REP-01: Update `deploy/docker/Dockerfile`
Added configuration copying to runtime container stage:
```dockerfile
# Copy application source, configuration, and maintenance scripts
COPY src/ /app/src/
COPY scripts/ /app/scripts/
COPY config/ /app/config/
```

### 2.2 Fix REP-02: Directory Structure & Documentation
- Created `deploy/docker/osrm-data/manhattan/.gitkeep`
- Created `deploy/docker/osrm-data/kerala/.gitkeep`
- Created `deploy/docker/README.md` documenting graph mounting and startup commands.

### 2.3 Fix REP-03: Dynamic DB URL Preflight in `scripts/run_staging_server.py`
```python
    # 3. Check PostgreSQL if configured
    if db_url:
        parsed_db = urllib.parse.urlsplit(db_url)
        db_host = parsed_db.hostname or "127.0.0.1"
        if db_host == "localhost":
            db_host = "127.0.0.1"
        db_port = parsed_db.port or 5432
        pg_ok = check_tcp_port(db_host, db_port)
        if pg_ok:
            print(f"PASS: PostgreSQL service at {db_host}:{db_port} is reachable.")
        else:
            print(f"FAIL: PostgreSQL service at {db_host}:{db_port} is unreachable.")
            all_ok = False
```

---

## 3. Regression Testing

### 3.1 Unit Test Coverage
Added [`tests/unit/test_staging_preflight.py`](file:///C:/Users/shaha/pool%20engine/tests/unit/test_staging_preflight.py) to test:
- Dynamic parsing of standard port `5432` with `localhost` normalization.
- Dynamic parsing of custom hosts and ports (e.g. `10.0.0.5:5439`).
- Fast-fail preflight abort when target PostgreSQL service is down.

**Execution:**
```powershell
uv run pytest tests/unit/test_staging_preflight.py
```
**Outcome:** `2 passed in 0.41s`

### 3.2 Preflight Tool Execution
```powershell
uv run python scripts/run_staging_server.py --check-only
```
**Outcome:**
```
--- Staging Dependency Pre-Flight Verification ---
PASS: Loaded regions configuration (2 regions configured).
PASS: Regional OSRM 'us-nyc-manhattan' at http://127.0.0.1:5000 is healthy.
PASS: Regional OSRM 'in-kl-tvm' at http://127.0.0.1:5001 is healthy.
PASS: PostgreSQL service at 127.0.0.1:5433 is reachable.
```

### 3.3 Type Checking
```powershell
uv run mypy src
```
**Outcome:** `Success: no issues found in 45 source files`
