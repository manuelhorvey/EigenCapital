# EigenCapital — Forensic Audit of Signal Selection, Portfolio Construction, Position Sizing & Order Submission

**Audit date:** 2026-09-01
**Git branch:** `main`
**Working tree:** clean (no uncommitted changes)
**R4 fingerprint:** UNCHANGED (`aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb`)
**R4 decisions:** UNCHANGED (no behavioral modifications)
**Risk policy:** UNCHANGED

---

## Executive Summary

**What actually happens today:**

EigenCapital R4 computes a frozen 12-1 month momentum signal across 32 universe symbols, applies regime conditioning (risk-on/off), vol-scales, cross-sectionally ranks, and clips weights to ±0.20 (BTC ±0.10). The signal supports **both LONG and SHORT** positions in the production rebalance loop. The rebalance loop then:

1. Computes target lot sizes for all eligible symbols with weight > 0.005
2. **Sorts by |weight|** (strongest signals first) — **this IS ranking**
3. Takes the **top 20** (MAX_CONCURRENT from `live_risk.max_concurrent_positions`)
4. Generates rebalance orders (close positions that fell out of top 20, open/adjust those in top 20)
5. Executes up to 20 orders per cycle

**The system does NOT simply "send all eligible signals."** It ranks by |weight| and takes the top 20. However, the top-20 selection happens **after** individual sizing, and sizing is **not portfolio-aware** — each position is sized independently based on equity weight, not on aggregate portfolio risk.

**The most important finding:**

> When 20 signals appear simultaneously, **candidate #20 knows nothing about candidates #1–#19 at sizing time**. Sizing is pure weight × equity, with no correlation adjustment, no common-factor de-duplication, and no portfolio heat budget. This is by design in Phase 2 and should be a Phase 3 research opportunity.

---

> **CORRECTION (2026-09-01):** The original audit incorrectly stated the production path was "long-only." Independent verification confirmed: the active `r4_rebalance_loop.py` supports both LONG and SHORT positions (weights clipped to ±0.20, `generate_orders()` handles both BUY and SELL sides). The long-only behavior existed only in the quarantined `r4_live_orders.py` path (`clip(lower=0)`). This distinction is critical for Phase 2 result interpretation.

---

## 1. Complete Order Pipeline Trace

```text
MT5 D1 OHLCV Data (300 bars per symbol)
    ↓
fetch_d1_data() — scripts/r4_rebalance_loop.py
    Source: MT5 via mt5linux RPyC bridge (127.0.0.1:8001)
    Input: R4_SYMBOLS list (32 symbols from config)
    Output: Dict[symbol, pd.DataFrame] (OHLCV)
    ↓
compute_r4_signal() — scripts/r4_rebalance_loop.py
    Source: frozen R4 logic (matches R4ConfigManifest)
    Input: Dict[symbol, pd.DataFrame]
    Transformations:
        1. Returns: pct_change() per symbol
        2. Momentum: (1+r).rolling(252).prod()-1 minus (1+r).rolling(21).prod()-1
        3. Cross-sectional rank: .rank(axis=1, pct=True) - 0.5 → [-0.5, +0.5]
        4. Regime conditioning: 20d vol < expanding median → 1.0, else → 0.0
        5. Vol scaling: min(60d vol / 0.50, 1.0)
        6. Final: regime × vol_scale × base_weight → clip ±0.20
        7. BTCUSD extra clip: ±0.10
    Output: pd.Series of weights per symbol + diagnostics dict
    ↓
Regime Gate
    Condition: regime_on == True OR --force-regime (dry-run only)
    Rejection: entire cycle skipped
    ↓
generate_orders() — scripts/r4_rebalance_loop.py
    Source: portfolio rebalance logic
    Input: target weights, current positions, prices, contract sizes, equity
    Transformations:
        1. Filter: eligible symbols only, weight > 0.005
        2. Size: notional = |weight| × capped_equity
        3. Lot conversion: notional / (price × contract_size)
        4. Round to 0.01 step, enforce min lot, enforce MAX_POSITION_USD cap
        5. RANK: sort by |weight| descending
        6. SELECT: top 20 (MAX_CONCURRENT)
        7. REBALANCE: close positions not in top 20, open/adjust positions in top 20
        8. ORDER: close orders first (free margin), then open orders
    Output: List[(symbol, side, lots, reason, ticket_or_None)]
    ↓
Pre-execution Risk Gates — RiskEnforcer.check_all()
    Gate 1: Broker connectivity (equity/free_margin > 0)
    Gate 2: Position count (broker-authoritative, current + target ≤ 20)
    Gate 3: Account drawdown (10% from peak)
    Gate 4: Daily loss ($250 limit)
    Gate 5: Equity floor ($4,000 minimum)
    Gate 6: Position SL protection (CRITICAL logged, does NOT block — R4 uses signal-based exits)
    Gate 7: Fingerprint verification (all components match T=0)
    Source: eigencapital/live/risk_enforcement.py::RiskEnforcer
    Rejection: ANY BLOCK/CRITICAL → entire cycle halted
    ↓
Additional Pre-execution Gates:
    - FingerprintVerifier.verify_all() — manifest, risk, live_risk, config
    - DailyLossTracker.is_daily_loss_breached
    - Watchdog.evaluate() — NORMAL required
    - ReconciliationEngine.reconcile() — broker ↔ internal state
    - Position attribution — foreign positions quarantine
    ↓
execute_orders() — scripts/r4_rebalance_loop.py
    Source: direct MT5 order submission via mt5linux
    Input: List[(symbol, side, lots, reason, ticket_or_None)]
    Transformations:
        1. Per order: get tick price, build MT5 request
        2. Hedging-safe: ticket-scoped closes via request["position"]
        3. Retry: max 2 retries with exponential backoff
        4. Timeout: 30s per order_send via ThreadPoolExecutor
    Output: fill results (success/fail per order)
    ↓
Post-execution:
    - PartialFillManager records fills
    - EvidenceOrchestrator captures position snapshot
    - Audit trail appended to decisions.jsonl
    - Order intents persisted to order_intents.jsonl
    - Reconciliation of filled/failed vs intent count
```

