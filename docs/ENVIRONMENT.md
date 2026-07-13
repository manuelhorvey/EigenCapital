# EigenCapital — Environment Variables Reference

Centralized reference for all environment variables used by the EigenCapital paper trading system.

---

## Quick Reference Table

| Variable | Default | Required | Used By | Description |
|----------|---------|----------|---------|-------------|
| `EIGENCAPITAL_API_TOKEN` | — | No | Dashboard server | Bearer token for API auth (enables `Authorization: Bearer <token>` on JSON/POST endpoints) |
| `EIGENCAPITAL_BIND` | `127.0.0.1` | No | Dashboard server | Bind address for the HTTP server. WARNING logged if not loopback. |
| `EIGENCAPITAL_REFRESH_INTERVAL` | `60` | No | Engine loop | Seconds between engine cycles. |
| `EIGENCAPITAL_RATE_LIMIT` | `100` | No | API server | Max requests per 60s per IP for JSON endpoints. |
| `EIGENCAPITAL_ENV` | — | No | Config system | Environment overlay selector (paper/live/backtest/research). |
| `MT5_PASSWORD` | — | Yes* | MT5 bridge | MetaTrader 5 account password (*required for bridge to connect). |
| `MT5_ACCOUNT` | — | Yes* | MT5 bridge | MetaTrader 5 account number. |
| `SLACK_WEBHOOK_URL` | — | No | Slack alerter | Webhook URL for Slack alert integration. |
| `OPENCODE_ZEN_API_KEY` | — | No | Macro narrative pipeline | API key for Claude LLM access (weekly FXStreet narrative extraction). |
| `FRED_API_KEY` | — | No | FRED data fetch | API key for FRED CSV endpoint (higher rate limits when set). Falls back to unauthenticated graph export without a key. |
| `PAGERDUTY_ROUTING_KEY` | — | No | PagerDuty channel | Routing key for PagerDuty event integration. |
| `QUANTFORGE_API_TOKEN` | — | No | (Legacy) | Historical token for QuantForge integration (not currently used). |

\* Required for MT5 bridge functionality. The engine runs without MT5 (PaperBroker only).

---

## Detailed Descriptions

### `EIGENCAPITAL_API_TOKEN`

Dashboard bearer-token authentication. When set, all JSON API endpoints and POST endpoints
require `Authorization: Bearer <token>`. Static files (HTML/CSS/JS) are exempt so the React
SPA can poll. Env var takes precedence over `api_token` in `configs/domains/infrastructure/config.yaml`.

```bash
export EIGENCAPITAL_API_TOKEN="$(openssl rand -hex 32)"
```

### `EIGENCAPITAL_BIND`

Controls the dashboard server's bind address. Defaults to `127.0.0.1` (loopback only).
Changing to `0.0.0.0` exposes the dashboard to the network and emits a WARNING log line.

```bash
# Default — safe
export EIGENCAPITAL_BIND=127.0.0.1

# DANGEROUS — network-accessible
export EIGENCAPITAL_BIND=0.0.0.0
```

### `EIGENCAPITAL_REFRESH_INTERVAL`

Controls how frequently the engine cycle runs. Default 60 seconds.
Lower values increase CPU/API load.

```bash
# Faster cycle (for testing)
export EIGENCAPITAL_REFRESH_INTERVAL=30

# Slower cycle (for low-resource environments)
export EIGENCAPITAL_REFRESH_INTERVAL=120
```

### `EIGENCAPITAL_ENV`

Selects an environment overlay from `configs/environments/`. Controls `data_source`,
`rebalance` frequency, and `research_mode`. Valid values: `paper`, `live`, `backtest`,
`research`.

```bash
export EIGENCAPITAL_ENV=backtest
```

### `MT5_PASSWORD` & `MT5_ACCOUNT`

Credentials for the MetaTrader 5 demo account. Read by the bridge supervisor
(`scripts/ops/mt5_bridge_supervisor.py`) at launch time. Never passed via argv
(the `monitor_all` script was fixed in 2026-06-30 to prevent `ps aux` leakage).

```bash
export MT5_ACCOUNT=12345678
export MT5_PASSWORD="your_demo_password"
```

### `SLACK_WEBHOOK_URL`

Enables the Slack alerting daemon (`paper_trading/ops/slack_alerter.py`).
If not set, the alerter skips Slack delivery (logs only).

### `OPENCODE_ZEN_API_KEY`

Required for the weekly macro narrative pipeline. Without this key, the LLM
call is skipped and a neutral narrative is saved instead.

### `PAGERDUTY_ROUTING_KEY`

Optional PagerDuty integration via `paper_trading/alerting/channels/pagerduty.py`.
If not set, PagerDuty events are silently dropped.

---

## Security Notes

- `.env` file permissions must be `0600` (owner-only read/write). If the file
  is group- or world-readable, a WARNING is logged listing every exposed variable.
- The `monitor_all` launcher no longer passes `--password $MT5_PASSWORD` on argv.
- CI (`tools/check_no_plaintext_secrets.py`) scans for hardcoded secrets with
  an allowlist for known placeholders (`your_password`, `...`).

---

**Last updated:** 2026-07-08
