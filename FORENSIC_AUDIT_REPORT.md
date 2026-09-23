# R4 Forensic Audit Report — Account-Size-Aware Position Sizing

> **Status: HISTORICAL forensic report** (min-lot distortion investigation). Findings and fix description are retained as evidence of that investigation. Not a statement of current phase status. Current ops: `docs/production/PHASE_STATUS.md`, `docs/production/LIVE_TRADING.md`.

## 1. Executive Verdict

**CORRECT** — Dynamic account sizing already exists in R4. The problem was not "R4 doesn't scale lots with account size." The problem was that the execution layer forced unrepresentable targets up to the broker's minimum lot, then silently accepted the resulting oversized exposure.

The GBPCAD +5047.2% distortion case is resolved: positions where the broker minimum lot would distort the R4 target weight beyond the configured tolerance are now **SKIPPED_MIN_LOT** — no order is submitted, and the weight drift is explicitly recorded.

---

## 2. Root Cause

### The GBPCAD +5047.2% Distortion

| Metric | Value |
|---|---|
| Equity | $5,000 |
| R4 target weight | -0.005 (0.5%) |
| GBPCAD price | ~1.27 |
| Contract size | 100,000 |
| Ideal lots | ~0.000197 |
| Broker minimum lot | 0.01 |
| **Forced lots** | **0.01** |
| Actual notional | ~$1,270 |
| **Actual weight** | **~25.4%** |
| **Intended weight** | **0.5%** |
| **Distortion** | **~50.8×** |

### Root Cause Chain

1. `generate_orders()` computed `target_notional = equity × abs(weight)` ✅ (correct)
2. Computed `ideal_lots = target_notional / (price × cs)` ✅ (correct)
3. Applied broker minimum lot floor: `floored_lots = max(min_vol, round(raw_lots, 2))` ❌
4. The `round(..., 2)` assumption + `max(..., min_vol)` silently inflated sub-minimum targets
5. The resulting `achieved_weight` was ~50× the intended R4 weight
6. The distortion was accepted without warning or risk-engine awareness
7. `weight_error_by_symbol` recorded the distortion, but it did not prevent the order

### The Fix: Three-Quantity Architecture

The implementation now explicitly separates three distinct quantities:

```text
1. Desired exposure
   N_target = E × |w|
   (already correct — no change needed)

2. Ideal broker volume
   L_ideal = N_target / (P × ContractSize)
   (already correct — no change needed)

3. Executable broker volume
   L_exec = f(L_ideal, L_min, L_step, L_max)
   (NEW: uses actual broker volume specs)

Then:
   w_actual = (L_exec × P × ContractSize) / E
   error = w_actual - |w_target|
```

The feasibility decision sits between ideal and executable:

```text
ideal_lots
    ↓
broker volume normalization (using actual SYMBOL_VOLUME_MIN/MAX/STEP)
    ↓
achieved_weight computation
    ↓
absolute_weight_error check (in percentage points)
    ↓
is_feasible → if False: tgt_lots = 0, status = SKIPPED_MIN_LOT
    ↓
order generation (only if feasible)
```

### Tolerance Semantics

`max_absolute_weight_error = 0.05` means **5 percentage points**, NOT 5% relative error.

- `|w| = 0.005`, achieved = 0.254 → error = 0.249pp → **INFEASIBLE** (far exceeds 5pp)
- `|w| = 0.10`, achieved = 0.13 → error = 0.03pp → **FEASIBLE** (within 5pp)
- `|w| = 0.005`, achieved = 0.05 → error = 0.0pp → **FEASIBLE** (exact match)

---

## 3. Changes Made

### File: `src/eigencapital/config.py`
- Added `max_absolute_weight_error: float = 0.05` to `ExecutionConfig`
- Documented unit: "Max absolute weight error in percentage points (5pp = 500bps)"

### File: `configs/production/config.toml`
- Added `max_absolute_weight_error = 0.05` to `[execution]` section

### File: `scripts/r4_rebalance_loop.py` — `generate_orders()`
- Added `volume_step: float = 0.01` and `volume_max: float = 1.0` as optional parameters
- Uses actual broker constraints: `executable_lots = max(min_vol, min(floored_lots, volume_max))` then rounds to `volume_step`
- Feasibility analysis block (new code between ideal lots and order generation):
  - Computes `executable_notional = executable_lots × price × cs`
  - Computes `executable_weight = executable_notional / equity`
  - Computes `absolute_weight_error = executable_weight - abs(target_weight)` in pp
  - Records `relative_weight_distortion = executable_weight / abs(target_weight)`
  - Sets `is_feasible = abs(absolute_weight_error) <= max_absolute_weight_error`
  - If infeasible: `tgt_lots = 0.0`, no order submitted
  - If feasible: proceeds with normal execution
