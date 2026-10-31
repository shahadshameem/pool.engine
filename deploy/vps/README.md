# WayMate Monorepo — Production VPS Deployment Guide

This guide covers deploying and operating the complete **WayMate Monorepo** (WayMate React 19 Frontend + High-Performance Python Pool Engine Backend) on any Linux Virtual Private Server (VPS) running Ubuntu 22.04 or 24.04 LTS (e.g. Contabo, DigitalOcean, Hetzner, Linode, AWS EC2).

---

## Architecture Overview

```
                                      [ Internet / Browser & App Requests ]
                                                    │
                                                    ▼
                                          [ Port 80 / 443 HTTPS ]
                                           Caddy Reverse Proxy
                                     (Automatic Let's Encrypt TLS)
                                                    │
                         ┌──────────────────────────┴──────────────────────────┐
                         │                                                     │
                   [ waymate.in ]                                    [ api-pool.waymate.in ]
                         │                                                     │
                         ▼                                                     ▼
                 [ 127.0.0.1:3000 ]                                    [ 127.0.0.1:8000 ]
             ┌───────────────────────┐                             ┌───────────────────────┐
             │ waymate-prod-frontend │                             │  pool-engine-prod-api │
             │ (React SPA on Nginx)  │                             │  (4 Uvicorn Workers)  │
             └───────────────────────┘                             └───────────┬───────────┘
                                                                               │
                                                                   ┌───────────┴───────────┐
                                                                   ▼                       ▼
                                                            ┌──────────────┐       ┌────────────────┐
                                                            │ postgres-prod│       │  osrm-kerala   │
                                                            │ (Port 5432)  │       │  (Port 5000)   │
                                                            └──────────────┘       └────────────────┘
```

---

## 1. Quick Start (Turnkey 1-Command Setup)

On a fresh Ubuntu VPS:

```bash
# 1. Clone monorepo
git clone https://github.com/shahadshameem/pool.engine.git
cd pool.engine

# 2. Run automated setup script as root
sudo bash deploy/vps/setup_vps.sh
```

The setup script automatically:
1. Installs Docker Engine and Docker Compose Plugin.
2. Configures the UFW firewall (opening ports 22, 80, and 443).
3. Generates a secure, cryptographically random `.env.production` configuration.
4. Prepares and compiles the Kerala OSRM road graph.
5. Installs and configures Caddy for automatic HTTPS and TLS termination.
6. Builds and launches:
   - **WayMate Frontend**: React 19 + Vite SPA served via Nginx on `127.0.0.1:3000`.
   - **Pool Engine API**: High-throughput FastAPI ASGI service on `127.0.0.1:8000`.
   - **PostgreSQL 16**: Production database with connection pooling and automated schema.
   - **Kerala OSRM**: Contraction Hierarchies road router.
7. Validates health check endpoints (`/` on frontend and `/v1/health/liveness` on API).

---

## 2. DNS Configuration

Point your domain DNS `A` records to your VPS public IPv4 address:

| Host / Subdomain | Target IP | Destination Service |
| :--- | :--- | :--- |
| `waymate.in` | `<YOUR_VPS_IP>` | WayMate Frontend Web Client |
| `www.waymate.in` | `<YOUR_VPS_IP>` | WayMate Frontend Web Client |
| `api-pool.waymate.in` | `<YOUR_VPS_IP>` | Pool Engine ASGI Service |

Caddy handles automatic SSL/TLS certificate issuing and renewals with Let's Encrypt / ZeroSSL without manual certbot intervention.

---

## 3. Routine Updates (Zero Downtime)

To deploy new commits pushed to GitHub:

```bash
sudo bash deploy/vps/update_vps.sh
```

This pulls the latest commits, rebuilds both the frontend and backend containers, and verifies service readiness.

---

## 4. Useful Operations Commands

```bash
# View live container logs
docker compose -f deploy/docker/docker-compose.production.yml logs -f

# Check container status
docker compose -f deploy/docker/docker-compose.production.yml ps

# Restart services
docker compose -f deploy/docker/docker-compose.production.yml restart

# Manual database backup
sudo bash backend/scripts/backup_production_db.sh
```
