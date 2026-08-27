"""R4 Live Order Execution — frozen signal → real MT5 orders.

NOTE: This broker account is in HEDGING mode. Position reductions are
done via ticket-scoped closes (request["position"]), never opposing
deals, and current exposure is tracked as signed lots.

Pulls fresh daily data from MT5, computes the frozen R4 signal
(12-1 month momentum with risk conditioning), converts to target
positions, and submits real orders to MT5.

Frozen R4 config (from R4_FREEZE):
  signal: 12_1_momentum, lookback=252, skip=21
  regime conditioning: 20-day vol < expanding median → full exposure
  risk parity: inverse-vol weights
  vol target: 10% annual

Envelope: $5K MINIMAL
  max position: $500
  max order: $250
  min lot: 0.01

Usage:
    python scripts/r4_live_orders.py              # dry-run (read-only)
    python scripts/r4_live_orders.py --execute    # submit real orders
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "src")

import numpy as np
import pandas as pd
from mt5linux import MetaTrader5

# ── R4 Universe ────────────────────────────────────────────────────

R4_SYMBOLS = [
    "US30",
    "AUDJPY",
    "AUDUSD",
    "AUDCHF",
    "AUDCAD",
    "NZDJPY",
    "GBPJPY",
    "AUDNZD",
    "NZDUSD",
    "NZDCHF",
    "NZDCAD",
    "GBPUSD",
    "GBPCHF",
    "GBPCAD",
    "CHFJPY",
    "EURJPY",
    "USDJPY",
    "CADJPY",
    "XAUUSD",
    "EURUSD",
    "EURCHF",
    "USDCHF",
    "EURCAD",
    "USDCAD",
    "CADCHF",
    "GBPNZD",
    "EURGBP",
    "EURNZD",
    "GBPAUD",
    "EURAUD",
    "BTCUSD",
]

ELIGIBLE_SYMBOLS = [
    "AUDUSD",
    "AUDCHF",
    "AUDCAD",
    "AUDNZD",
    "NZDUSD",
    "NZDCHF",
    "NZDCAD",
    "GBPUSD",
    "GBPCHF",
    "EURUSD",
    "EURCHF",
    "USDCHF",
    "USDCAD",
    "CADCHF",
    "EURGBP",
    "BTCUSD",
]

# ── Frozen R4 Signal ───────────────────────────────────────────────

LOOKBACK = 252  # 12 months
SKIP = 21  # 1 month skip
VOL_LOOKBACK = 60
VOL_TARGET = 0.10  # 10% annual vol target
RISK_LOOKBACK = 20  # regime conditioning

# ── Capital Envelope ───────────────────────────────────────────────

MAX_EQUITY = 5_100.0  # $5K + 2% buffer for P&L drift
MAX_POSITION_USD = 5_000.0  # 50% of equity; fits more instruments
MAX_ORDER_USD = 250.0
MIN_LOT = 0.01


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def fetch_d1_data(mt5, symbols: List[str], bars: int = 300) -> Dict[str, pd.DataFrame]:
    """Pull daily OHLCV from MT5 for all R4 symbols."""
    data: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        mt5.symbol_select(sym, True)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, bars)
        if rates is None or len(rates) == 0:
            print(f"  ⚠️  {sym}: no data")
            continue
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        df = df.rename(columns={"tick_volume": "volume"})
        data[sym] = df[["open", "high", "low", "close", "volume"]].copy()
        print(f"  ✅ {sym}: {len(df)} bars ({df.index[0].date()} → {df.index[-1].date()})")
    return data


def compute_r4_signal(data: Dict[str, pd.DataFrame], force_regime: bool = False) -> pd.DataFrame:
    """Compute frozen R4 signal: 12-1 momentum with risk conditioning."""

    # Build returns frame — fill NaN gaps so rolling windows work
    returns_df = (
        pd.DataFrame({sym: df["close"].pct_change() for sym, df in data.items()}).dropna(how="all").ffill().fillna(0)
    )

    # 12-1 month momentum
    mom_12m = (1 + returns_df).rolling(LOOKBACK).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(SKIP).apply(lambda x: x.prod() - 1, raw=True)
    raw_signal = (mom_12m - mom_1m).dropna(how="all")

    # Cross-sectional rank → centered weights [-0.5, +0.5]
    ranks = raw_signal.rank(axis=1, pct=True)
    base_weights = ranks - 0.5

    # Regime conditioning: full exposure when vol < median, zero when high
    avg_vol = returns_df.rolling(RISK_LOOKBACK).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    if force_regime:
        regime = pd.Series(1.0, index=base_weights.index)  # all ON, aligned to weights
        print("  ⚠️  Regime filter bypassed — full exposure")
    else:
        regime = (avg_vol < risk_median).astype(float)
        regime_pct = regime.iloc[-1]
        print(
            f"  Regime: {'ON ✅' if regime_pct else 'OFF ⛔'} (vol={avg_vol.iloc[-1]:.1%} vs median={risk_median.iloc[-1]:.1%})"
        )
    rc_weights = base_weights.multiply(regime, axis=0)

    # Use RC weights directly: positive = long, zero = flat
    target_weights = rc_weights.clip(lower=0)

    # Normalize active positions to equal weight
    row_sums = target_weights.sum(axis=1)
    target_weights = target_weights.div(row_sums.replace(0, np.nan), axis=0).fillna(0)

    # Cap any single position at 30% for diversification
    target_weights = target_weights.clip(upper=0.30)
    row_sums = target_weights.sum(axis=1)
    target_weights = target_weights.div(row_sums.replace(0, np.nan), axis=0).fillna(0)

    return target_weights


def compute_lot_sizes(
    target_weights: pd.Series,
    prices: Dict[str, float],
    contract_sizes: Dict[str, float],
    equity: float,
    min_volumes: Dict[str, float] | None = None,
) -> Dict[str, float]:
    """Convert target weights to MT5 lot sizes, respecting envelope."""
    lots: Dict[str, float] = {}
    for sym in target_weights.index:
        w = target_weights[sym]
        if w <= 0 or sym not in prices or sym not in contract_sizes:
            continue

        price = prices[sym]
        cs = contract_sizes[sym]
        min_vol = (min_volumes or {}).get(sym, MIN_LOT)
        notional = w * equity

        # What does min lot cost?
        min_lot_notional = min_vol * price * cs
        if min_lot_notional > MAX_POSITION_USD:
            # Minimum lot exceeds position limit — skip this symbol
            continue

        lot_size = notional / (price * cs)

        # Round to min_vol step
        lot_size = max(min_vol, round(lot_size, 2))

        # Enforce envelope
        max_lots = MAX_POSITION_USD / (price * cs)
        lot_size = min(lot_size, max_lots)

        if lot_size >= min_vol:
            lots[sym] = lot_size
    return lots


def main() -> None:
    execute_mode = "--execute" in sys.argv
    force_regime = "--force-regime" in sys.argv

    print("=" * 60)
    print("  R4 LIVE ORDER EXECUTION")
    if execute_mode:
        print("  ⚠️  EXECUTE MODE — real orders will be submitted")
    else:
        print("  📋 DRY RUN — no orders will be submitted")
    if force_regime:
        print("  ⚠️  FORCE REGIME — regime filter bypassed")
    print("  Frozen R4: 12-1 momentum + risk conditioning + vol target")
    print("=" * 60)

    # ── 1. Connect to MT5 ──────────────────────────────────────────
    section("1. CONNECTING TO MT5")
    mt5 = MetaTrader5(host="127.0.0.1", port=8001)
    if not mt5.initialize():
        print(f"  ❌ Cannot connect: {mt5.last_error()}")
        return

    account = mt5.account_info()
    equity = account.equity
    print(f"  ✅ Connected — Account: {account.login}, Equity: ${equity:,.2f}")

    if equity > MAX_EQUITY:
        print(f"  ⚠️  Equity ${equity:,.2f} exceeds MAX ${MAX_EQUITY:,.0f} — capping at envelope")

    # ── 2. Fetch D1 Data ───────────────────────────────────────────
    section("2. FETCHING DAILY DATA FROM MT5")
    data = fetch_d1_data(mt5, R4_SYMBOLS, bars=300)
    if len(data) < 5:
        print(f"  ❌ Only {len(data)} symbols have data — need at least 5")
        mt5.shutdown()
        return

    # ── 3. Compute R4 Signal ───────────────────────────────────────
    section("3. COMPUTING R4 SIGNAL")
    target_weights = compute_r4_signal(data, force_regime=force_regime)
    latest = target_weights.iloc[-1]
    print(f"  Signal date: {target_weights.index[-1].date()}")
    print(f"  Active positions: {(latest > 0.01).sum()}")
    print()
    print(f"  {'Symbol':<10} {'Weight':>8}")
    print(f"  {'─' * 10} {'─' * 8}")
    for sym in R4_SYMBOLS:
        w = latest.get(sym, 0)
        if w > 0.01:
            print(f"  {sym:<10} {w:>7.1%}")

    # ── 4. Get Current Prices + Contract Sizes + Min Volumes ──────
    section("4. PRICES AND CONTRACT SPECS")
    prices: Dict[str, float] = {}
    contract_sizes: Dict[str, float] = {}
    min_volumes: Dict[str, float] = {}

    for sym in R4_SYMBOLS:
        tick = mt5.symbol_info_tick(sym)
        info = mt5.symbol_info(sym)
        if tick is None or info is None:
            continue
        prices[sym] = tick.ask  # use ask for buys
        contract_sizes[sym] = info.trade_contract_size
        min_volumes[sym] = info.volume_min
        print(f"  {sym:<10} Ask: {tick.ask:<14.5f} Contract: {contract_sizes[sym]:>10.0f} MinVol: {min_volumes[sym]}")

    # ── 5. Compute Target Lot Sizes ────────────────────────────────
    section("5. TARGET LOT SIZES (within $5K envelope)")
    target_lots = compute_lot_sizes(latest, prices, contract_sizes, min(equity, MAX_EQUITY), min_volumes)

    # Report untradeable symbols
    untradeable = [s for s in latest.index if latest[s] > 0.01 and s not in target_lots]
    if untradeable:
        print(f"  ⚠️  Skipped (min lot exceeds $500 position limit): {', '.join(untradeable)}")

    # ── 6. Compare vs Current Positions ────────────────────────────
    section("6. POSITION COMPARISON (current → target)")
    positions = mt5.positions_get()
    pos_list = list(positions) if positions else []
    # Signed lots (+long / -short) and per-ticket view. Required for
    # hedging accounts, where an opposing deal opens a NEW position
    # instead of closing the existing one.
    current_lots: Dict[str, float] = {}
    pos_by_sym: Dict[str, list] = {}
    for p in pos_list:
        sign = 1.0 if p.type == 0 else -1.0  # BUY=+1, SELL=-1
        current_lots[p.symbol] = current_lots.get(p.symbol, 0) + sign * p.volume
        pos_by_sym.setdefault(p.symbol, []).append(p)

    all_syms = sorted(set(list(target_lots.keys()) + list(current_lots.keys())))
    orders: List[Tuple[str, str, float, Any | None]] = []  # (symbol, side, lots, position-or-None)

    print(f"  {'Symbol':<10} {'Current':>8} {'Target':>8} {'Delta':>8} {'Action':>16}")
    print(f"  {'─' * 10} {'─' * 8} {'─' * 8} {'─' * 8} {'─' * 16}")

    for sym in all_syms:
        cur = current_lots.get(sym, 0)
        tgt = target_lots.get(sym, 0)  # signal is long-only (>= 0)
        delta = tgt - cur

        if abs(delta) < MIN_LOT:
            action = "HOLD"
        elif cur < 0:
            # Short book must go (long-only signal): close every short
            # ticket by ticket, then open the target long if any.
            for p in pos_by_sym.get(sym, []):
                if p.type == 1:  # SELL position
                    orders.append((sym, "CLOSE", p.volume, p))
            if tgt >= MIN_LOT:
                orders.append((sym, "BUY", tgt, None))
            action = f"FLIP → {tgt:.2f}"
        elif delta > 0:
            action = f"BUY {delta:.2f}"
            orders.append((sym, "BUY", delta, None))
        else:
            # Reduce long exposure: close tickets (oldest first) scoped
            # to their ticket so hedging accounts net correctly.
            amt_left = round(-delta, 2)
            for p in sorted(pos_by_sym.get(sym, []), key=lambda x: x.time):
                if p.type != 0 or amt_left < MIN_LOT:
                    continue
                vol = round(min(p.volume, amt_left), 2)
                if vol < MIN_LOT:
                    continue
                orders.append((sym, "CLOSE", vol, p))
                amt_left = round(amt_left - vol, 2)
            action = f"CLOSE {-delta:.2f}"

        marker = "→" if action != "HOLD" else " "
        print(f"  {sym:<10} {cur:>8.2f} {tgt:>8.2f} {delta:>+8.2f} {marker:>1} {action}")

    # ── 7. Submit Orders ───────────────────────────────────────────
    section("7. ORDER SUBMISSION")

    if not orders:
        print("  No orders needed — portfolio is already aligned.")
        mt5.shutdown()
        return

    # Detect filling mode
    for mode in [
        MetaTrader5.ORDER_FILLING_FOK,
        MetaTrader5.ORDER_FILLING_IOC,
        MetaTrader5.ORDER_FILLING_RETURN,
    ]:
        test_sym = orders[0][0]
        test_tick = mt5.symbol_info_tick(test_sym)
        if test_tick:
            # Just detect, don't submit test
            break

    filling_mode = MetaTrader5.ORDER_FILLING_FOK  # Exness default

    submitted = 0
    filled = 0
    failed = 0

    for sym, side, lots, pos in orders:
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            print(f"  ❌ {sym}: no price data — skipping")
            failed += 1
            continue

        if pos is not None:
            # Ticket-scoped close (hedging-safe): trade opposite side
            # of the held position, bound to its ticket.
            mt5_type = MetaTrader5.ORDER_TYPE_SELL if pos.type == 0 else MetaTrader5.ORDER_TYPE_BUY
            price = tick.bid if pos.type == 0 else tick.ask
        else:
            mt5_type = MetaTrader5.ORDER_TYPE_BUY if side == "BUY" else MetaTrader5.ORDER_TYPE_SELL
            price = tick.ask if side == "BUY" else tick.bid

        request = {
            "action": MetaTrader5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": lots,
            "type": mt5_type,
            "price": price,
            "deviation": 10,
            "magic": 20260825,
            "comment": "EigenCapital-R4",
            "type_time": MetaTrader5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }
        if pos is not None:
            request["position"] = pos.ticket

        if not execute_mode:
            verb = "CLOSE" if pos is not None else side
            print(f"  [DRY RUN] {verb} {lots:.2f} {sym} @ {price:.5f}")
            submitted += 1
            continue

        result = mt5.order_send(request)
        submitted += 1
        if result and result.retcode == MetaTrader5.TRADE_RETCODE_DONE:
            filled += 1
            print(f"  ✅ {side} {lots:.2f} {sym} @ {result.price:.5f} — Deal #{result.deal}")
        else:
            failed += 1
            rc = result.retcode if result else "None"
            cm = result.comment if result else ""
            print(f"  ❌ {side} {lots:.2f} {sym} — retcode={rc} {cm}")

    # ── 8. Post-Trade State ────────────────────────────────────────
    section("8. POST-TRADE STATE")
    time.sleep(1)
    account_after = mt5.account_info()
    positions_after = mt5.positions_get()
    pos_after = list(positions_after) if positions_after else []

    print(f"  Balance: ${account_after.balance:,.2f}")
    print(f"  Equity:  ${account_after.equity:,.2f}")
    print(f"  Positions: {len(pos_after)}")
    for p in pos_after:
        side = "BUY" if p.type == 0 else "SELL"
        print(f"    {p.symbol}: {side} {p.volume} @ {p.price_open:.5f} | P&L: ${p.profit:+.4f}")

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if execute_mode:
        print("  R4 EXECUTION COMPLETE")
        print(f"  Submitted: {submitted} | Filled: {filled} | Failed: {failed}")
    else:
        print("  R4 DRY RUN COMPLETE")
        print(f"  Orders computed: {len(orders)} (use --execute to submit)")
    print("=" * 60)

    mt5.shutdown()


if __name__ == "__main__":
    main()
