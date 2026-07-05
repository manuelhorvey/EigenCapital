# EigenCapital — Dashboard HTTP Endpoints

The dashboard server (port 5000) exposes JSON endpoints consumed by the React frontend and external monitoring tools. All endpoints are `GET` unless noted.

**Server**: `paper_trading/serve.py` (stdlib `http.server` + `ThreadingMixIn`)  
**Auth**: Optional bearer token via `EIGENCAPITAL_API_TOKEN` env var or `api_token` in config. Static files excluded.  
**Rate limit**: 100 req/60s per IP (static paths exempt).  
**CORS**: `http://127.0.0.1:3000` (Vite dev) + same-origin.

---

## Primary Data Source

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/state-bundle.json` | `SystemBundle` | Full engine state (snapshot + health + MT5) — fetched async, stale-while-revalidate |

## State & Monitoring

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/state.json` | `EngineSnapshot` | Current asset states, portfolio summary, weekend_cycle, live Sharpe |
| `/health.json` | `dict` | Asset-level governance health and validity states |
| `/health` | `dict` | Engine liveness (alive/stale/dead, state file age, sequence ID) |
| `/health/<asset>.json` | `dict` | Single asset health detail |
| `/metrics` | Prometheus text | Prometheus metrics exposition (v0.0.4) |
| `/ping` | `{"status": "ok"}` | Liveness check |
| `/logs` | `list[dict]` | Recent engine log lines (last 200, text) |

## Portfolio & Risk

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/risk.json` | `dict` | Portfolio risk summary (VaR, CVaR, drawdown) |
| `/risk/<asset>.json` | `dict` | Single asset risk detail |
| `/risk-parity.json` | `dict` | Risk parity weight allocations |
| `/governance.json` | `dict` | Governance state per asset (multipliers, validity, halt) |
| `/statistical-metrics.json` | `dict` | PSR(>0), PSR(>1), MinTRL, CRS, HHI per asset |
| `/trade-outcomes.json` | `dict` | TP/SL/win rate aggregates from SQLite |
| `/weekly-review.json` | `dict` | Weekly review computation data |

Position concentration data is available inside `/state.json` under `portfolio.position_concentration` — there is no standalone endpoint.

## Attribution & Execution

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/attribution/trades.json` | `list[dict]` | Per-trade 4-domain attribution (`?limit=&offset=&archetype=&regime=&asset=`) |
| `/attribution/summary.json` | `dict` | Aggregated attribution summary by archetype and regime |
| `/attribution/waterfall.json` | `dict` | PnL waterfall decomposition (prediction/execution/exit/friction) |
| `/attribution/live.json` | `dict` | Live open position attribution (MFE, MAE tracking) |
| `/execution/quality.json` | `dict` | EIS and FQI scores per asset |
| `/execution/slippage.json` | `dict` | Entry/exit slippage distribution, gap and partial-fill counts |

## Shadow & Counterfactual

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/shadow/trades.json` | `list[dict]` | Shadow vs live trade comparison (`?limit=&offset=&alt_label=`) |
| `/shadow/summary.json` | `dict` | Divergence rate by config label |
| `/shadow-actions` | `dict` | All shadow actions |
| `/shadow-actions/<asset>.json` | `dict` | Single asset shadow action |

## Trades & Assets

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/trades.json` | `list[dict]` | Trade journal (`?limit=10&offset=0`, max 200) |
| `/asset/<asset>.json` | `dict` | Single asset detail (model, position, governance, sell_only, tripwire) |
| `/wal/<asset>.json` | `list[dict]` | WAL timeline events for an asset (`?max=100`) — features_snapshot, inference_output, decision_output |
| `/confidence.json` | `dict` | Per-asset live + historical confidence bucket histograms |
| `/volatility.json` | `dict` | Live vol vs rolling baseline (green/amber/red) |
| `/equity_history.json` | `list[dict]` | Portfolio equity curve time series |
| `/archetype/stats.json` | `dict` | Archetype classification distribution (avg R, WR, TP/SL rate, slippage) |

## Macro & Liquidity

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/narrative.json` | `dict` | Current macro narrative (weekly LLM output, stale flag) |
| `/liquidity.json` | `dict` | Per-asset liquidity regime (NORMAL/THIN/STRESSED) with scalars |
| `/psi.json` | `dict` | PSI drift scores per feature per asset (30s cache) |

## Optimization & Analytics

| Endpoint | Response | Description |
|----------|----------|-------------|
| `/optimization.json` | `dict` | Drift detector recommendations from `data/live/optimization.json` |
| `/analytics/snapshot.json` | `dict` | Precomputed aggregate analytics (5-cycle gate) |
| `/mt5/status.json` | `dict` | MT5 bridge connection status (cached in-memory) |
| `/weekly-review.json` | `dict` | Weekly review data |

## POST Endpoints

| Endpoint | Body | Description |
|----------|------|-------------|
| `/narrative/confirm` | `{}` | Confirm pending macro narrative (promotes pending → active) |
| `/weekly-review/acknowledge` | `{}` | Acknowledge weekly review (timestamped log) |
| `/api/clear-cache` | `{}` | Clear all in-memory API response caches |
| `/api/log-error` | `{"message": str}` | Submit client-side error to engine logs |

## Data Flow

The primary data flow is: `GET /state-bundle.json` → sliced via React Query selectors → memoized components. All other endpoints are secondary and polled at lower frequencies (30-60s). Static SPA files (`/`, `/index.html`, `/assets/*`, `/favicon.ico`) are served by `handler.py` and fall through to `index.html` for client-side routing.

---

**Last updated:** 2026-07-05
