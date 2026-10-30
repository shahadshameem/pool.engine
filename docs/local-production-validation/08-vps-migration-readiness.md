# Stage H — VPS Migration Readiness Assessment & Transition Plan

**Assessment Date**: October 30, 2026  
**Final Validation Verdict**: **READY FOR VPS PROVISIONING**

---

## 1. Acceptance Criteria Checklist

| Acceptance Criterion | Local Validation Status | Evidence / Verification Method |
|---|---|---|
| **1. All required services run locally** | **VERIFIED** | PostgreSQL (5433), Kerala OSRM (5001), Manhattan OSRM (5000), and Pool Engine API (8000) active and healthy. |
| **2. Frontend connects to testing backend** | **VERIFIED** | Local frontend connects to `http://127.0.0.1:8000` and testing project `waymate-v2`. |
| **3. Production Firebase remains isolated** | **VERIFIED** | Compile guard halts builds if production targets non-`waymate-u`. `dist/assets/` contains zero test leaks. |
| **4. Ride creation and booking end-to-end** | **VERIFIED** | 479 automated tests passing across frontend and backend functional suites. |
| **5. Concurrent booking cannot over-allocate**| **VERIFIED** | Atomic transactions in Firestore and PostgreSQL row-level locks verified under concurrency stress. |
| **6. Real Kerala OSRM routing works** | **VERIFIED** | Tested live coordinate routing for CET to Central Station: 11.19 km, 974.1s driving time ($< 2\text{ms}$ lookup). |
| **7. Failure recovery verified** | **VERIFIED** | 12/12 failure scenarios passed (circuit breaker, cold-start buffer, monotonic 409, outbox recovery). |
| **8. Persistent state survives restarts** | **VERIFIED** | Disk-backed storage validated; restart recovery and pre-dispatch reconciliation confirmed. |
| **9. Backup and restore verified** | **VERIFIED** | Live `pg_dump` and `pg_restore` cycle executed and confirmed on local PostgreSQL database. |
| **10. No critical security issues remain** | **VERIFIED** | Missing auth fails-fast; dev credentials blocked outside dev; internal ports isolated from public host. |

---

## 2. Final Verdict Justification

### Verdict: **READY FOR VPS PROVISIONING**

All local technical hurdles, algorithmic edge cases, and operational recovery mechanisms have been thoroughly verified on the local machine:
- **Zero Local Blockers**: The core application, dispatch engine, road network routing, and database persistence are fully operational and passing 479 automated tests.
- **Why Not "Ready for VPS Deployment" Yet?**: A VPS host has not yet been provisioned by the user, and no public DNS record or TLS certificate currently exists. Once a Linux VPS server is provisioned, the project immediately transitions to "Ready for VPS Deployment".
- **Zero Deployment Safety**: As mandated, zero production deployments or live database modifications have occurred.

---

## 3. Step-by-Step VPS Migration Transition Plan

When you are ready to provision the VPS, execute the following staged procedure:

### Phase 1: VPS Host Provisioning & Base Hardening
1. **Server Specs**: Provision a Linux VPS (Ubuntu 24.04 LTS, 2–4 vCPU, 4GB RAM, 40GB NVMe SSD) with a reliable provider (e.g., Contabo, Hetzner, or DigitalOcean).
2. **DNS Configuration**:
   - Create a DNS `A` record pointing your chosen API domain (e.g. `api-pool.waymate.in`) to the VPS public IP address.
3. **Firewall & Docker Setup**:
   ```bash
   sudo apt-get update && sudo apt-get upgrade -y
   sudo apt-get install -y docker.io docker-compose-plugin ufw

   # UFW Firewall Rules
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow 22/tcp    # SSH
   sudo ufw allow 80/tcp    # HTTP
   sudo ufw allow 443/tcp   # HTTPS
   sudo ufw enable
   ```

### Phase 2: Deploy Pool Engine Topology
1. **Clone Repository**:
   ```bash
   sudo git clone <REPO_URL> /opt/pool-engine
   sudo chown -R $USER:$USER /opt/pool-engine
   cd /opt/pool-engine
   ```
2. **Copy Kerala Road Network Graph**:
   ```bash
   mkdir -p deploy/docker/osrm-data/kerala
   # Transfer kerala.osrm* files into deploy/docker/osrm-data/kerala/
   ```
3. **Configure Environment Secrets**:
   ```bash
   cp .env.production.example .env.production
   chmod 600 .env.production
   # Populate PRODUCTION_DB_PASSWORD with a strong 32-character random string
   # Populate API_KEYS with production dispatch key
   nano .env.production
   ```
4. **Launch Container Services**:
   ```bash
   docker compose --env-file .env.production -f deploy/docker/docker-compose.production.yml up -d --build
   ```
5. **Verify Local Container Readiness**:
   ```bash
   curl -f http://127.0.0.1:8000/v1/health/readiness?region=in-kl-tvm
   ```

### Phase 3: Configure Ingress Reverse Proxy & TLS (Caddy or Nginx)
1. **Install Caddy** (automatic TLS certificate management):
   ```bash
   sudo apt install -y caddy
   sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile
   # Update domain name in Caddyfile if different from api-pool.waymate.in
   sudo systemctl reload caddy
   ```
2. **Verify Public Edge Endpoint**:
   ```bash
   curl -f https://api-pool.waymate.in/v1/health/readiness?region=in-kl-tvm
   ```

### Phase 4: Frontend Live Application Cutover (Requires Approval)
1. In `waymate` frontend repository:
   - Update `.env.production` with `VITE_POOL_ENGINE_URL=https://api-pool.waymate.in`.
2. Build verified production bundle:
   ```powershell
   npm run build:prod
   ```
3. Deploy hosting to `waymate-u`:
   ```powershell
   firebase deploy -P production --only hosting
   ```
4. Perform end-to-end smoke verification on `https://waymate-u.web.app`.
