# EigenCapital Dashboard (frontend)

React + TypeScript + Vite operator UI. **Read-only observer** — never controls trading.

| Topic | Document |
|---|---|
| Architecture | [`docs/production/DASHBOARD_ARCHITECTURE.md`](../docs/production/DASHBOARD_ARCHITECTURE.md) |
| API | [`docs/production/DASHBOARD_API.md`](../docs/production/DASHBOARD_API.md) |
| Operations | [`docs/production/DASHBOARD_OPERATIONS.md`](../docs/production/DASHBOARD_OPERATIONS.md) |
| Security | [`docs/production/DASHBOARD_SECURITY.md`](../docs/production/DASHBOARD_SECURITY.md) |

## Develop

```bash
# From repo root: start API/backend helpers as documented in ops docs
./scripts/start_dashboard.sh

# Frontend (this directory)
npm install
npm run dev
```

Canonical server entrypoint: `scripts/dashboard_server.py` / `scripts/start_dashboard.sh`. Backend package: `src/eigencapital/dashboard/`.

Invariant: dashboard routes are GET-only; no POST/PUT/PATCH/DELETE.
