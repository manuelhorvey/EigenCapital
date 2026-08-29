# Dashboard Operations Runbook

## Quick Start

### Development
```bash
# Backend
cd /path/to/EigenCapital
python scripts/dashboard_server.py --port 8080

# Frontend (separate terminal)
cd dashboard
npm run dev
```

### Production
```bash
# Build frontend
cd dashboard
npm run build

# Serve with nginx/caddy
# Backend runs independently
python scripts/dashboard_server.py --host 0.0.0.0 --port 8080
```

## Architecture

```
React Dashboard (port 5173/80)
        │
        ▼
FastAPI Backend (port 8080)
        │
        ▼
EigenCapital Domain Models
        │
        ▼
MT5 / Production State
```

## Health Checks

### Backend Health
```bash
curl http://localhost:8080/api/v1/system/health
```

Expected response:
```json
{
  "status": "ok",
  "trading_authorization": "TRADING_AUTHORIZED",
  "timestamp": "2026-08-28T23:00:00Z"
}
```

### Build Verification
```bash
curl http://localhost:8080/api/v1/system/build
```

Expected response:
```json
{
  "git_head": "...",
  "manifest_identity": "...",
  "verified": true,
  "drift_detected": false
}
```

## Troubleshooting

### Dashboard shows "UNKNOWN" state
1. Check if backend is running: `curl http://localhost:8080/`
2. Check if MT5 is accessible: `python -c "from mt5linux import MetaTrader5; print('OK')"`
3. Check reports directory exists: `ls -la reports/`

### Positions not updating
1. Verify MT5 connection: Check `reports/r4_loop/` for recent decisions
2. Check WebSocket connection in browser DevTools
3. Verify API endpoint: `curl http://localhost:8080/api/v1/portfolio/positions`

### Risk state shows "UNKNOWN"
1. Check risk observation files in `reports/r4_loop/`
2. Verify risk observer is running in trading loop
3. Check API response: `curl http://localhost:8080/api/v1/risk`

### Build drift detected
1. Check git HEAD matches expected
2. Verify manifest identity
3. Check configuration fingerprint
4. Restart dashboard after verification

## Monitoring

### Dashboard Metrics
- API latency: `/api/v1/system/health` response time
- WebSocket connections: Active connection count
- Data freshness: Age of last update

### Alerts
- Dashboard outage does NOT affect trading
- Dashboard cannot modify production state
- All dashboard access is logged

## Backup/Recovery

### Backup
- Dashboard is stateless
- No database to backup
- Configuration in `configs/production/config.toml`

### Recovery
1. Restart backend: `python scripts/dashboard_server.py`
2. Rebuild frontend: `cd dashboard && npm run build`
3. Verify health: `curl http://localhost:8080/api/v1/system/health`

## Support

- Backend logs: stdout/stderr of dashboard server
- Frontend errors: Browser DevTools console
- API documentation: `http://localhost:8080/api/docs`
