# WayMate Pool Engine — Production VPS Deployment Guide

This guide covers deploying and operating the WayMate Pool Engine on any Linux Virtual Private Server (VPS) running Ubuntu 22.04 or 24.04 LTS (such as Contabo, DigitalOcean, Hetzner, Linode, or AWS EC2).

---

## Architecture Overview

```
                                      [ Internet / Client Requests ]
                                                    │
                                                    ▼
                                          [ Port 80 / 443 HTTPS ]
                                           Caddy Reverse Proxy
                                     (Automatic Let's Encrypt TLS)
                                                    │
                                                    ▼
                                          [ 127.0.0.1:8000 ]
                              ┌───────────────────────────────────────────┐
                              │            Docker Bridge Network          │
                              │ ┌───────────────────────────────────────┐ │
                              │ │ pool-engine-api (4 Uvicorn Workers)   │ │
                              │ └───────────────────┬───────────────────┘ │
                              │                     │                     │
                              │        ┌────────────┴───────────┐         │
                              │        ▼                        ▼         │
                              │ ┌──────────────┐       ┌────────────────┐ │
                              │ │ postgres-prod│       │  osrm-kerala   │ │
                              │ │ (Port 5432)  │       │  (Port 5000)   │ │
                              │ └──────────────┘       └────────────────┘ │
                              └───────────────────────────────────────────┘
```

---

## 1. Quick Start (Turnkey 1-Command Setup)

On a fresh Ubuntu VPS:

```bash
# 1. Clone repository
git clone https://github.com/shahadshameem/pool.engine.git
cd pool.engine

# 2. Run automated setup script as root
sudo bash deploy/vps/setup_vps.sh
```

The script automatically:
1. Installs Docker Engine and Docker Compose Plugin.
2. Configures the UFW firewall (opening ports 22, 80, and 443).
3. Generates a secure, cryptographically random `.env.production` configuration.
4. Prepares the Kerala OSRM road graph.
5. Installs and configures Caddy for automatic HTTPS.
6. Launches PostgreSQL 16, Kerala OSRM, and the 4-worker FastAPI Pool Engine.
7. Validates health check endpoints (`/v1/health/liveness` and `/v1/health/readiness`).

---

## 2. DNS Configuration

In your DNS provider (Cloudflare, Namecheap, GoDaddy, Route53):

| Type | Host | Value | TTL |
|---|---|---|---|
| `A` | `api-pool` | `<YOUR_VPS_IP>` | Auto / 300 |

Once DNS propagates, Caddy will automatically issue a valid SSL/TLS certificate for `api-pool.waymate.in`.

---

## 3. Maintenance & Operations

### View Live Logs
```bash
# All services
docker compose -f deploy/docker/docker-compose.production.yml logs -f

# Only API service
docker compose -f deploy/docker/docker-compose.production.yml logs -f pool-engine-api

# OSRM router
docker compose -f deploy/docker/docker-compose.production.yml logs -f osrm-kerala
```

### Restart Services
```bash
docker compose -f deploy/docker/docker-compose.production.yml restart
```

### Fast Updates (Zero Downtime)
```bash
sudo bash deploy/vps/update_vps.sh
```

### Backup Database
```bash
sudo bash scripts/backup_production_db.sh
```
Backups are saved to `/var/backups/pool_engine/` and automatically retained for 14 days.

### Restore Database
```bash
sudo bash scripts/restore_production_db.sh /var/backups/pool_engine/pool_engine_prod_YYYYMMDD_HHMMSS.dump
```

---

## 4. Frontend Integration

In the WayMate frontend repository (`.env.production`):

```env
VITE_POOL_ENGINE_URL=https://api-pool.waymate.in
VITE_POOL_ENGINE_REGION=in-kl-tvm
```
