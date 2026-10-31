# EC-AUDIT-001 — R4 Identity Decision Record

**Status:** `APPROVED — ALTERNATIVE A`
**Decision owner (role):** Repository owner — authorized decision owner for the R4 strategy identity
**Decision owner (identity):** The operator who issued the Unit 1 remediation authorization in this session. No individual legal name was provided in-session; it is intentionally not fabricated.
**Approval date:** 2026-10-31
**Approval channel:** Direct authorization by the repository owner in the controlled remediation session (Unit 1).
**Supersedes:** The prior description of this record as `DRAFT — AWAITING EXPLICIT APPROVAL` (the record was not present in the repository or in Git history at the time of this remediation; see Provenance below).

---

## 1. Decision

Alternative A is approved:

1. `signal_vol_scale_reference = 0.50` is the **frozen live R4 signal identity**. It is the divisor in the volatility-damping expression `min(realized_vol_60d / 0.50, 1.0)` in `scripts/r4_rebalance_loop.py::compute_r4_signal`.
2. `vol_target_annual = 0.10` is a **separate annual volatility target**. It is declared in the R4 manifest and `StrategyConfig` and loaded into `VOL_TARGET`, but it is **not consumed** by the live R4 signal calculation or the sizing path. It must not be represented as an implemented portfolio-level volatility-targeting mechanism.
3. **No R4 numerical behavior changes.** Signal mathematics, lookback and volatility windows, thresholds, portfolio target construction, position sizing, caps, regime gating, rebalancing semantics, symbol universe, broker execution, risk limits, and capital allocation are unchanged.
4. A production-function fidelity test guards the frozen identity: `tests/unit/test_r4_signal_fidelity.py`.

---

## 2. Verified provenance (Git)

The audit's historical claims were checked against the actual Git history. One claim was **contradicted** and is corrected here.

| Claim | Verified evidence | Status |
|---|---|---|
| `945c9d1` (2026-08-25) had unused `VOL_TARGET = 0.10` and signal divisor `/0.50` coexisting | `git show 945c9d1:scripts/r4_rebalance_loop.py` → line 87 `VOL_TARGET = 0.10`, line 197 `vol_scale = np.minimum(vol60 / 0.50, 1.0)` | VERIFIED |
| `a26499f` introduced `vol_target_annual = 0.10` into configuration | `git show a26499f -- src/eigencapital/config.py` → added `vol_target_annual: float = 0.10`; production TOML added `vol_target_annual = 0.10` | VERIFIED |
| `701ec4f` (2026-09-08) adopted `/0.50` in the shadow parity implementation | `git show 701ec4f -- scripts/r4_shadow_portfolio.py` → `vol_scale = np.minimum(vol60 / 0.50, 1.0)` | VERIFIED |
| `d51eacb` introduced `vol_target_annual = 0.10` in the manifest | **FALSE.** `d51eacb` changes only `src/eigencapital/live/risk.py` and `tests/unit/live/test_risk_unification.py`. The field was already present in the manifest from `f5982e7` (2026-08-24, Phase 1R). | CONTRADICTED — corrected |

Additional provenance:

- `vol_target_annual` first entered `src/eigencapital/fidelity/r4_manifest.py` at `f5982e7` (2026-08-24).
- `0.50` first entered `scripts/r4_rebalance_loop.py` at `945c9d1` (2026-08-25).
- `VOL_SCALE_REFERENCE = 0.50` first entered `scripts/export_r4_trade_stream.py` at `9f146c6` (2026-09-18).
- No qualification record authorizing a change of the live signal reference from `0.50` to `0.10` was found in the repository or Git history.
- `git log --all -S 'EC_AUDIT_001'` and `git log --all -S 'signal_vol_scale_reference'` return no matches; the identifier `signal_vol_scale_reference` did not previously exist as a code symbol.

---

## 3. Implementation map (use / non-use)

| Location | `0.50` | `vol_target_annual = 0.10` |
|---|---|---|
| `scripts/r4_rebalance_loop.py::compute_r4_signal` | Consumed: `min(vol60 / 0.50, 1.0)` with `sqrt(252)`, clip ±0.20, BTC ±0.10 | `VOL_TARGET` assigned at module load; never read |
| `scripts/r4_shadow_portfolio.py` | Consumed: `min(vol60 / 0.50, 1.0)` | Not used |
| `scripts/export_r4_trade_stream.py` | Consumed: `VOL_SCALE_REFERENCE = 0.50` | Not used |
| `scripts/r4_live_orders.py` (quarantined) | — | `VOL_TARGET = 0.10` defined, unused |
| `src/eigencapital/config.py` / `r4_manifest.py` / `configs/production/config.toml` | — | Declared `0.10`; included in identity fingerprints |

---

## 4. Evidence of resolution

- Production-function fidelity test: `tests/unit/test_r4_signal_fidelity.py` (11 tests) — passes; fails if the divisor changes to `0.10` (verified by mutation).
- Documentation clarified: `docs/DOCUMENTATION_SOURCE_OF_TRUTH.md`, `docs/architecture/CONFIGURATION_INVENTORY.md`.
- No production code, configuration value, strategy math, sizing, risk limit, or broker behavior changed.

---

## 5. Residual notes

- The `0.10` annual target remains declared but unwired. Whether to wire it in future is a separate, unapproved decision; it must not be treated as implemented.
- The record path originally cited in the audit (`reports/audits/`) did not exist in the repository at remediation time; this file establishes it.
