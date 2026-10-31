# WayMate Frontend — Web Client

High-performance, modern ride-sharing web application built with **React 19**, **TypeScript**, **Vite**, and **Tailwind CSS**.

---

## Features
- **Rider & Host Experience**: Search, request, offer, and manage pooled rides.
- **Pool Engine Integration**: Seamlessly connects to the WayMate Pool Engine backend for real-time optimal vehicle dispatch, candidate pooling, and detour calculations.
- **Maps & Geolocation**: Integrated route selection, pickup/dropoff coordinate capture, and H3 spatial index mapping.
- **Authentication & Security**: Firebase Auth + MFA with local emulation support.

---

## Getting Started

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Configure Environment
Copy `.env.example` to `.env.local` and set required keys:
```bash
cp .env.example .env.local
```

### 3. Run Development Server
```bash
npm run dev
```
The app runs at `http://localhost:5173`. Any calls to `/v1/*` are automatically proxied to the Pool Engine backend at `http://localhost:8000`.

### 4. Run Tests & Linter
```bash
npm test
npm run lint
```

### 5. Build for Production
```bash
npm run build
```
Compiled static assets are generated in `dist/`.