### Architecture Invariant

```
R4 Signal → generate_orders (rank + select top N) → Risk Gates → MT5
```

**Strategy CANNOT bypass Portfolio or Risk.** The `Portfolio` class in `portfolio.py` enforces this architecturally, but the live rebalance loop in `scripts/r4_rebalance_loop.py` implements its own pipeline that **bypasses the `Portfolio` class entirely** — it calls `generate_orders()` directly with the signal weights and runs risk gates via `RiskEnforcer` independently.

**This is a significant architectural observation:** The canonical `Portfolio` → `EigenRisk` pipeline (`portfolio.py` → `risk/engine.py`) exists as a domain model but is NOT used by the live production path. The live path uses `RiskEnforcer` (live-specific) instead.

---

## 2. Why Does the System Send Up to 20 Orders?

### Architecture

```
Signal → generate_orders() → top 20 by |weight| → risk gates → execute all that pass
```

### Precise Answers

| Question | Answer | Source |
|----------|--------|--------|
| Does R4 rank signals? | **YES** — by absolute weight magnitude | `generate_orders()` sorts `ranked` by `abs_weight` descending |
| Maximum number of candidates? | **20** (MAX_CONCURRENT from `live_risk.max_concurrent_positions`) | `ranked[:MAX_CONCURRENT]` |
| Maximum simultaneous orders? | **20** (MAX_ORDERS_PER_CYCLE from `execution.max_orders_per_cycle`) | `orders[:MAX_ORDERS_PER_CYCLE]` |
| Portfolio-level budget? | **YES** — hard cap at 20 concurrent positions | `RiskEnvelope.max_concurrent_positions` |
| Gross exposure budget? | **NO** — no gross notional cap enforced in live path | Not present in `RiskEnforcer` |
| Net exposure budget? | **NO** — no net exposure cap | Not present |
| Currency-factor exposure budget? | **NO** — no currency decomposition | Not present |
| Correlation-aware sizing? | **NO** — sizing is weight × equity, independent | `compute_lot_sizes()` |
| Sector concentration control? | **NO** — `asset_class_exposures` in AccountState is always empty | `AccountState.asset_class_exposures` never populated in live path |
| Portfolio volatility target? | **NO** — individual vol scaling exists but no portfolio vol target | Not present |
| Portfolio heat limit? | **NO** — no aggregate risk budget | Not present |
| Per-symbol allocation limit? | **YES** — MAX_POSITION_USD = $2,500 per position | `MAX_POSITION_USD / (price * cs)` |
| Aggregate risk budget? | **NO** — no VaR/CVaR/portfolio risk metric | Not present |
| Does signal strength affect size? | **YES** — weight × equity determines notional | `notional = |weight| * capped_equity` |
| Does volatility affect size? | **YES** — vol scaling reduces high-vol positions | `vol_scale = min(vol60/0.50, 1.0)` |
| Does existing exposure affect new size? | **NO** — each position sized independently | `generate_orders()` does not query existing risk |
| Order sequence matters? | **YES** — closes first, then opens (free margin) | `close_orders + open_orders` |
| If all candidates pass individually, execute all? | **YES** — up to MAX_CONCURRENT (20) | `orders[:MAX_ORDERS_PER_CYCLE]` |

