# WayMate Monorepo — Web Application & Pool Engine

Complete monorepo containing the **WayMate React 19 Frontend Web Client** and the high-performance **Python 3.13+ Provider-Independent Ride-Pooling Engine**, complete with turnkey VPS deployment infrastructure.

---

## Monorepo Layout

```text
pool.engine (Monorepo Root)
├── backend/                              # High-Performance Ride-Pooling & Dispatch Engine
│   ├── src/engine/                       # Core domain models, algorithms, routing, API service
│   ├── tests/                            # Comprehensive unit, scenario, oracle, integration tests
│   ├── config/                           # Regional map configurations (Kerala, Manhattan)
│   ├── playground/                       # Simulation and interactive dispatch sandbox
│   ├── scripts/                          # Benchmarks, graph compilers, DB migrations
│   ├── pyproject.toml                    # Python packaging & dependencies
│   ├── Dockerfile                        # Multi-stage unprivileged backend container
│   └── README.md                         # Detailed backend documentation
│
├── frontend/                             # WayMate Web Client Application
│   ├── src/                              # React 19 components, pages, hooks, poolEngine client
│   ├── public/                           # Static assets, web manifest, icons, robots, sitemap
│   ├── index.html                        # SPA HTML5 entrypoint
│   ├── package.json                      # NPM dependencies & scripts
│   ├── vite.config.ts                    # Vite build configuration (with local dev API proxy)
│   ├── tailwind.config.js                # Tailwind CSS styling system
│   ├── nginx.conf                        # Production Nginx SPA routing & caching config
│   ├── Dockerfile                        # Multi-stage production container build (Node -> Nginx)
│   └── README.md                         # Frontend documentation
│
├── deploy/                               # Production Deployment & Infrastructure
│   ├── docker/
│   │   ├── docker-compose.yml            # Local development orchestration (Frontend, Backend, DB, OSRM)
│   │   ├── docker-compose.production.yml # Multi-container production VPS topology
│   │   └── osrm-data/                    # OSRM road graph assets
│   ├── caddy/
│   │   └── Caddyfile                     # Production Caddy proxy (automatic HTTPS, TLS, rate limits)
│   └── vps/
│       ├── setup_vps.sh                  # Turnkey 1-command VPS deployment script
│       ├── update_vps.sh                 # Fast 1-command zero-downtime update script
│       └── README.md                     # Complete VPS production operations guide
│
├── .gitignore                            # Unified gitignore for Python, Node, Docker, and IDEs
└── AGENTS.md                             # Specification & AI agent governance
```

---

## Quickstart (Local Development)

### 1. Run the Backend (Python Pool Engine)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev,service,postgres]
uvicorn engine.service.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```
The backend API and Swagger UI will be available at:
- **API**: `http://127.0.0.1:8000`
- **Swagger Docs**: `http://127.0.0.1:8000/docs`
- **Health Check**: `http://127.0.0.1:8000/v1/health/liveness`

To run backend tests:
```powershell
cd backend
python -m pytest tests/unit tests/scenario tests/oracle
```

### 2. Run the Frontend (WayMate Web App)
```powershell
cd frontend
npm install
npm run dev
```
The web app starts at `http://localhost:5173`. Any API requests to `/v1/*` are automatically proxied to the Pool Engine backend running at `http://127.0.0.1:8000`.

To run frontend tests:
```powershell
cd frontend
npm test
```

### 3. Or Run Everything with Docker Compose
```powershell
docker compose -f deploy/docker/docker-compose.yml up --build
```
- **Frontend App**: `http://localhost:3000`
- **Backend API**: `http://localhost:8000`
- **PostgreSQL**: `localhost:5432`

---

## Production VPS Deployment (Contabo, DigitalOcean, Hetzner, AWS)

On a fresh Ubuntu 22.04 or 24.04 LTS server:

```bash
# 1. Clone the monorepo
git clone https://github.com/shahadshameem/pool.engine.git
cd pool.engine

# 2. Run automated setup as root
sudo bash deploy/vps/setup_vps.sh
```

The script automatically:
- Installs Docker Engine, Docker Compose, and Caddy.
- Sets up UFW firewall rules (ports 22, 80, 443).
- Generates secure `.env.production` secrets.
- Compiles the Kerala OSRM road graph.
- Configures Caddy for automatic HTTPS certificate provisioning:
  - `waymate.in` $\to$ Frontend SPA (Port 3000)
  - `api-pool.waymate.in` $\to$ Pool Engine API (Port 8000)
- Builds and starts all production containers in a unified Docker network.

### Updating on VPS (Zero-Downtime)
```bash
sudo bash deploy/vps/update_vps.sh
```
Pulls the latest code from GitHub, rebuilds frontend and backend containers, and validates health checks.
