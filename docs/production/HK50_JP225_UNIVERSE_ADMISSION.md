# Production Universe Admission — HK50 & JP225

**Date:** 2026-09-27
**Action:** Added `HK50` and `JP225` to `[broker.allowed_symbols]` in `configs/production/config.toml`, classified as `indices`.
**Scope:** Universe expansion + repository synchronization only.

---

## 1. What this admission is — and is not

```text
ELIGIBLE ASSET          ✅ HK50 / JP225 are now eligible `[broker.allowed_symbols]` entries
RESEARCH-VALIDATED ASSET ❌ NO — no study covers either symbol
LIVE-TRADING AUTHORIZED  ❌ NO — ordinary downstream gates still apply per cycle
```

These three states are **not** synonymous. Admission to the eligible universe
grants nothing else.

## 2. Lifecycle boundary (unchanged)

```text
KNOWN → ELIGIBLE → DATA AVAILABLE → STRATEGY ELIGIBLE → RISK ELIGIBLE → EXECUTION ELIGIBLE → LIVE
                    ↑ HK50 / JP225 are HERE (eligible), with nothing downstream assumed
```

Per-cycle reality:

- **Data:** the loop sizes only symbols that return D1 bars from the broker.
  No bars → no returns column → no signal weight → no order.
- **Strategy:** frozen R4 ranks the whole eligible universe cross-sectionally;
  an asset enters a target only if its momentum weight survives ranking.
  The R4 formula was not modified.
- **Risk:** all existing gates (position count, notional envelope, min-lot
  feasibility, daily loss, drawdown, fingerprint) apply identically. No new
  limits were invented and none bypassed.
- **Execution:** order generation fails closed on unreadable broker specs;
  min-lot cost above the $5,000 position cap skips the symbol.
- **Dashboard:** the universe view derives from the backend config — both
  symbols render automatically with truthful `NO_LOCAL_DATA` data status.

## 3. Volatility classification: UNASSESSED

Per the volatility-taxonomy governance (`docs/research/VOLATILITY_TAXONOMY_RESEARCH.md`,
frozen baseline `vol_taxonomy_v1`, 34 assets — HK50/JP225 are absent from it):

- No volatility level, regime, persistence, shock behavior, correlation, or
  trade-path characterization exists for either symbol.
- **No volatility category (e.g. "HIGH") is asserted.** Both are recorded as
  `UNASSESSED` until a descriptive characterization is run on real data.
- The frozen research baseline is untouched; this admission does not rewrite it
  (same adjudication pattern as USOIL, `DASHBOARD_CONTRACT.md` §6).

## 4. Unresolved items — fail-closed until verified

| Item | Status | Consequence while unresolved |
|---|---|---|
| Broker min-lot fit vs $5,000 cap | **UNVERIFIED** — requires the live Exness terminal (`scripts/instrument_eligibility.py`, `scripts/account_readiness.py`) | If min-lot cost > cap, the loop silently skips the symbol (existing fail-closed sizing) |
| Broker symbol names on the account | **UNVERIFIED** — MT5 may list e.g. `HK50m`/`JP225m` or different stems | Config uses bare `HK50`/`JP225` (current Exness convention); mismatch ⇒ no data ⇒ no orders |
| Trading sessions | **UNVERIFIED** — `configs/market_schedules/default.toml` entries deliberately assert NO session window | Schedule reports open Mon–Fri without intraday bounds; extend only from verified broker specs |
| Historical OHLC locally | **ABSENT** — no `data/mt5/HK50m_D1.csv` / `JP225m_D1.csv`; no new data source introduced | Offline research/replay tools simply see no history for them; broker-side history governs live signal availability |

## 5. Research governance impact

```text
Trial slots consumed:            0 / 6 (ledger unchanged)
Research verdicts changed:       NO
Frozen research artifacts modified: NO
R4 methodology changed:          NO
```

No research claim of any kind is created by this admission. If either symbol
is ever to be treated as comparable to existing fleet members, the required
first step is a **descriptive data/volatility characterization** — descriptive
only, opening no trial slot by itself, exactly like the existing volatility
taxonomy (`research/volatility/`).

### Phase 2 change-control boundary (flagged for the operator)

`docs/production/PHASE2_CHANGE_CONTROL.md` and `docs/production/PHASE_STATUS.md`
list "R4 universe frozen" / "No universe expansion" as 🔒 LOCKED during
Phase 2. This admission leaves the frozen R4 identity untouched —
`src/eigencapital/fidelity/r4_manifest.py` (15-symbol research universe), the
R4 manifest fingerprint, signal math, cadence, sizing and exits are unchanged
and still pinned by tests — and follows the production-admission pattern
already used for USOIL, XAGUSD and XNGUSD (`[broker.allowed_symbols]`
eligibility ≠ frozen research universe).

