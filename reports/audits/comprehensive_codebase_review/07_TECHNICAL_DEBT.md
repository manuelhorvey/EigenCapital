# Technical Debt Register

Priorities are **relative to capital readiness**, not general cleanliness. Items marked ⚠ overlap with a P0/P1 finding and should not be handled as refactors.

| ID | Debt | Location | Priority | Notes |
|---|---|---|---|---|
| TD-01 | Live loop is a 3,329-line god module mixing signal, sizing, execution, reconciliation, persistence, CLI | `scripts/r4_rebalance_loop.py` | High ⚠ | Primary cause of untestable safety gaps |
| TD-02 | Three parallel audit mechanisms, none authoritative | `execution/events.py`, `live/durable_audit.py`, `production_qual/event_ledger.py` | High ⚠ | Consolidate on one keyed, hash-chained log |
| TD-03 | Rebalance logic implemented twice | `core/rebalance.py`, `scripts/r4_rebalance_loop.py` | High | Two sources of truth for policy |
| TD-04 | State-file sprawl with no schema/version | `reports/r4_loop/*` | High | Inconsistent `.json`/`.jsonl` naming; consumers disagree |
| TD-05 | Dashboard service is a 60 KB procedural module | `dashboard/services/dashboard_state.py` | Medium | Mixes freshness policy, semantics, presentation |
| TD-06 | Config keys documented but not enforced | `configs/production/config.toml`, `config.py` | Medium ⚠ | `max_absolute_weight_error` is recorded but deliberately not a veto (config claims otherwise); `max_chase_attempts`, `max_age_seconds`, `max_cumulative_slippage_bps`, `max_order_frequency`, `rebalance_frequency` have no consumer |
| TD-07 | Duplicated order-request builders with different hard-coded deviation (10 vs 20) | `scripts/r4_rebalance_loop.py:995`, `:2564` | Medium | Consolidate; use config |
| TD-08 | No config schema / unknown-key rejection | `config.py` | Medium | Typos in safety keys are silent |
| TD-09 | 3 xfailed stop-loss tests carrying a real gate defect | `tests/unit/live/test_stop_loss_policy.py` | High ⚠ | Xfail documents but does not fix |
| TD-10 | Stale inline comments contradict code (`1500` vs `5000`, `8` vs `20`) | `scripts/r4_rebalance_loop.py:163-168` | Low | Incident-response hazard |
| TD-11 | Missing governing specs (`SYSTEM_SPECIFICATION.md`, `domain_contracts.md`) | docs | Medium | Claims reference documents that do not exist |
| TD-12 | Unpinned runtime dependencies; Actions referenced by tag | `pyproject.toml`, `.github/workflows/ci.yml` | Medium | Non-reproducible builds |
| TD-13 | Deprecated shim modules (`execution/reconciliation`, `live/alerts`) | `src/eigencapital/` | Low | Remove after callers migrate |
| TD-14 | In-memory per-IP rate limiter | `dashboard/api/app.py` | Low | Multi-worker multiplies limits |
| TD-15 | Research registry is mutable with `delete()` and dead freeze code | `research/experiments/registry.py` | Medium ⚠ | Undermines evidence immutability |
| TD-16 | Simulation executors importable from production modules | research/alpha executors | Medium ⚠ | Latent evidence-fabrication path |
| TD-17 | No unified alerting for "safety disabled" / "recon not persisted" | operations | Medium | Silent degradation |
| TD-18 | Local CSV ATR source for catastrophic stops may be stale | `scripts/r4_safety_supervisor.py` | Low–Medium | Document freshness tolerance |
| TD-19 | Shadow/paper/fidelity code included but not exercised in CI against live semantics | `fidelity/`, `micro_live/`, `shadow/` | Low | Clarify intended use |
| TD-20 | Large untracked research/data surface increases blast radius of accidental commits | repo root | Low | Enforced partly by repo-hygiene CI |

## Suggested sequencing

1. **TD-01/TD-02/TD-04 together** — extracting an orchestrator and one persistence/audit layer is cheaper than fixing each gap in the script.
2. **TD-06/TD-07/TD-08** — make config authoritative, then delete documentation claims that are not enforced.
3. **TD-03** — delete one rebalance implementation after TD-01.
4. Cosmetic items (TD-10, TD-13, TD-14) opportunistically.