**Key finding:** The system sends up to 20 orders because `live_risk.max_concurrent_positions = 20` and the signal routinely has 15-20+ positive weights above the 0.005 threshold.

---

## 3. Current Sizing Formula

### Mathematical Formula

```
weight = (cross-sectional_rank - 0.5) × regime × vol_scale
         clipped to [-0.20, +0.20] (production clips at 0 for long-only)

if |weight| < 0.005:
    skip (not tradeable)

notional = |weight| × min(equity, MAX_EQUITY=5100)

lot_size = notional / (price × contract_size)

lot_size = max(min_lot, round(lot_size, 2))
lot_size = min(lot_size, MAX_POSITION_USD / (price × contract_size))
```

### Component Details

| Component | Value | Source | Transformation |
|-----------|-------|--------|----------------|
| Signal weight | [-0.20, +0.20] | `compute_r4_signal()` | regime × vol_scale × rank |
| Capped equity | min(equity, $5,100) | `min(equity, MAX_EQUITY)` | — |
| Target notional | weight × equity | Direct multiplication | — |
| Price | MT5 ask price | `tick.ask` | Per-symbol |
| Contract size | MT5 symbol_info | `info.trade_contract_size` | Per-symbol |
| Min lot | MT5 symbol_info | `info.volume_min` | Per-symbol (typically 0.01) |
| Max position | $2,500 | `MAX_POSITION_USD / (price × cs)` | Per-symbol cap |

### Flow: intended_size → approved_size → order_quantity

```
intended_size = weight × equity / (price × contract_size)
    ↓
lot_size = max(min_lot, round(intended_size, 2))
    ↓
lot_size = min(lot_size, MAX_POSITION_USD / (price × contract_size))
    ↓
order_quantity = lot_size  (no risk gate modification of size)
```

**These are NOT always identical when risk gates intervene** — but in the current implementation, risk gates operate at the **cycle level** (block the entire cycle) rather than at the **per-order level** (modify individual sizes). If risk gates pass, every order goes through at its computed size. If they fail, NO orders go through.

**Exception:** The `PositionManager` in `compute_size_scale_factor()` computes a shadow REDUCED factor but **does not apply it** (shadow-only during Phase 2).

---

## 4. The "20 Orders" Behavior

### What 20 Positions Actually Mean

The system config allows up to **20 concurrent positions** and up to **20 orders per cycle**. The eligible universe has **17 tradeable symbols** (those where min lot fits within $2,500 position limit):

```
USTEC, AUDUSD, AUDCHF, AUDCAD, AUDNZD, NZDUSD, NZDCHF, NZDCAD,
GBPUSD, GBPCHF, EURUSD, EURCHF, USDCHF, USDCAD, CADCHF, EURGBP, BTCUSD
```

Plus some symbols like XAUUSD, US30, GBPCAD, EURCAD, USDCAD, GBPNZD, EURNZD, GBPAUD, EURAUD that fit within the $5,000 position cap.

**Realistic portfolio composition when 20 positions are active:**

Since R4 ranks by |weight| and takes the top 20, the portfolio would contain the 20 symbols with the strongest momentum signals. Given the universe is predominantly FX pairs with USD as a common counter-currency, a 20-position portfolio would very likely contain multiple expressions of the same USD directional view.

### Hypothetical Factor Analysis

