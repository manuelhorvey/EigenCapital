# EigenCapital — Findings Registry
> Branch: fix/findings-resolution
> Baseline: ruff ❌ 2 pre-existing F401 · mypy ✅ 309 files · unit tests ✅ 3391 passed, 2 skipped
> Last updated: 2026-09-28 (post-resolution: ruff ✅ · mypy ✅ 309 files · 3450 passed, 2 skipped)

## BASELINE (pre-change state, recorded 2026-09-28)
- **Ruff**: 2 pre-existing errors (out of scope, will be cleaned up with H-5/C-5):
  - `src/eigencapital/live/daily_loss.py:42` F401 `datetime.timedelta` unused
  - `src/eigencapital/live/watchdog.py:314` F401 `sys` unused
- **Mypy**: Success — no issues found in 309 source files
- **Unit tests**: `3391 passed, 2 skipped` (no pre-existing failures)

## Status Legend
- `open` / `in_progress` / `done` / `blocked` / `skipped`

## WORK QUEUE (orchestrator)
- **Verified & committed this run (batch 1)**: C-1, C-3, C-4, C-5, C-6, H-4, H-5, H-7, H-12
- **Verified & committed this run (batch 2)**: H-8, H-9, H-9b, H-11, H-14 (each independently reviewed, one commit per finding)
- **Verified & committed (batch 3)**: H-10, M-6, M-2, M-8, M-10, M-11 (each independently reviewed, one commit per finding)
- **Next**: M-13, M-7, M-3/M-4, M-5, then M-14, M-9, L-1/L-2, L-3/L-4, then M-12, L-5..L-8, then H-13, then M-1 last (big refactor, alone), then final re-scan
- **Out of range, carried to final re-scan**: C-2, H-1, H-2, H-3
- **This run** (per instruction): H-5 → L-8, in severity order, parallel only across disjoint files
- **Not in requested range**: C-2, H-1, H-2, H-3 — carried forward to the final re-scan

---

## CRITICAL (P0)

| ID | Description | Affected Files | Status |
|---|---|---|---|
| C-1 | Fingerprint verifier caches after first cycle — never re-hashes | `production_qual/fingerprint_verifier.py` | done |
| C-2 | `live/broker.py` stub doesn't send real orders | `live/broker.py`, `scripts/r4_rebalance_loop.py` | open |
| C-3 | `durable_audit.py` no file lock on append + mirror zeroing | `live/durable_audit.py` | done |
| C-4 | `supervisor.py` TOCTOU race — duplicate live loop risk | `live/supervisor.py` | done |
| C-5 | `daily_loss.py` static UTC offset breaks on DST | `live/daily_loss.py` | done |
| C-6 | `catastrophic_protection.py` retry loop drops exceptions | `live/catastrophic_protection.py` | done |

## HIGH (P1)

| ID | Description | Affected Files | Status |
|---|---|---|---|
| H-1 | Hardcoded 1-contract sizing ignores target_risk | `portfolio/portfolio.py:184` | open |
| H-2 | Exposure calc uses entry price not market price | `portfolio/portfolio.py:56` | open |
| H-3 | `_deep_merge` shallow copy mutates base config | `config.py:270` | open |
| H-4 | Reconciliation ignores swaps/commissions | `reconciliation/engine.py:698-725` | done |
| H-5 | `watchdog.py` pgrep match is brittle | `live/watchdog.py` | done |
| H-7 | No unit tests for ReconciliationEngine | `tests/unit/reconciliation/` (missing) | done |
| H-8 | `campaign.py` state purely in-memory | `live/campaign.py` | done |
| H-9 | `trading_provider.py` swallows all exceptions in connect() | `execution/trading_provider.py` | done |
| H-9b | Same swallow defect on the real call path: `MT5Connection.connect()` | `micro_live/runner.py:37` | done |
| H-10 | Dead [risk] config table never parsed | `configs/production/config.toml`, `config.py` | open |
| H-11 | Auth token in URL query string (dashboard) | `dashboard/src/lib/config.ts` | done |
| H-12 | Fingerprint verifier tests miss cache bypass | `tests/unit/production_qual/` | done |
| H-13 | Min-lot forcing bypasses concentration limits | `scripts/r4_rebalance_loop.py` | open |
| H-14 | Snapshot rate limiter misses transient events | `production_qual/evidence_orchestrator.py` | done |

