# Stage B — Local Environment Setup & Operation Guide

**Guide Purpose**: Step-by-step instructions for launching, operating, verifying, and stopping the local WayMate and Pool Engine testing environment.

---

## 1. Local Architecture Overview

Because Docker Desktop is not installed on this local Windows developer machine, the local validation harness uses native Windows background daemons:

```
[Port 5173] WayMate Vite Frontend (Node.js 24)
     |
     v
[Port 8000] Pool Engine API Server (Python 3.13 / ASGI)
     |
     +---> [Port 5001] Kerala OSRM Daemon (osrm-routed-kerala.exe)
     +---> [Port 5000] Manhattan OSRM Daemon (osrm-routed.exe)
     +---> [Port 5433] Portable PostgreSQL 16 (postgres.exe)
```

---

## 2. Exact Commands to Start the Local Environment

### Step 1: Start PostgreSQL (Port 5433)
```powershell
& "C:\Users\shaha\AppData\Local\pg_portable\pgsql\bin\postgres.exe" `
    -D "C:\Users\shaha\AppData\Local\pg_portable\data" `
    -p 5433
```
*Verification*:
```powershell
& "C:\Users\shaha\AppData\Local\pg_portable\pgsql\bin\pg_isready.exe" -p 5433 -h 127.0.0.1
# Expected Output: 127.0.0.1:5433 - accepting connections
```

### Step 2: Start Kerala OSRM Routing Engine (Port 5001)
```powershell
& "C:\Users\shaha\AppData\Local\osrm_portable\osrm-routed-kerala.exe" `
    -a CH -p 5001 -t 4 `
    "C:\Users\shaha\AppData\Local\osrm_portable\kerala.osrm"
```
*Verification*:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:5001/route/v1/driving/76.9063,8.5456;76.9535,8.4878?overview=false"
# Expected Output: {"code": "Ok", "routes": [{"distance": 11193, "duration": 974.1, ...}]}
```

### Step 3: Start Manhattan OSRM Routing Engine (Port 5000)
```powershell
& "C:\Users\shaha\AppData\Local\osrm_portable\osrm-v26.10.0-win32-x64-Release\osrm-routed.exe" `
    -a CH -p 5000 -t 8 `
    "C:\Users\shaha\AppData\Local\osrm_portable\manhattan.osrm"
```

### Step 4: Start Pool Engine Staging API (Port 8000)
```powershell
Set-Location "C:\Users\shaha\pool engine"
uv run python scripts/run_staging_server.py --port 8000
```
*Verification*:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/health/readiness" | ConvertTo-Json
# Expected Output: {"ready": true, "status": "ready", "components": {"storage": "healthy", "routing": "healthy"}}
```

### Step 5: Start WayMate Frontend Development Server (Port 5173)
```powershell
Set-Location "C:\Users\shaha\git web\waymate"
npm run dev -- --host 0.0.0.0 --port 5173
```
*Access URL*: `http://localhost:5173`

---

## 3. Exact Commands to Stop the Local Environment

### Stopping Native Background Tasks:
To gracefully terminate any running background tasks:
```powershell
# Stop Pool Engine API
Stop-Process -Name python -ErrorAction SilentlyContinue

# Stop OSRM Daemons
Stop-Process -Name osrm-routed, osrm-routed-kerala -ErrorAction SilentlyContinue

# Stop PostgreSQL
& "C:\Users\shaha\AppData\Local\pg_portable\pgsql\bin\pg_ctl.exe" -D "C:\Users\shaha\AppData\Local\pg_portable\data" stop -m fast

# Stop WayMate Vite Server
Stop-Process -Name node -ErrorAction SilentlyContinue
```

---

## 4. Docker Compose Setup (For Linux VPS Migration)

When migrating to a Linux VPS with Docker installed, the identical topology runs as a unified multi-container stack:

```bash
# 1. Place Kerala graph in osrm-data
mkdir -p deploy/docker/osrm-data/kerala
cp /path/to/kerala.osrm* deploy/docker/osrm-data/kerala/

# 2. Configure Environment
cp .env.production.example .env.production
chmod 600 .env.production

# 3. Launch Stack
docker compose --env-file .env.production -f deploy/docker/docker-compose.production.yml up -d --build

# 4. Verify Health
curl -f http://127.0.0.1:8000/v1/health/readiness
```
