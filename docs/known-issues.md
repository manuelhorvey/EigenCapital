# EigenCapital — Known Issues & Constraints

## Active

- **Paper trading only** — MT5 Exness demo, no live capital deployed
- **3 permanent SELL_ONLY assets** — CADCHF, NZDCHF, EURAUD have confirmed permanent BUY signal inversion. Feature space encodes SELL alpha but not BUY alpha. See AGENTS.md for full diagnostic chain.
- **MT5 bridge requires Wine** on Linux; single-threaded (RLock-serialized concurrent requests)
- **Small MT5 demo ($107)** — positions quantize to 0.01 lot minimum (~$1,150 notional on EURUSD). Desired vs actual notional drifts upward. Leverage budget deferred until equity > $10K.
- **Circuit breaker** — -15% DD or 7 consecutive portfolio losses triggers emergency halt. Auto-clears when equity ≥ 99% of peak and reason is DRAWDOWN/CONSECUTIVE_LOSSES.
- **Spread gate** — observe-only for first 720 cycles (~6h), then enforcement. Blocks entry when spread exceeds per-class threshold.
- **Some JPY crosses produce incomplete first-cycle bars** — cold-start transient suppressed by first-cycle suppression stage.
- **Paper/MT5 sizing divergence** is expected — paper simulates $100K equity, MT5 executes on $107. Two completely independent sizing chains.

## Resolved (historical)

- GBPNZD removed 2026-06-20 (tp/sl ratio 0.33 required 75% breakeven WR, achieved 72.3%)
- Ensemble disabled 2026-06-20 (walk-forward p=0.83; ADR-026)
- SL/TP triple bug fixed 2026-06-16 (deactivated atr_mult_tp, uncalibrated atr_mult_sl, TP compiler convexity)
- THIN liquidity regime routing fixed 2026-06-17 (was halting all assets; now soft warning)
- Carry feature always-zero bug fixed 2026-06-19 (rate_diff column name mismatch)
- Pipeline indentation nesting bug fixed 2026-06-19 (16 methods were inner functions of _detect_bar_jump)
- Regime model at inference fixed 2026-06-19 (load guard + missing regime features)
- Emergency halt loop fixed 2026-07-03 (stale peak, cycle counter, auto-clear)
