# Shadow Analytics — Data Flow Integrity Audit

**Audit date:** 2026-09-01
**Scope:** Full pipeline from MT5 positions through to JSONL evidence
**Status:** All findings documented below

---

## 1. FX Long/Short Factor Sign Conventions

**Status:** ✅ CORRECT

```python
def _compute_currency_exposure(symbol, weight, notional, direction):
    sign = 1.0 if direction == "LONG" else -1.0
    return {base: sign * notional, quote: -sign * notional}
```

Verification:
- LONG EURUSD → +EUR, -USD ✅ (buy EUR, pay USD)
- SHORT EURUSD → -EUR, +USD ✅ (sell EUR, receive USD)
- LONG USDCHF → +USD, -CHF ✅ (buy USD, pay CHF)
- SHORT USDCHF → -USD, +CHF ✅ (sell USD, receive CHF)

Sign convention is consistent: **positive = long that currency, negative = short that currency**.

---

## 2. USD Decomposition for EURUSD vs USDCHF

**Status:** ✅ CORRECT

| Position | USD Exposure | Correct? |
|----------|-------------|----------|
| LONG EURUSD | -notional (quote is USD, selling USD) | ✅ |
| SHORT EURUSD | +notional (quote is USD, buying USD) | ✅ |
| LONG USDCHF | +notional (base is USD, buying USD) | ✅ |
| SHORT USDCHF | -notional (base is USD, selling USD) | ✅ |

If R4 has both LONG EURUSD and LONG USDCHF, the USD exposures partially cancel — correctly reflecting that these are opposing USD bets.

---

## 3. Contract-Size/Notional Calculations

**Status:** ✅ CORRECT

```python
notional = abs(signed_lots) * price * cs
```

Where:
- `signed_lots` = actual lot size from MT5 position (e.g., 0.01)
- `price` = current ask price from MT5 tick
- `cs` = `trade_contract_size` from MT5 symbol_info

For EURUSD: `0.01 lots × 1.08 × 100,000 = $1,080`
For BTCUSD: `0.01 lots × 58,000 × 1 = $580`

**Note:** The `price` used is the ask price from the tick at the time of analytics computation, NOT the fill price. This means:
- Notional reflects current market value, not entry cost
- Weight = notional / equity is a mark-to-market weight
- This is appropriate for portfolio state observation

---

## 4. Leverage Denominator

**Status:** ⚠️ MINOR ISSUE — `capped_equity` vs actual equity

```python
capped_equity = min(equity, 5100.0)
gross_leverage = gross_exposure / capped_equity
```

The denominator uses `min(equity, 5100.0)` — the campaign's maximum authorized equity. This means:
- If equity drops to $4,000, leverage is computed against $4,000 (correct)
- If equity rises to $6,000, leverage is computed against $5,100 (conservative)

**Impact:** Minor. Leverage is slightly overstated when equity > $5,100. This is a deliberate conservative choice matching the capital envelope. Not a bug, but should be documented.

---

## 5. Correlation Return Construction

**Status:** ⚠️ NOT WIRED — returns_history is never passed

The rebalance loop call:
```python
_diagnostics = _analyzer.compute_diagnostics(
    target_weights=target_weights,
    current_positions=current_lots,
    prices=prices,
    contract_sizes=contract_sizes,
    equity=equity,
    # returns_history NOT passed
)
```

**Impact:** `correlation_diagnostics` will always be empty `{}` in live production. The correlation-adjusted `effective_bets` metric is never computed live.

**Recommendation:** Either:
1. Pass `returns_history` (fetch 60-day returns before calling analytics), OR
2. Accept that correlation diagnostics are offline-only and document this

This is NOT a correctness bug — the field simply returns empty when returns are not provided. But it means the live output will show `effective_bets=0.0` instead of the correlation-adjusted value.

---

## 6. Eigenvalue Numerical Stability

**Status:** ✅ HANDLED

```python
try:
    eigenvalues = np.linalg.eigvalsh(corr_np)
    # ...
except Exception:
    return {}
```

- Uses `eigvalsh` (symmetric eigendecomposition) — appropriate for correlation matrices
- Wrapped in try/except — singular or near-singular matrices produce empty result
- `portfolio_variance <= 0` check prevents division by zero
- NaN/Inf returns handled by pandas `.corr()` returning NaN, which propagates to eigenvalues, triggering the exception handler