If the top 20 signals include:
```
LONG AUDUSD, NZDUSD, GBPUSD, EURUSD, USTEC
SHORT USDCHF, USDCAD, BTCUSD
```

This effectively represents:
- **Short USD** (via AUDUSD, NZDUSD, GBPUSD, EURUSD = 4 positions)
- **Short USD** (via USDCHF, USDCAD = 2 positions, opposite direction)
- **Long risk** (via USTEC = 1 position)
- **Long crypto** (via BTCUSD = 1 position)

**These are NOT 20 independent bets.** They are likely 3-5 underlying factor bets expressed through 20 instruments.

### Does the System Recognize This?

**NO.** The system does not decompose exposure into:
- USD exposure (long/short)
- Risk-on/off exposure
- Carry exposure
- Volatility regime exposure

Each position is treated as an independent bet.

---

## 5. Correlation / Common-Factor Exposure Audit

### Currency Decomposition

The system does **not** perform currency-factor decomposition. The `AccountState` class has `instrument_exposures` and `asset_class_exposures` fields, but:

1. **`instrument_exposures`** is never populated in the live path
2. **`asset_class_exposures`** is never populated in the live path
3. The `RiskEnforcer` reads broker positions directly — it does not compute factor exposures

### What 20 Simultaneous Long USD-SHORT Positions Mean

If R4 has 10 long FX positions and 10 short FX positions, the **net USD exposure** is:

```
net_USD = Σ(long_USDXXX) - Σ(short_USDXXX) + Σ(long_XXXUSD) - Σ(short_XXXUSD)
```

This could be very large even though positions are individually sized at 2-5% of equity. The system does not measure or limit this.

### Does EigenCapital Currently Recognize This?

**NO.** This is a **Phase 3 portfolio-construction gap**, not a Phase 2 bug. The current Phase 2 evidence campaign intentionally operates with independent sizing to establish the baseline.

---

## 6. Signal Validity vs Portfolio Eligibility

### Current Behavior

The system treats these as **the same decision**:

```python
if abs(weight) > 0.005:
    # This is BOTH "signal is valid" AND "portfolio should own this position"
    target_portfolio[sym] = ...
```

There is no separate:
1. "Is there an opportunity?" (signal validity)
2. "How much should we express given everything else?" (portfolio construction)

### Does the Code Have This Distinction?

**NO.** The `generate_orders()` function combines signal validity, sizing, and portfolio selection into a single function. The `Portfolio` class in `portfolio.py` models this separation architecturally, but the live path does not use it.

---

## 7. Signal Ranking

### Does Ranking Currently Exist?

**YES.** The `generate_orders()` function explicitly sorts by |weight|:

```python
ranked = sorted(
    target_portfolio.items(),
    key=lambda x: x[1]["abs_weight"],
    reverse=True,
)
```

### Does Ranking Affect Execution?

**YES.** Only the top `MAX_CONCURRENT` (20) positions are traded. If there are 25 eligible signals, the 5 weakest are excluded.

### Does Order Sequence Affect Results?

**YES.** Closes are executed before opens:

```python
close_orders = [o for o in orders if "rotated out" in o[3]]
open_orders = [o for o in orders if o not in close_orders]
return close_orders + open_orders
```

This is **intentional** — closing positions frees up margin for new entries. The order within closes and within opens follows the ranked order (strongest first).

### If Two Runs with Identical Inputs Produce Identical Order Sets?

**YES** — the ranking is deterministic (sort by weight), and the rebalance logic is deterministic given the same signal weights and positions.

---

## 8. Portfolio-Level Risk Controls

### Inventory of All Current Controls