Operator-visible effect to acknowledge: the live loop ranks the whole
broker-eligible universe cross-sectionally (`R4_SYMBOLS` derives from
`[broker.allowed_symbols]`), so once the broker returns HK50/JP225 D1 bars,
the frozen formula ranks two additional candidates. The formula does not
change; the candidate set does. If the Phase-2 freeze is meant to cover
eligibility admissions (not only the frozen research identity), that
interpretation must be resolved by the operator before the next T0
regeneration — this document does not adjudicate it.

## 6. Repository synchronization record

Authoritative change:

- `configs/production/config.toml` — HK50/JP225 added as `indices` (37 entries, 7 `forex_excluded` → 30 tradeable)

Derived/classification layers synchronized:

- `src/eigencapital/live/portfolio_analytics.py` — `ASSET_CLASS_MAP`
- `src/eigencapital/shadow/portfolio/exposure.py` — factor groups now **derived** from the canonical asset-class map (+ explicit FX currency logic and BTC/ETH equity-beta exceptions); the shadow layer's inline `SINGLE_LEG_ASSET_CLASS`/`FACTOR_GROUP` symbol lists were removed, so future universe admissions propagate automatically (drift-guarded by `test_shadow_classification_derived_from_canonical_map`)
- `src/eigencapital/live/risk_observation.py` — sector and correlation grouping now **derive** from canonical `classify_asset_class` (token lists deleted; fixes stale USTEC→OTHER and the substring misfiling that bucketed XAUUSD/XNGUSD/BTCUSD as FX — they contain "USD")
- `src/eigencapital/production_qual/evidence_orchestrator.py` — class-exposure buckets (fx/commodity/index) now **derive** from canonical `classify_asset_class` (USTEC/US500/HK50/JP225 previously fell out of every bucket; XAUUSD/XNGUSD/BTCUSD were bucketed as FX)
- `configs/market_schedules/default.toml` — schedule entries, sessions UNVERIFIED
- Operational scripts: `instrument_eligibility.py`, `account_readiness.py`, `capture_t0.py` now **derive** their universe from config via the shared helper `scripts/_universe.py` (inline symbol copies deleted — the historical drift that left USTEC/USOIL/XNGUSD missing from script lists cannot recur); `r4_live_orders.py` and the `r4_rebalance_loop.py` shadow prefix map synchronized (the prefix fallback now matches index names in full — a 3-char prefix slice could never equal `US30`/`HK50`/`JP225`)
- `scripts/r4_shadow_portfolio.py` — `NATIVE` documented as a data-availability subset (local D1 CSVs), not an eligibility list
- Dashboard: universe view already derives from config (`_build_universe_view`) — no frontend change; new coverage in `tests/unit/dashboard/test_universe_view.py` (both symbols render as admitted indices, `NO_LOCAL_DATA` never rendered as a value, non-config symbols stay flagged research-only)
- Classification regression tests: sector breakdown (`test_core_and_live_edges.py`) and evidence class buckets (`test_phase2_economics.py`) prove XAUUSD→metals, BTCUSD→crypto, HK50/JP225→indices, EURUSD→forex through the canonical classifier

Deliberately unchanged (frozen / historical / separate environments):

- `src/eigencapital/fidelity/r4_manifest.py` (15-symbol frozen research universe)
- `docs/research/VOLATILITY_TAXONOMY_RESEARCH.md`, `research/volatility/config.py` (34-asset baseline)
- `docs/research/RESEARCH_PROGRAM_STATUS.md` and all dated `docs/audits/*`
- `configs/{paper,research,development}/config.toml`

## 7. Verification debt (before either symbol can trade)

1. Run `python scripts/instrument_eligibility.py` against the live terminal —
   confirm min-lot notional fits the $5,000 position cap.
2. Run `python scripts/account_readiness.py` — confirm the broker recognizes
   the exact symbol names.
3. Re-run `python scripts/r4_generate_t0.py` (config fingerprint changed with
   the universe edit — `--verify-config` will report T0 drift by design until
   then).
4. After ≥1 trading week of observed broker-side data, run a descriptive
   volatility/data characterization and update this record's §3 from
   `UNASSESSED` to the observed classification — with no trading-value claims.

## 8. Optional improvements (not required for admission)

- **Universe observability:** expose `DashboardStateService.get_data_status()`
  (config-derived universe view — currently *not* wired to any `/api/v1`
  route) behind a read-only endpoint + DTO, with a lineage row in
  `docs/production/DASHBOARD_DATA_TRUTH_MATRIX.md`, if `Universe: 30 eligible /
  fingerprint / config version` visibility is wanted in the dashboard.
  Do not render any per-symbol performance or volatility value for
  HK50/JP225 while §3 remains `UNASSESSED`.
- **Derived asset-class views — DONE:** operational scripts derive from config
  (`scripts/_universe.py`), the shadow exposure layer derives from the
  canonical map, and the remaining independent classifiers now do as well:
  `production_qual/evidence_orchestrator.py` (class-exposure buckets) and
  `live/risk_observation.py` (sector + correlation grouping) both call
  `classify_asset_class` from `live/portfolio_analytics.py`, so future
  universe admissions propagate to every diagnostic automatically.