---

## 7. Pre-Trade vs Post-Trade State

**Status:** ⚠️ AMBIGUOUS — analytics runs AFTER order generation but BEFORE execution

Timeline in rebalance loop:
```
1. generate_orders()     ← computes target weights
2. risk gates
3. PortfolioAnalyzer     ← uses current_lots (pre-trade positions)
4. execute_orders()      ← submits to MT5
```

**What analytics describes:** The portfolio state BEFORE the current cycle's orders execute. The `current_positions` are the positions that existed at the start of the cycle.

**What it does NOT describe:**
- The target portfolio (after orders execute)
- The actual fills (post-execution)

**Impact:** The analytics shows the portfolio state at cycle start, not the intended or actual state. This is acceptable for observation but should be documented. The `target_weights` are included in the output for comparison.

---

## 8. JSONL Schema/Versioning

**Status:** ⚠️ NO VERSION FIELD

The JSONL output does not include a schema version. If the analytics implementation changes (e.g., new fields, renamed fields, changed calculation methods), old and new records will be mixed without distinguishability.

**Recommendation:** Add `"analytics_version": "1.0"` to every record.

---

## 9. Governance: Analytics Cannot Influence Execution

**Status:** ✅ VERIFIED

The analytics call in the rebalance loop:
```python
try:
    from eigencapital.live.portfolio_analytics import PortfolioAnalyzer
    _analyzer = PortfolioAnalyzer(audit_dir=AUDIT_DIR)
    _diagnostics = _analyzer.compute_diagnostics(...)
    _analyzer.record(_diagnostics)
    log(...)
except Exception as e:
    log(f"  ⚠️ Shadow analytics failed (non-blocking): {e}")
```

- Wrapped in try/except — failures never block trading
- No return value used by the execution path
- No state mutation in `compute_diagnostics` or `record`
- The `_diagnostics` object is local — not passed to any execution function
- The `generate_orders()` function runs BEFORE analytics and has no reference to analytics output

**Verified:** Analytics is a dead-end side effect. It cannot influence signal, selection, sizing, risk approval, order quantity, or execution.

---

## 10. Symbol Mapping

**Status:** ✅ CORRECT

The analytics uses `SYMBOL_CURRENCY_MAP` which matches the production config's `allowed_symbols`. Non-FX symbols (BTCUSD, XAUUSD, US30, USTEC, USOIL) are classified by `ASSET_CLASS_MAP` and return empty currency exposure (correct — they don't have base/quote currencies in the FX sense).

---

## 11. Stale Positions vs Target Positions

**Status:** ✅ CORRECT

Analytics receives `current_lots` — the actual broker-confirmed positions from MT5 (via `positions_get()`). This is the authoritative source, not an internal estimate.

The `target_weights` (from the R4 signal) are also passed and included in the output for comparison. The difference between `current_positions` and `target_weights` represents the rebalance delta.

---

## Summary of Findings

| # | Check | Status | Action |
|---|-------|--------|--------|
| 1 | FX sign conventions | ✅ Correct | None |
| 2 | USD decomposition | ✅ Correct | None |
| 3 | Notional calculation | ✅ Correct | None |
| 4 | Leverage denominator | ⚠️ Minor | Document capped_equity choice |
| 5 | Returns not wired | ⚠️ Gap | Pass returns_history or document |
| 6 | Eigenvalue stability | ✅ Handled | None |
| 7 | Pre-trade state | ⚠️ Document | Add timestamp/state label |
| 8 | No version field | ⚠️ Gap | Add analytics_version |
| 9 | Governance invariant | ✅ Verified | None |
| 10 | Symbol mapping | ✅ Correct | None |
| 11 | Stale vs target | ✅ Correct | None |

### Recommendations

1. **Add `analytics_version` field** to every JSONL record for future reproducibility
2. **Wire returns_history** into the analytics call (fetch 60-day returns before calling)
3. **Document** that analytics describes pre-trade portfolio state
4. **Document** that `capped_equity` is a deliberate conservative choice

None of these require changes to R4 behavior, sizing, selection, or risk gates.