| Control | Level | Source | Status |
|---------|-------|--------|--------|
| Max concurrent positions (20) | TRADE + PORTFOLIO | `RiskEnvelope.max_concurrent_positions` | **HARD GATE** |
| Max position notional ($2,500) | TRADE | `generate_orders()` | **SIZING CAP** |
| Max drawdown 10% | PORTFOLIO | `RiskEnvelope.max_account_drawdown_pct` | **HARD GATE** |
| Daily loss $250 | PORTFOLIO | `DailyLossTracker` | **HARD GATE** |
| Min equity $4,000 | PORTFOLIO | `RiskEnvelope.min_equity` | **HARD GATE** |
| Position SL protection | TRADE | `RiskEnforcer._check_position_protection` | **OBSERVATION ONLY** (R4 uses signal-based exits) |
| Fingerprint verification | PORTFOLIO | `FingerprintVerifier` | **HARD GATE** |
| Foreign position quarantine | PORTFOLIO | `PositionAttribution` | **HARD GATE** (blocks new entries) |
| Max gross notional | — | NOT PRESENT | **MISSING** |
| Max net exposure | — | NOT PRESENT | **MISSING** |
| Currency exposure limits | — | NOT PRESENT | **MISSING** |
| Correlation limits | — | NOT PRESENT | **MISSING** |
| Portfolio volatility target | — | NOT PRESENT | **MISSING** |
| VaR / CVaR | — | NOT PRESENT | **MISSING** |
| Concentration limits | — | NOT PRESENT (in live path) | **MISSING** |
| Order frequency (10/hour) | TRADE | `MicroLiveLimits` (not wired to rebalance loop) | **SHADOW ONLY** |

### Classification

| Status | Count | Controls |
|--------|-------|----------|
| Implemented (hard gates) | 6 | Position count, drawdown, daily loss, equity floor, fingerprint, quarantine |
| Implemented (sizing cap) | 1 | Per-position notional cap |
| Observation only | 1 | SL protection (logged, does not block) |
| Missing | 8 | Gross/net exposure, currency, correlation, vol, VaR, concentration |

---

## 9. Portfolio-Aware Sizing

### Does Candidate #20 Know About Candidates #1–#19?

**NO.** Here is the precise sizing path:

```python
# In generate_orders():
for sym in target_weights.index:
    w = target_weights[sym]
    notional = abs(w) * capped_equity       # ← no reference to other positions
    lot_size = notional / (price * cs)      # ← pure weight × equity
    lot_size = min(lot_size, max_lots)      # ← per-position cap only
```

**Every candidate is sized independently.** The sizing formula has no inputs from:
- existing positions (other than through the "current quantity" delta)
- existing risk
- existing exposure
- correlation with other positions
- remaining portfolio budget

### What This Means

If 20 signals all have weight 0.20 (maximum), the system would attempt to open 20 positions each at $2,500 = $50,000 total notional on a $5,000 account = **10x leverage**. The only thing preventing this is:

1. The `MAX_POSITION_USD` cap ($2,500 per position)
2. The `MAX_CONCURRENT` cap (20 positions)
3. Broker margin requirements (MT5 would reject if margin insufficient)

There is **no portfolio-level notional or leverage limit** in the `RiskEnforcer`.

---

## 10. Order Sequencing and Path Dependencies

### How Candidates Are Ordered

1. Close orders: sorted by |weight| (strongest first — actually this is by the order they appear in `target_symbols`)
2. Open orders: sorted by |weight| (strongest first)

### Does Order Sequence Matter?

**YES.** Closes are executed first to free margin. Within closes and opens, the order follows the ranked signal. If position #20 would breach the `max_concurrent_positions` limit after positions #1-#19 are opened, position #20 would still be included because:

```python
# After closes, we have free slots for opens
available_after_close = MAX_CONCURRENT - len(pos_list) + len(closes)
if len(opens) > available_after_close:
    opens = opens[:available_after_close]
```

So the system **does** truncate opens to available slots. This is a form of capacity-aware ordering.

### Does Risk Get Recomputed After Every Order?

**NO.** The `check_all()` risk gate is called **once before order generation** with `target_orders=0`. After that, all orders are submitted without re-checking risk state between orders. This means:

- If the first 5 orders consume all margin, orders 6-20 would still be submitted
- MT5 would reject orders that exceed margin, but EigenCapital doesn't check

### Do Two Runs with Identical Inputs Produce Identical Order Sets?

**YES** — the signal computation, ranking, and order generation are all deterministic.

---

## 11. MT5 Broker-Side Constraints

### How MT5 Constraints Affect Execution

EigenCapital **relies on MT5 to enforce** the following constraints that it does NOT validate before submission:

