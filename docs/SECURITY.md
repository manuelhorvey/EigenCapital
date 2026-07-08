# Security

EigenCapital's security model is layered: the dashboard binds to loopback by
default, MT5 rejects non-loopback hosts, secrets live in environment
variables (never argv), and the `.env` file is treated as a sensitive
artifact.

## 1. Dashboard HTTP server — bearer token authentication

**File:** `paper_trading/serve.py`

| Setting | Default | Override |
|---|---|---|
| Bind address | `127.0.0.1` | `EIGENCAPITAL_BIND` env var |
| Port | `5000` | positional arg to `serve()` |
| Auth | **Off** | `EIGENCAPITAL_API_TOKEN` env var OR `api_token` in `config` |

**Behaviour:**
- With `EIGENCAPITAL_API_TOKEN` unset: server is open to anyone who can reach
  the bound port (safe by default because the bind is loopback).
- With `EIGENCAPITAL_API_TOKEN` set: all JSON API endpoints and POST endpoints
  require `Authorization: Bearer <token>`. Static files (HTML/CSS/JS)
  remain accessible without auth so the React SPA can poll.
- The env var takes precedence over the config value.

**Warnings:**
- Non-loopback bind address emits a WARNING log line.
- `Authorization` headers are never logged or echoed in error messages.

```bash
# Enable auth
export EIGENCAPITAL_API_TOKEN="$(openssl rand -hex 32)"

# Bind to all interfaces (DANGEROUS — only for test envs)
export EIGENCAPITAL_BIND=0.0.0.0  # warns on startup
```

**CORS:** Restricted to `http://127.0.0.1:3000` (Vite dev server) and
same-origin. No wildcards.

## 2. MT5 bridge — loopback enforcement

**File:** `paper_trading/ops/mt5_client.py`

| Setting | Configured |
|---|---|
| `bridge_host` | `127.0.0.1` (only acceptable value) |
| `bridge_port` | `9879` |
| Override for non-loopback | `allow_remote_bridge=True` constructor flag (testing ONLY — emits WARNING) |

`MT5Client._is_loopback(host)` rejects:
- public IPs (CIDR-fall-through)
- private RFC1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`)
  unless `allow_remote_bridge=True`
- missing-host / `None`
- IPv6 link-local without explicit loopback prefix

The bridge (TCP frame protocol — `paper_trading/ops/mt5_bridge.py` server + `paper_trading/ops/mt5_client.py` client) is also expected to bind
to `127.0.0.1`; an AST-level guard in `tests/test_mt5_security.py`
ensures the bridge source string doesn't drift.

**Connection retry policy:**
- `ensure_connected()` exponential backoff capped at 30 s.
- Forced re-connect invalidates position cache.

## 3. Secrets in `.env`

**File:** `paper_trading/config_manager.py:_warn_on_insecure_dotenv()`

Tracked sensitive variables (warned on world-readable `.env`):
- `MT5_PASSWORD`
- `MT5_ACCOUNT`
- `OPENCODE_ZEN_API_KEY`
- `QUANTFORGE_API_TOKEN`
- `PAGERDUTY_ROUTING_KEY`
- `SLACK_WEBHOOK_URL`

**Policy:**
- `.env` permissions must be `0600` (owner-only read/write).
- On import, if `.env` is group- or world-readable AND any tracked variable
  is present, a WARNING log lists every leaked variable name.
- `.env` is in `.gitignore`.

**CI checks:**
- `tools/check_no_plaintext_secrets.py` — regex sweep with allowlist for
  known placeholders (`your_password`, `...`, etc.).
- `tests/` directory is excluded.

## 4. Argv hygiene

- The launcher script `monitor_all` no longer passes `--password
  $MT5_PASSWORD` (was leaking the secret via `ps aux`).
- MT5 password is read from env at the bridge supervisor level
  (`scripts/ops/mt5_bridge_supervisor.py`).

## 5. Pre-commit hooks

**File:** `.pre-commit-config.yaml` — six local hooks:

| Hook | Purpose |
|---|---|
| `ruff lint` | Static lint |
| `ruff format` | Deterministic formatting |
| `config-schema-check` | `tools/check_config_schema.py` (only when `configs/*.yaml` changes) |
| `import-firewall` | `tools/check_import_firewall.py` (forbidden-import sweep) |
| `unclaimed-todo-scan` | AST scan for uncommented `TODO`/`FIXME`/`XXX`/`HACK` markers |
| `no-bare-asserts` | `tools/check_no_bare_asserts.py` — production code with bare `assert` fails to land |
| `plaintext-secret-detector` | `tools/check_no_plaintext_secrets.py` |

Install once: `pre-commit install`. Hooks run on every `git commit`.

## 6. Drift detection between docs and code

CI gate `tools/doc_drift_check.py` (new in 2026-06-30 audit) verifies:
- All cited module paths in `AGENTS.md` "Key Files" and `SYSTEM_OVERVIEW.md`
  "Component Responsibilities" tables resolve on disk.
- Asset-count in domain config files (`configs/domains/assets/`) matches the count in
  `paper_trading/models/` minus `orphaned/`.
- Phase count derived from `paper_trading/orchestrator/engine.py:_phase_X_*`
  matches Mermaid diagrams in `README.md` / `docs/SYSTEM_OVERVIEW.md` /
  `docs/PRODUCTION_SYSTEM_SPEC_v1.md`.
- SELL_ONLY sets match across code, docs, and config.

A failed check fails the PR.

**Grafana dashboards** live in `ops/grafana/` - pre-built dashboard definitions for
engine metrics. The Prometheus scrape config is at `ops/prometheus.yml`.

## 7. Observability hardening

- `tests/test_json_logging.py` covers hardening: no internal Python state
  leaks into structured log records.
- `tests/test_prometheus_metrics.py` cover label escaping and sample
  ordering.

## 8. Property-based invariants

- `tests/test_sizing_chain_properties.py` (10 hypothesis-driven) — atomic
  budget under concurrent compute, no crash on zero equity or extreme
  `size_scalar`/`drawdown`.

---

**Reporting security issues:** Email `security@eigencapital.local` (placeholder
— replace before going live).

---

**Last updated:** 2026-07-05