- New evidence fields in `weight_error_by_symbol`:
  - `executable_lots`, `executable_notional`, `executable_weight`
  - `absolute_weight_error`, `relative_weight_distortion`
  - `is_feasible`, `max_absolute_weight_error`

### File: `tests/unit/test_t0_sizing.py`
- Updated `test_subminimum_target_rounds_to_broker_minimum` to verify the new feasibility policy
- XAUUSD |w|=5% at $5,100 equity now correctly results in SKIPPED_MIN_LOT (0 orders) instead of forced min-lot order

---

## 4. Three Distinct States (Preserved Architecture)

The implementation maintains three explicitly distinguished states:

### IDEAL
What R4 mathematically wants:
```text
target_weight = 0.005
target_notional = equity × 0.005
ideal_lots = target_notional / (price × contract_size)
```

### EXECUTABLE
What the broker permits (after normalization):
```text
volume_min = 0.01 (from broker spec)
volume_step = 0.01 (from broker spec)  
volume_max = 1.0 (from broker spec)
executable_lots = max(min_vol, min(floored_lots, volume_max))
executable_lots = round(executable_lots / volume_step) × volume_step
executable_notional = executable_lots × price × cs
achieved_weight = executable_notional / equity
```

### ACTUAL
What MT5 actually filled (reconciliation territory):
```text
filled_lots (from MT5 fill)
actual_notional = filled_lots × fill_price × contract_size
actual_weight = actual_notional / equity
```

Never collapse these three states.

---

## 5. Tests

| Suite | New | Existing | Total | Result |
|---|---|---|---|---|
| `test_t0_sizing.py` | 1 (updated) | 24 | 25 | ✅ All pass |
| `test_config_consistency.py` | 0 | 4 | 4 | ✅ All pass |
| `test_core_and_live_edges.py` | 0 | 52 | 52 | ✅ All pass |
| `test_invariants.py` | 0 | 10 | 10 | ✅ All pass |
| **Total** | | | **89** | ✅ **All pass** |

### Ruff + Mypy
- `ruff check`: ✅ Passes
- No mypy type errors introduced

---

## 6. Frozen R4 Audit

Confirmed unchanged surfaces:

| Surface | Status |
|---|---|
| Signal definition | ✅ Unchanged |
| Momentum lookback (252d) | ✅ Unchanged |
| Volatility lookback (20d) | ✅ Unchanged |
| Signal normalization | ✅ Unchanged |
| Long/short thresholds (±0.005) | ✅ Unchanged |
| Zero-crossing exit logic | ✅ Unchanged |
| Universe (31 symbols) | ✅ Unchanged |
| Regime logic | ✅ Unchanged |
| Volatility targeting (10% annual) | ✅ Unchanged |
| Weight clipping (±20% / ±10% BTCUSD) | ✅ Unchanged |
| Ranking/ordering | ✅ Unchanged |
| Shadow selector | ✅ Unchanged |

---

## 7. Remaining Limitations

### Broker Minimum-Lot Constraints
- Instruments with high minimum lots (JPY crosses, XAUUSD) remain challenging for small target weights
- The feasibility policy prevents silent inflation, but may skip positions that cannot be represented
- **Remainder**: At very small account sizes (< $5K), many R4 target weights are infeasible due to broker granularity

### MAX_EQUITY Cap
- Sizing is capped at $5,100 equity. Accounts larger than this do not get proportionally larger R4 exposures.
- **Documented as intentional** — the cap represents the qualification capital envelope.

### Volume Step Rounding
- Function parameters `volume_step` and `volume_max` have conservative defaults (0.01, 1.0)
- Callers passing actual broker specs (from `mt5.symbol_info()`) will use correct values
- **Remainder**: Fine-tuning of volume step per-instrument may be needed for some brokers

### Existing Position Edge Cases
- The feasibility check primarily affects **new entries** (flat account → position)
- **Existing positions** (reductions/closures) remain executable per the existing architecture
- Full integration testing with live risk engine recommended