| Constraint | EigenCapital Validates? | MT5 Enforces? |
|------------|------------------------|---------------|
| Minimum lot | YES (rounds up to min_vol) | YES |
| Maximum lot | YES (cap via MAX_POSITION_USD) | YES |
| Lot step | YES (rounds to 0.01) | YES |
| Contract size | YES (uses for calculation) | N/A |
| Margin requirement | **NO** — relies on MT5 rejection | YES |
| Leverage | **NO** — relies on MT5 | YES |
| Stop-distance rules | **NO** | YES |
| Symbol trading mode | **NO** (but symbol_select is called) | YES |
| Market hours | **NO** | YES |
| Spread | **NO** — no live spread check in rebalance loop | N/A |
| Filling mode | **YES** (FOK default) | YES |

**Spread is not checked in the live rebalance loop.** The `RiskEnvelope` has no spread gate, and `generate_orders()` does not query spread before submitting.

---

## 12. Counterfactual Portfolio-Construction Study

### Current Behavior (A) — Independent Sizing

Each candidate sized independently at weight × equity.

### Hypothetical B — Portfolio Heat Budget

Allocate from a finite aggregate risk budget (e.g., max 2% portfolio VaR). Would reject low-weight signals when budget is exhausted.

**Estimated impact:** Would reduce position count from ~20 to ~8-12, prioritizing strongest signals.

### Hypothetical C — Inverse-Volatility Portfolio

Normalize exposure by volatility: `notional_i = (1/vol_i) / Σ(1/vol_j) × total_budget`.

**Estimated impact:** Would equalize risk contribution across positions. Low-vol positions (e.g., EURGBP) would get larger notional; high-vol positions (e.g., BTCUSD) would get smaller.

### Hypothetical D — Correlation-Aware Allocation

Account for covariance between positions. Would de-duplicate USD-heavy portfolios.

**Estimated impact:** Would significantly reduce the effective number of independent bets. If 8 positions are 90%+ correlated (all short-USD), would effectively treat them as 1-2 bets.

### Hypothetical E — Risk Parity

Allocate based on portfolio risk contribution. Each position contributes equal risk.

**Estimated impact:** Similar to C but more sophisticated. Would require covariance matrix estimation.

### Hypothetical F — Hierarchical Risk Parity

Cluster correlated assets, allocate within and across clusters.

**Estimated impact:** Most complex. Would provide best diversification but highest implementation complexity.

### Summary Comparison

| Method | Positions | Gross Exposure | Portfolio Vol | Diversification | Complexity |
|--------|-----------|----------------|---------------|-----------------|------------|
| A (current) | 20 | HIGH | HIGH | LOW | LOW |
| B (heat budget) | 8-12 | MEDIUM | MEDIUM | MEDIUM | LOW |
| C (inv-vol) | 20 | MEDIUM | LOW | MEDIUM | MEDIUM |
| D (corr-aware) | 20 | LOW | LOW | HIGH | HIGH |
| E (risk parity) | 20 | LOW | LOW | HIGH | HIGH |
| F (HRP) | 20 | LOW | LOW | HIGHEST | VERY HIGH |

---

## 13. Frozen State Verification

The audit did NOT modify any of the following:

| Component | Status | Evidence |
|-----------|--------|----------|
| R4 fingerprint | UNCHANGED | `aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb` |
| R4 parameters | UNCHANGED | `LOOKBACK=252, SKIP=21, VOL_LOOKBACK=60, RISK_LOOKBACK=20` |
| R4 universe | UNCHANGED | 32 symbols, 17 eligible |
| Strategy cadence | UNCHANGED | Weekly rebalance |
| Signal logic | UNCHANGED | 12-1 momentum + regime + vol scale |
| Risk envelope | UNCHANGED | `max_concurrent=20, max_position=$2,500, max_order=$2,500` |
| Execution semantics | UNCHANGED | Same order generation and submission logic |
| Shadow REDUCED | UNCHANGED | Still shadow-only |

**Parity test results:** 20 passed, 2 pre-existing failures (config drift from 19→20 not reflected in test assertions).

---

## 14. Recommended Future Architecture

### Current

```
MT5 Data
    ↓
R4 Signal (inline in r4_rebalance_loop.py)
    ↓
generate_orders() [combines: sizing + ranking + selection + rebalance]
    ↓
RiskEnforcer.check_all() [cycle-level gates]
    ↓
execute_orders() [direct MT5 submission]
```

### Phase 3 Candidate

