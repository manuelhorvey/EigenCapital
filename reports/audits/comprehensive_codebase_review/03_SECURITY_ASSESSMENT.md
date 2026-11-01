# Security Assessment

## Scope

Repository, git history filenames, dashboard HTTP/WS surface, live-loop filesystem and process controls, audit-log integrity, and supply chain (CI + dependencies). No penetration test against a running deployment, no CVE database scan, no container/image review.

## Summary

No committed secrets were found. The dashboard's authentication design is better than typical internal tools (constant-time compare, no URL credentials by default, rate limiting, restricted CORS, loopback bind, DTO masking). The material weaknesses are **predictable default credentials**, **local privilege/state-file trust**, and **audit-chain integrity that is tamper-evident but not tamper-resistant**.

## Secrets and credentials

| Item | Finding | Severity |
|---|---|---|
| Committed secrets | None found. In-tree grep hits are test fixtures. No key/credential filenames in git history. | — |
| `.env` at repo root | Untracked, only `.env.example` is tracked. Contains broker account/server identifiers and environment selector. Not a secret leak into git, but it is plaintext on disk. | Low |
| Dashboard API key | Falls back to `dev-key-change-in-production` when `DASHBOARD_API_KEY` is unset (`dashboard/api/app.py`, `dashboard/streaming/events.py`, `scripts/start_dashboard.sh`). Predictable default. | Medium |
| Auth bypass switch | `DASHBOARD_DISABLE_AUTH=1` disables auth entirely; intended for local dev. If set in a service unit it silently exposes live state. | Medium |
| Legacy token transport | `?token=` accepted on WebSocket during a transition window. Documented, but keys in URLs leak via logs/proxies. | Low |
| Startup script | `start_dashboard.sh` binds to `127.0.0.1` and exports the default `DASHBOARD_API_KEY`. Loopback bind materially reduces exposure. | Medium → Low in practice |
| Frontend key exposure | `start_dashboard.sh` also sets `VITE_API_KEY` to the same value, so the key is embedded in the frontend bundle. Auth is a perimeter control, not per-user authorization: anyone who can load the UI has the key. | Low (loopback, single operator) |

**Recommendation:** fail closed when `EIGENCAPITAL_ENV=production` and `DASHBOARD_API_KEY` is missing or equal to the default; remove `?token=` acceptance; log a startup warning if auth is disabled.

## Transport and API surface

- CORS restricted to explicit localhost origins, `allow_methods=["GET"]`, credentials enabled. Environment-overridable.
- Security headers set globally (`nosniff`, `SAMEORIGIN`, referrer policy, no-store).
- `/healthz`, `/`, `/api/docs`, `/api/redoc` are unauthenticated. Docs exposure is informational only; no live state.
- Per-IP rate limit default 600 req/min, applied **before** auth (good for brute-force). In-memory counters: a multi-worker deployment would multiply the effective limit.
- WebSocket requires the same key via `api-key.<key>` subprotocol, Bearer, or legacy query token; the stream is masked to reduce leakage to shared viewers.
- Exact balances/P&L remain on authenticated REST. Reasonable split.

## Process and filesystem controls

| Control | Status |
|---|---|
| Single live-loop instance | `ProcessSupervisor.claim_instance()` with PID file + `fcntl` lock; exit 75 on refusal. Verified. |
| Single safety-supervisor instance | Separate PID/health files. Verified by code. |
| Atomic writes for health/supervisor state | `tmp` + `os.replace` + `fsync`. Verified. |
| Durable audit inter-process lock | `fcntl` lock + `fsync` + mirror. Verified. |
| File permissions on `.env` / state | Not enforced by code; relies on operator `umask`. **Unverified.** |
| Path traversal in dashboard | Paths derive from fixed repo-relative specs, not user input. No user-supplied path found. | 
| Arbitrary code execution | No `eval`/`exec` in dashboard or live path; `subprocess` use limited to start/stop scripts. | 

## Audit-log integrity

`DurableAudit` computes `sha256(prev_hash | seq | canonical(payload))` and writes a primary plus atomic mirror. This detects accidental mutation, deletion, or reordering **only if** an attacker cannot rewrite both copies.

Limitations:

- **Unkeyed hash chain.** There is no HMAC/secret key. An attacker with write access to both primary and mirror can recompute a fully consistent chain.
- **Event ID counter** in `AuditLog` is reconstructed by replay and is not protected by the chain, so concurrent processes can duplicate `event_id`s.
- **Not wired to the live loop** (see P0-3), so today the strongest audit primitive protects the least important path (`campaign.py`).

**Recommendation:** HMAC the chain with a key held outside the repo (env or OS keyring), and export periodic chain head digests to an append-only external sink (e.g., a second host or object-lock bucket).

## Supply chain

| Issue | Detail |
|---|---|
| Unpinned runtime deps | `pandas>=2.0`, `numpy>=1.24`, `statsmodels>=0.14` — builds are not reproducible. |
| GitHub Actions by tag, not SHA | `actions/checkout@v4`, `setup-python@v5`, `codecov/codecov-action@v5` (mutable tags). |
| No `permissions:` block | Workflow inherits default token permissions (may be write). |
| Coverage upload non-blocking | `fail_ci_if_error: false`. |
| No dependency vulnerability scan | No `pip-audit`/Dependabot config found. |
| Python matrix | CI 3.11–3.13; local dev on 3.14. Runtime floor `>=3.11` is consistent but 3.14 is untested in CI. |
| PyPI install in CI | `pip install -e ".[dev]" "[research]"` without hashes. |

**Recommendation:** pin actions to commit SHAs, add `permissions: contents: read`, add `pip-audit` (non-blocking initially), and lock runtime dependencies for operational deployments.

## Research/evidence integrity as a security property

`SIMULATED_EVIDENCE` executors and hard-coded research paths exist and are referenced only by tests today. They are a **latent fabrication path**: any future wiring that selects them in a promotion context would produce "evidence" with no execution. Recommend making them import-time test-only (e.g., guarded by `if "pytest" not in sys.modules: raise`) or moving them into `tests/`.

## Security rating

| Area | Rating |
|---|---|
| Credential handling | Medium (default key; loopback mitigates) |
| AuthN/AuthZ | Good for single-operator local tool |
| Audit integrity | Medium (tamper-evident, not resistant; unwired) |
| Supply chain | Medium–Low (no pinning, no CVE scan) |
| Process containment | Good |

No CRITICAL remote-code-execution or authentication-bypass finding was identified in the code. The highest-impact security change is to fail closed on missing/default credentials in production.
