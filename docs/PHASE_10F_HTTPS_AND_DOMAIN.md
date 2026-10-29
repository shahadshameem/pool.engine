# Pool Engine — Phase 10F: HTTPS Ingress & Domain Integration

**Repository:** `C:\Users\shaha\pool engine`  
**Phase:** Phase 10F — Ingress & HTTPS  
**Date:** October 29, 2026  
**Auditor:** Senior SRE / Network Security Engineer (Pair-Programming Agent)  
**Target Environment:** Contabo Linux VPS with Coolify / Caddy Reverse Proxy  
**Status:** COMPLETE & DOCUMENTED (Configuration Specified; Awaiting User Domain Confirmation)  

---

## 1. Executive Summary

This document specifies the ingress architecture, reverse proxy routing, TLS 1.3 encryption, proxy forwarding headers, and ingress rate limiting for Pool Engine on the Contabo Linux VPS.

In accordance with deployment safety principles:
- **Zero Direct Public Exposure:** The PostgreSQL database and OSRM routing containers do not expose any ports on public network interfaces.
- **Loopback Ingress:** `pool-engine-api` binds strictly to `127.0.0.1:8000`.
- **Pre-Flight DNS Gate:** DNS records and public TLS certificates require explicit user domain confirmation before activation.

---

## 2. Ingress Architecture & Proxy Topology

```
             Public Client Traffic (HTTPS / Port 443)
                                │
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Contabo VPS Host: Coolify / Caddy Reverse Proxy     │
       │       - Automated Let's Encrypt ACME TLS 1.3            │
       │       - HTTP to HTTPS 301 Redirect                      │
       │       - Rate Limiting: 30 req/min per client IP         │
       │       - Security Headers (HSTS, nosniff, DENY)          │
       └────────────────────────┬────────────────────────────────┘
                                │ Forwarding to http://127.0.0.1:8000
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Pool Engine API Container (pool-engine-prod-api)    │
       │       - Reads X-Forwarded-For, X-Forwarded-Proto        │
       │       - CORS Restricted to Configured Origins           │
       └─────────────────────────────────────────────────────────┘
```

---

## 3. Reverse Proxy Configuration Specifications

### 3.1 Caddy Configuration Snippet (`/etc/caddy/Caddyfile`)
If using host-level Caddy:
```caddy
{$POOL_ENGINE_DOMAIN:api.waymate.in} {
    # Automatic HTTPS with TLS 1.3
    tls {
        protocols tls1.3
    }

    # Security Headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

    # Rate Limiting: Protect ride-creation and dispatch endpoints
    @ride_creation {
        path /v1/requests*
        method POST
    }
    # 30 requests per minute per IP for passenger ride requests
    rate_limit @ride_creation {
        zone rider_zone {
            key {remote_host}
            events 30
            window 1m
        }
    }

    # Reverse proxy to Pool Engine ASGI API
    reverse_proxy 127.0.0.1:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

### 3.2 Coolify Deployment Integration
If deploying through the VPS Coolify instance:
1. **Application Source:** Git repository `https://github.com/shahadshameem/pool.engine` (branch `master`).
2. **Build Pack:** `Docker Compose` referencing `deploy/docker/docker-compose.production.yml`.
3. **Domain Assignment:** In Coolify application settings, assign domain (e.g. `https://api.waymate.in`). Coolify's internal Traefik/Caddy proxy automatically negotiates Let's Encrypt certificates and routes traffic to container port 8000.
4. **Environment Variables:** Provide `PRODUCTION_DB_PASSWORD`, `AUTH_ENABLED=true`, and `FIREBASE_PROJECT_ID=waymate-v3` in Coolify's secret manager.

---

## 4. Required Inputs from User Prior to Public Activation

Before creating public DNS records or initiating TLS handshakes:
1. **Target Pilot Hostname:** Confirmation of the intended domain (e.g., `api.waymate.in`, `pool.waymate.in`, or `staging-pool.waymate.in`).
2. **DNS A Record:** Point the chosen hostname to the Contabo VPS public IPv4 address.
3. **Proxy Preference:** Confirmation of whether Coolify's built-in proxy or a standalone host Caddy/Nginx service manages the domain routing.