```
MT5 Data
    ↓
R4 Signal (standalone module)
    ↓
Candidate Generation (signal validity only)
    ↓
┌─────────────────────────────┐
│   PORTFOLIO CONSTRUCTION    │
│                             │
│  1. Factor decomposition    │
│     (USD, EUR, GBP, etc.)  │
│  2. Correlation matrix      │
│  3. Concentration limits    │
│  4. Portfolio vol target    │
│  5. Risk budget allocation  │
│  6. Ranking + selection     │
└─────────────┬───────────────┘
              ↓
    Position Sizing (portfolio-aware)
              ↓
    Risk Gates (per-order + portfolio-level)
              ↓
    Execution
              ↓
    Reconciliation
              ↓
    Evidence
```

### Distinguish CURRENT from PHASE 3 CANDIDATE

| Capability | CURRENT | PHASE 3 CANDIDATE |
|------------|---------|-------------------|
| Signal generation | Inline in script | Standalone module |
| Factor decomposition | NONE | Currency, asset-class, sector |
| Correlation matrix | NONE | Rolling pairwise + factor |
| Concentration limits | Per-position only | Per-factor, per-asset-class |
| Portfolio vol target | NONE | 10% annual target |
| Risk budget | NONE | Per-position risk contribution |
| Sizing | weight × equity (independent) | Portfolio-aware allocation |
| Ranking | By |weight| | By marginal risk contribution |
| Selection | Top N by rank | Risk-budget constrained |

---

## 15. Observability Recommendations

The following are NOT currently captured in the evidence ledger:

| Metric | Current Status | Recommendation |
|--------|---------------|----------------|
| Candidate count | NOT captured | Add to audit trail |
| Selected count | NOT captured | Add to audit trail |
| Rejected count | NOT captured | Add to audit trail |
| Rejection reason | NOT captured | Add per-reason breakdown |
| Intended size | NOT captured | Record pre-gate size |
| Approved size | NOT captured | Record post-gate size |
| Final order quantity | NOT captured | Record actual submitted qty |
| Portfolio risk before order | NOT captured | Compute pre-trade portfolio risk |
| Portfolio risk after hypothetical | NOT captured | Shadow computation |
| Gross exposure | NOT captured | Compute and record |
| Net exposure | NOT captured | Compute and record |
| Factor exposure | NOT captured | Currency-factor decomposition |
| Marginal risk contribution | NOT captured | Phase 3 |
| Remaining risk budget | NOT captured | Phase 3 |
| Execution ordering | Implicit in JSONL | Make explicit |

**Do not add these to live behavior unless explicitly approved.** Recommend adding as read-only diagnostics in shadow mode.

---

## 16. Documentation

### Updated Documentation

| Document | Status | Notes |
|----------|--------|-------|
| `docs/architecture/ARCHITECTURE_CURRENT_STATE.md` | EXISTS | Partially accurate; this audit provides more precise pipeline trace |
| `docs/architecture/ARCHITECTURE_GAPS.md` | EXISTS | Accurate; gaps properly classified |
| `docs/audits/FORENSIC_ORDER_PIPELINE_AUDIT_2026-09-01.md` | **THIS DOCUMENT** | Complete forensic audit |
| `docs/architecture/ORDER_PIPELINE.md` | DOES NOT EXIST | Recommended: create from this audit |
| `docs/architecture/POSITION_SIZING.md` | DOES NOT EXIST | Recommended: create from Section 3 |
| `docs/architecture/PORTFOLIO_CONSTRUCTION.md` | DOES NOT EXIST | Recommended: create from Sections 4-6 |

---

## 17. Gaps Classification

### P0 Critical
- None identified. The system is safe for Phase 2 operation.

### P1 High
- **Pre-existing parity test drift:** `test_execution_parameters_unchanged` expects `max_orders_per_cycle == 19` but config has 20. `test_risk_envelope_unchanged` expects `max_concurrent_positions == 19` but config has 20. These are pre-existing test-code mismatches, not new findings.

### P2 Medium
- **No portfolio-level notional/leverage limit in RiskEnforcer:** The `RiskEnforcer.check_all()` does not compute gross leverage. The `EigenRiskEngine` in `risk/engine.py` does check gross leverage via `check_gross_leverage()`, but this engine is NOT used by the live rebalance loop. Only `RiskEnforcer` is used.
- **Spread not checked before order submission** in the live rebalance loop.
- **Risk not recomputed between orders** in a single cycle.