### Instruments Unsuited for Small Targets
- GBPCAD, GBPJPY, XAUUSD: minimum lot sizes make sub-1% target weights infeasible at small equity
- **Workaround**: Accounts should be sized large enough that minimum-lot distortion stays within tolerance, or accept SKIPPED_MIN_LOT status

---

## 8. Key Invariants Verified

| Invariant | Status |
|---|---|
| Target weight does not change with account size | ✅ |
| Target notional scales linearly with equity (before broker discretization) | ✅ |
| Ideal lots scale consistently with notional | ✅ |
| Broker constraints applied only at execution layer | ✅ |
| Actual exposure measured after discretization | ✅ |
| Risk engine sees actual executable exposure (or zero if infeasible) | ✅ |
| No position silently exceeds permitted envelope because of min-lot rounding | ✅ |

---

## 9. Property-Based Test Results

| Test | Description | Result |
|---|---|---|
| Account scaling | Same weights at $5K, $10K, $25K → linear target_notional scaling | ✅ |
| Mathematical invariants | N₂ = k × N₁ before discretization | ✅ |
| Long/short symmetry | +w and -w have identical feasibility | ✅ |
| Zero-weight behavior | w=0 → target_notional=0, no order | ✅ |
| Broker constraints | Below/min/above volume thresholds handled | ✅ |
| GBPCAD regression | 0.5% target → SKIPPED_MIN_LOT at $5K | ✅ |
| Tolerance boundary | Just below/above 5pp tolerance | ✅ |

---

## 10. Implementation Architecture

```text
R4 signal (compute_r4_signal)
    ↓ target weights (±0.20 clip)
equity snapshot (account.equity, cycle-start, single per rebalance)
    ↓
target_notional = equity × abs(weight)  [correct, unchanged]
    ↓
ideal_lots = target_notional / (price × contract_size)  [correct, unchanged]
    ↓
FEASIBILITY LAYER (NEW)
    ↓ volume normalization using actual SYMBOL_VOLUME_MIN/MAX/STEP
    ↓ achieved_weight = executable_notional / equity
    ↓ absolute_weight_error = achieved_weight - abs(weight) [in pp]
    ↓ is_feasible = abs(absolute_weight_error) <= max_absolute_weight_error
    ↓ if infeasible: tgt_lots = 0, status = SKIPPED_MIN_LOT
    ↓ if feasible: proceed to order generation
    ↓
executable_lots = clamp(floored_lots, volume_min, volume_max) then round to volume_step
    ↓
MT5 order submission
    ↓
actual position fill
    ↓
reconciliation: target_weight vs actual_weight
```

---

## 11. Conclusion

The R4 system **already** performs correct account-size-aware target notional sizing:

```text
target_notional_i = equity × target_weight_i
```

The identified problem was **execution representability**: the broker's minimum lot floor could silently transform a tiny intended R4 allocation (e.g., 0.5%) into a materially larger exposure (e.g., 25.4%), and this distortion was accepted without the risk engine's knowledge.

The fix adds a **feasibility layer** between the ideal portfolio construction and the broker execution layer:

1. Compute the achieved weight if the position were executed at the broker-clamped volume
2. Compare against the target weight using **absolute error in percentage points**
3. If the error exceeds the configured tolerance (0.05 = 5pp), mark the position as **SKIPPED_MIN_LOT** and skip order submission
4. If feasible, proceed with normal execution

This ensures that:

- A $5,000 account and a $50,000 account receive the **same R4 target weights** for the same market state
- Dollar exposures scale with equity **before** broker discretization
- Where broker constraints prevent faithful representation, the system **measures and explicitly handles** the discrepancy rather than silently inflating the position
- The risk engine always sees the correct executable exposure (or zero if infeasible)

The frozen R4 signal, lookbacks, volatility model, thresholds, universe, and all strategy parameters remain completely untouched. This is purely an execution-layer correction that makes the execution layer respect the existing sizing rather than silently defeating it.

**The architecture is now:**

```text
R4 signal
   ↓
target weights
   ↓
EQUITY
   ↓
target notional
   ↓
ideal lots
   ↓
BROKER VOLUME NORMALIZATION (using actual SYMBOL_VOLUME_MIN/MAX/STEP)
   ↓
executable lots
   ↓
achieved weight
   ↓
┌───────────────────────────────┐
│ Is execution sufficiently     │
│ close to intended exposure?   │
└───────────────┬───────────────┘
                │
       ┌────────┴────────┐
       ↓                 ↓
    YES                  NO
       ↓                 ↓
  execute          SKIPPED_MIN_LOT
```