## MEDIUM (P2)

| ID | Description | Affected Files | Status |
|---|---|---|---|
| M-1 | r4_rebalance_loop.py God Object (3000+ lines) | `scripts/r4_rebalance_loop.py` | open |
| M-2 | events.py in-memory audit lost on crash | `execution/events.py` | open |
| M-3 | mt5_provider.py strips timezone on yfinance fallback | `data/mt5_provider.py` | open |
| M-4 | mt5_provider.py uses auto_adjust=True | `data/mt5_provider.py` | open |
| M-5 | portfolio.py cash update is equity-style not margin | `portfolio/portfolio.py` | open |
| M-6 | mypy silenced with || true in CI | `.github/workflows/ci.yml` | done |
| M-7 | CI matrix: integration tests only on Python 3.13 | `.github/workflows/ci.yml` | open |
| M-8 | Dashboard exposes raw financial data without masking | `dashboard/src/` | open |
| M-9 | No MT5 reconnect backoff | `scripts/r4_rebalance_loop.py` | open |
| M-10 | AuthorizationGate lacks cryptographic signing | `live/authorization.py` | open |
| M-11 | rebalance_policy.py silently returns default on corrupt file | `live/rebalance_policy.py` | open |
| M-12 | Global weight_error_by_symbol dict is thread-unsafe | `scripts/r4_rebalance_loop.py` | open |
| M-13 | Account ID hardcoded in production config | `configs/production/config.toml` | open |
| M-14 | No Python lockfile | `pyproject.toml` | open |

## LOW (P3)

| ID | Description | Affected Files | Status |
|---|---|---|---|
| L-1 | Primitive Obsession — bare strings for order sides/risk decisions | `portfolio/portfolio.py`, `risk_enforcement.py`, `reconciliation/engine.py` | open |
| L-2 | Feature Envy — portfolio.py computes PnL by reaching into Position | `portfolio/portfolio.py` | open |
| L-3 | PortfolioAnalyzer.compute_diagnostics long method | `live/portfolio_analytics.py` | open |
| L-4 | Blanket except Exception: return {} in portfolio_analytics.py | `live/portfolio_analytics.py` | open |
| L-5 | DashboardStateService Divergent Change smell | `live/` | open |
| L-6 | No frontend tests | `dashboard/package.json` | open |
| L-7 | SECURITY.md missing PGP key and API threat model | `SECURITY.md` | open |
| L-8 | structured_logging.py defaults to stderr without rotation | `live/structured_logging.py` | open |

---

## HUMAN CHECKPOINTS (blocked until answered)

| ID | Question |
|---|---|
| H-10 | Dead [risk] table — intentional or should be wired in? |
| M-13 | Account ID hardcoded — env var, secrets manager, or keep? |
| M-14 | Lockfile strategy: pip-compile→requirements.txt or Poetry? |
| M-1 | Decompose r4_rebalance_loop.py — full refactor or in-place fixes only? |

---

## DEPENDENCY MAP
- C-1 → H-12
- H-1 → H-2 → M-5 (same file)
- M-3 → M-4 (same file)
- M-6 → M-7 (same CI file)
- L-1 → L-2 (same file)
- L-3 → L-4 (same file)
- M-1 → M-9 → M-12 (same script)

## CHANGE LOG
(updated as findings are resolved)

## HUMAN CHECKPOINT ANSWERS (2026-09-28)
- H-10: Annotate [risk] as dead/legacy with comment — no wiring change
- M-13: Move account ID / server to env vars (MT5_ACCOUNT_ID, MT5_SERVER) with placeholder in config
- M-14: pip-compile → requirements.txt + requirements-dev.txt and commit
- M-1: Extract key concerns into modules; keep script as orchestrator
- H-11: Move the token out of the URL — `X-API-Key` header on HTTP, WS subprotocol/message for WebSocket; server accepts both during a transition window
- M-8: Mask in the DTO layer (account IDs, balances, notionals rounded; exact values stay behind the authenticated API)
- M-10: HMAC-SHA256 signing with fail-closed verification, with an accept-then-reject window for legacy unsigned records

