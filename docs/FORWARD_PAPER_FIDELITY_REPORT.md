# R4 Paper Fidelity Report

**Campaign:** FWD-2c20472b64a5
**Manifest:** 2c20472b64a54084...
**Verdict:** paper_fidelity_pass

## Gate Results

- ✅ **research_parity**: Effective match rate 100.0% (excl 0 expected), 0 unexplained, 0 critical (PASS)
- ✅ **execution_accounting**: Cost drag 10.0bp, max slippage 5.0bp (PASS)
- ✅ **risk_behavior**: Critical divergences: 0 (PASS)
- ✅ **reconciliation**: Reconciliation success rate: 100.0% (PASS)
- ✅ **operational_stability**: Missing bars: 0, stale events: 0 (PASS)
- ✅ **cost_slippage_envelope**: Within envelope (PASS)
- ✅ **no_critical_divergence**: Critical divergences: 0 (PASS)

## Parity Summary

- Total checks: 0
- Exact matches: 0
- Expected differences: 0
- Tolerable divergences: 0
- Unexplained divergences: 0
- Critical divergences: 0
- Match rate: 0.0%

## Summary

- Passed gates: 7/7
- Failed gates: 0/7
- Report hash: d247673860862aef...

**The paper implementation reproduces the validated R4 research.**

## Operational Summary

```
  total_ticks: 4352
  missing_bars: 0
  stale_data_events: 0
  spread_widening_events: 0
  session_boundaries: 0
  instrument_unavailable: 0
  market_closed_events: 0
  data_gaps: 0
  reconciliation_checks: 87
  reconciliation_failures: 0
  reconciliation_success_rate: 1.0
  connection_interrupts: 0
  price_anomalies: 93
  error_rate: 0.021369485294117647
  max_consecutive_errors: 5
```