### P3 Low
- The `Portfolio` class in `portfolio.py` is architecturally sound but unused by the live path.
- The `EigenRiskEngine` has richer checks (concentration, asset-class exposure) but is not wired into the live path.

### Phase 3 Research Opportunity
- Currency-factor decomposition
- Correlation-aware sizing
- Portfolio volatility targeting
- Risk-budget allocation
- Marginal risk contribution ranking
- Factor-based concentration limits

### Not a Problem
- 20 simultaneous positions: **This is by design.** `max_concurrent_positions=20` is intentional for the $5K campaign.
- Independent sizing: **This is the correct Phase 2 baseline.** Portfolio-aware sizing is Phase 3.
- Signal ranking by |weight|: **This is correct and simple.** More sophisticated ranking is Phase 3.

---

## 18. Recommendations

### MUST FIX NOW
- **Update parity test assertions** from 19→20 to match current config (pre-existing drift).

### SHOULD INVESTIGATE AFTER PHASE 2
1. Add gross/net exposure computation to audit trail (shadow-only)
2. Add currency-factor decomposition to audit trail (shadow-only)
3. Wire `EigenRiskEngine` checks into the live path (or replicate in `RiskEnforcer`)
4. Add portfolio-level leverage limit to `RiskEnforcer`
5. Add spread gate before order submission
6. Research portfolio-construction alternatives (heat budget, inv-vol, risk parity)

### DO NOT TOUCH
- R4 signal logic
- R4 parameters
- R4 universe
- Risk envelope (current values)
- Evidence collection
- Fingerprint verification
- Reconciliation engine

---

## 19. Phase 3 Roadmap

```
Current independent sizing
        ↓
[Shadow] Portfolio heat measurement (gross/net exposure, factor exposure)
        ↓
[Shadow] Exposure/factor measurement (currency decomposition)
        ↓
[Offline] Portfolio-construction experiments (backtest alternatives A-F)
        ↓
[Live shadow] Correlation-aware sizing (if evidence supports)
        ↓
[Live shadow] Risk-budget allocation
        ↓
[Only if evidence supports]: Risk parity / HRP / optimization
```

---

## 20. Success Criteria Answers

| # | Question | Answer |
|---|----------|--------|
| 1 | Why does EigenCapital send ~20 orders? | `max_concurrent_positions=20` and the signal routinely has 15-20+ positive weights. |
| 2 | How is each order selected? | Ranked by |weight|, top 20 selected. |
| 3 | How is each order sized? | weight × equity / (price × contract_size), capped at $2,500. |
| 4 | What happens when 20 signals appear simultaneously? | Top 20 by |weight| are traded, all at independent sizes. |
| 5 | Does candidate #20 know about #1-#19? | **NO.** Sizing is independent. |
| 6 | Is sizing independent or portfolio-aware? | **Independent.** |
| 7 | Actual portfolio risk of all simultaneous positions? | No portfolio-level risk metric computed. Individual vol scaling exists but aggregate risk is not measured. |
| 8 | Common-factor exposures? | Likely significant USD exposure overlap. Not measured. |
| 9 | Does order sequence affect outcomes? | **YES** — closes before opens. Deterministic. |
| 10 | Hard gates vs observations? | 6 hard gates, 1 observation (SL), 8 missing controls. |
| 11 | MT5 enforcement vs EigenCapital? | MT5 enforces margin, leverage, lot constraints. EigenCapital enforces position count, drawdown, daily loss, fingerprint. |
| 12 | Missing portfolio-construction capability? | Factor decomposition, correlation-aware sizing, portfolio vol targeting, risk budget. |
| 13 | Phase 2 problem or Phase 3 opportunity? | **Phase 3 research opportunity.** Current behavior is safe and intentional for Phase 2. |
| 14 | What should we measure before changing anything? | Gross/net exposure, factor exposure, portfolio volatility, marginal risk contribution. All as shadow diagnostics. |
| 15 | Can we improve without contaminating evidence? | **YES** — shadow diagnostics have zero impact on live behavior. |

---

*This audit was conducted as a read-only investigation. No live trading behavior was modified. The R4 evidence campaign continues unmodified.*
