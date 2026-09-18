"""R4 Trade-Stream Export — first persisted trade stream for R1 Monte Carlo.

Runs the frozen R4 signal over the local MT5 D1 history, simulates the
portfolio with next-bar-open weekly execution, and exports the resulting
closed round-trips into a persisted, provenance-stamped TradeStream JSON.

This script is a RESEARCH EXPORTER, not the production loop. Faithfulness
notes (all documented, none silent):

- Signal logic is replicated from scripts/r4_rebalance_loop.py
  (compute_r4_signal, the canonical R4 pipeline): 12-1 momentum
  (lookback=252, skip=21), cross-sectional percentile rank centered at 0,
  regime gate = 20-day average vol below its expanding median, 60-day vol
  scaling (capped at 1.0, 50% reference), final clip [-0.20, +0.20].
  Parameters are read from configs/production/config.toml when present
  (signal_lookback_long, skip_months*21, risk_lookback, vol_lookback_signal)
  and fall back to those frozen literals.
- Execution is next-bar open after a weight change, WEEKLY rebalance
  (config.toml rebalance_frequency).
- One-way transaction cost of 10 bps + 5 bps slippage of traded notional
  (config.toml transaction_cost_bps/slippage_bps) is charged per leg: 15 bps
  per side, 30 bps per round trip.
- Per-trade P&L is computed EXPLICITLY in this script (never re-derived
  inside the adapter): each per-symbol exposure interval is realized as one
  round-trip — open at interval-start open price, close at interval-end open
  price (last bar's close for the terminal close) — net of both cost legs.
  Any weight change while a position is open is realized as close + reopen
  (costs charged honestly on both legs). The R4 production strategy trades a
  cross-sectional portfolio; this exporter realizes it as per-symbol
  round-trips, which is the trade population the MC diagnostics consume.
- Faithfulness caveat (documented, not silent): the production loop evaluates
  the regime gate at the LATEST bar; a backtest must apply the point-in-time
  gate row-by-row to avoid lookahead. BTCUSD tightening is irrelevant here
  (no local BTCUSD history used). Only 8 of the 17 eligible R4 symbols have
  local history (documented data limitation).
- Stream assembly: the adapter is called PER SYMBOL (its pairing contract is
  a single strictly-alternating fill sequence), then per-symbol trades are
  merged and sorted by exit timestamp (exit-chronological), re-indexed 1..N,
  and wrapped in a TradeStream — satisfying the schema's exit-monotonicity
  invariant for a multi-symbol portfolio.

Usage:
    python scripts/export_r4_trade_stream.py            # default output
    python scripts/export_r4_trade_stream.py --out PATH
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, "src")

import numpy as np
import pandas as pd

from eigencapital.research.monte_carlo.adapter import backtest_results_to_trade_stream
from eigencapital.research.monte_carlo.bootstrap import run_bootstrap_test
from eigencapital.research.monte_carlo.permutation import run_permutation_test
from eigencapital.research.monte_carlo.persistence import load_trade_stream, save_trade_stream
from eigencapital.research.monte_carlo.schema import TradeRecord, TradeStream

# ── Frozen R4 parameters (fallbacks; overridden by config.toml if present) ──

LOOKBACK = 252
SKIP = 21  # skip_months=1 → 21 trading days (r4_rebalance_loop convention)
RISK_LOOKBACK = 20
VOL_LOOKBACK_SIGNAL = 60
VOL_SCALE_REFERENCE = 0.50
WEIGHT_CLIP = 0.20
COST_ONE_WAY = 15.0 / 10_000  # 10 bps transaction + 5 bps slippage (config.toml)
REBALANCE_EVERY = 5  # weekly on D1 bars

# R4-eligible symbols that exist in data/mt5/ (the rest have no local
# history — a documented data limitation).
AVAILABLE_SYMBOLS = [
    "AUDUSDm",
    "NZDUSDm",
    "GBPUSDm",
    "EURUSDm",
    "USDCHFm",
    "USDCADm",
    "USDJPYm",
    "XAUUSDm",
]

INSTRUMENT_LABEL = "R4_FX_METALS_D1"
DEFAULT_OUT = "reports/r1_monte_carlo/trade_stream_R4_daily.json"


def load_config_params() -> Dict[str, Any]:
    """Read frozen R4 parameters from production config when available."""
    try:  # tomllib is stdlib on 3.11+
        import tomllib

        with open("configs/production/config.toml", "rb") as fh:
            cfg = tomllib.load(fh)
        s = cfg.get("strategy", {})
        return {
            "lookback": int(s.get("signal_lookback_long", LOOKBACK)),
            "skip": int(s.get("skip_months", 1)) * 21,
            "risk_lookback": int(s.get("risk_lookback", RISK_LOOKBACK)),
            "vol_lookback": int(s.get("vol_lookback_signal", VOL_LOOKBACK_SIGNAL)),
            "rebalance_every": REBALANCE_EVERY,
            "cost_one_way": (float(s.get("transaction_cost_bps", 10.0)) + float(s.get("slippage_bps", 5.0))) / 10_000,
        }
    except (OSError, ValueError, KeyError):
        return {
            "lookback": LOOKBACK,
            "skip": SKIP,
            "risk_lookback": RISK_LOOKBACK,
            "vol_lookback": VOL_LOOKBACK_SIGNAL,
            "rebalance_every": REBALANCE_EVERY,
            "cost_one_way": COST_ONE_WAY,
        }


def load_bars() -> Dict[str, pd.DataFrame]:
    """Load local MT5 D1 CSVs for the available R4 symbols."""
    data: Dict[str, pd.DataFrame] = {}
    for sym in AVAILABLE_SYMBOLS:
        path = Path("data/mt5") / f"{sym}_D1.csv"
        if not path.is_file():
            print(f"  WARNING {sym}: no local history, skipping")
            continue
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time").sort_index()
        data[sym] = df[["open", "high", "low", "close"]].copy()
    if len(data) < 2:
        raise SystemExit("need at least 2 symbols with local history")
    return data


def compute_r4_signal(data: Dict[str, pd.DataFrame], params: Dict[str, Any]) -> pd.DataFrame:
    """Replica of scripts/r4_rebalance_loop.py::compute_r4_signal (point-in-time)."""
    returns_df = (
        pd.DataFrame({sym: df["close"].pct_change() for sym, df in data.items()}).dropna(how="all").ffill().fillna(0)
    )

    # 1. Momentum: 12-1 month
    mom_12m = (1 + returns_df).rolling(params["lookback"]).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(params["skip"]).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom_12m - mom_1m).dropna(how="all")

    # 2. Cross-sectional rank → centered weights
    rk = sig.rank(axis=1, pct=True)
    w = rk - 0.5

    # 3. Regime conditioning (point-in-time row-by-row: required for backtest)
    avg_vol = returns_df.rolling(params["risk_lookback"]).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)

    # 4. Vol scaling: 60-day vol, capped at 1.0 against the 50% reference
    vol60 = returns_df.rolling(params["vol_lookback"]).std() * np.sqrt(252)
    vol_scale = np.minimum(vol60 / VOL_SCALE_REFERENCE, 1.0)

    # 5. Frozen R4 final weights: regime × vol-scale → clip ±0.20
    fin = w.multiply(regime, axis=0) * vol_scale
    return fin.clip(-WEIGHT_CLIP, WEIGHT_CLIP)


def _iso(ts: Any) -> str:
    """Naive ISO-8601 label (CSV timestamps are tz-naive daily dates)."""
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _next_trading_day(index: pd.DatetimeIndex, date: Any) -> Any:
    pos = index.searchsorted(date)
    return index[pos] if pos < len(index) else None


def _open_fill(events: List[Dict[str, Any]], ts: Any, sym: str, side: str, price: float) -> None:
    events.append(
        {
            "timestamp": _iso(ts),
            "side": side,
            "quantity": 1.0,
            "fill_price": price,
            "commission": 0.0,
            "fees": 0.0,
            "instrument": sym,
        }
    )


def simulate_portfolio(
    data: Dict[str, pd.DataFrame], weights: pd.DataFrame, params: Dict[str, Any]
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Tuple[float, float]]]]:
    """Next-bar-open weekly execution of the weight path.

    Returns:
        (fills_by_symbol, trades_by_symbol) where trades_by_symbol maps each
        symbol to its closed round-trips as (net_pnl, costs_in_return_units)
        tuples in chronological order.
    """
    closes = pd.DataFrame({sym: df["close"] for sym, df in data.items()})
    opens = pd.DataFrame({sym: df["open"] for sym, df in data.items()})
    cost = params["cost_one_way"]

    weekly = weights.iloc[:: params["rebalance_every"]]
    exec_dates: List[Any] = []
    for d in weekly.index:
        ts = _next_trading_day(closes.index, d)
        if ts is not None:
            exec_dates.append(ts)

    fills_by_symbol: Dict[str, List[Dict[str, Any]]] = {sym: [] for sym in closes.columns}
    trades_by_symbol: Dict[str, List[Tuple[float, float]]] = {sym: [] for sym in closes.columns}

    open_pos: Dict[str, Dict[str, Any]] = {}  # sym → {weight, entry_ts, entry_px}
    target: Dict[str, float] = {sym: 0.0 for sym in closes.columns}

    def _close(sym: str, ts: Any, exit_px: float) -> None:
        pos = open_pos.pop(sym)
        close_side = "SELL" if pos["weight"] > 0 else "BUY"
        _open_fill(fills_by_symbol[sym], ts, sym, close_side, exit_px)
        gross = pos["weight"] * (exit_px / pos["entry_px"] - 1.0)
        costs = 2.0 * cost * abs(pos["weight"])  # both legs, in return units
        trades_by_symbol[sym].append((gross - costs, costs))

    for w_date, w_row in zip(weekly.index, weekly.itertuples(index=False)):
        exec_ts = _next_trading_day(closes.index, w_date)
        if exec_ts is None:
            break
        for sym in closes.columns:
            raw = weekly.at[w_date, sym]
            new_w = 0.0 if pd.isna(raw) else float(raw)
            cur = target[sym]
            if abs(new_w - cur) < 1e-9:
                continue
            if sym in open_pos:
                _close(sym, exec_ts, float(opens.at[exec_ts, sym]))
            if abs(new_w) > 1e-9:
                side = "BUY" if new_w > 0 else "SELL"
                entry_px = float(opens.at[exec_ts, sym])
                _open_fill(fills_by_symbol[sym], exec_ts, sym, side, entry_px)
                open_pos[sym] = {"weight": new_w, "entry_ts": exec_ts, "entry_px": entry_px}
            target[sym] = new_w

    # Terminal close at the last available close price
    last_ts = closes.index[-1]
    for sym in list(open_pos):
        _close(sym, last_ts, float(closes.at[last_ts, sym]))

    return fills_by_symbol, trades_by_symbol


def build_stream(
    fills_by_symbol: Dict[str, List[Dict[str, Any]]],
    trades_by_symbol: Dict[str, List[Tuple[float, float]]],
    params: Dict[str, Any],
    git_commit: str,
) -> TradeStream:
    """Per-symbol adapter calls → merged exit-chronological TradeStream."""
    merged: List[TradeRecord] = []
    for sym, fills in fills_by_symbol.items():
        if not fills:
            continue
        pnls = [p for p, _ in trades_by_symbol[sym]]
        costs = [c for _, c in trades_by_symbol[sym]]
        per_symbol = backtest_results_to_trade_stream(
            fills,
            per_trade_pnl=pnls,
            per_trade_costs=costs,
            stream_id=f"TS-R4-D1-0001:{sym}",
            experiment_id="EXP-R1-FIRSTSTREAM",
            strategy_id="R4",
            strategy_version="v4.0",
            dataset_id="mt5_d1_local",
            dataset_version="2026.08",
            git_commit=git_commit,
            cost_model_id="one_way_15bps",
            cost_model_version="v1",
            instrument=sym,
        )
        merged.extend(per_symbol.trades)

    # Exit-chronological order satisfies the schema's exit-monotonic invariant
    # for a multi-symbol portfolio; re-index to contiguous 1..N.
    merged.sort(key=lambda t: t.exit_timestamp)
    renumbered = tuple(
        TradeRecord(
            trade_index=i,
            instrument=t.instrument,
            entry_timestamp=t.entry_timestamp,
            exit_timestamp=t.exit_timestamp,
            side=t.side,
            realized_pnl=t.realized_pnl,
            return_r=t.return_r,
            costs_paid=t.costs_paid,
            metadata=t.metadata,
        )
        for i, t in enumerate(merged, start=1)
    )

    return TradeStream(
        stream_id="TS-R4-D1-0001",
        experiment_id="EXP-R1-FIRSTSTREAM",
        strategy_id="R4",
        strategy_version="v4.0",
        dataset_id="mt5_d1_local",
        dataset_version="2026.08",
        git_commit=git_commit,
        cost_model_id="one_way_15bps",
        cost_model_version="v1",
        trades=renumbered,
    )


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Export first R4 trade stream for R1 Monte Carlo")
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    params = load_config_params()
    print(f"R4 parameters: {params}")

    data = load_bars()
    print(f"Loaded {len(data)} symbols: {sorted(data)}")

    weights = compute_r4_signal(data, params)
    print(f"Signal rows: {len(weights)} ({weights.index[0].date()} → {weights.index[-1].date()})")

    fills_by_symbol, trades_by_symbol = simulate_portfolio(data, weights, params)
    n_trades = sum(len(v) for v in trades_by_symbol.values())
    print(f"Round-trips: {n_trades} across {sum(1 for v in fills_by_symbol.values() if v)} symbols")
    if n_trades == 0:
        raise SystemExit("no closed round-trips produced — cannot export an empty stream")

    stream = build_stream(fills_by_symbol, trades_by_symbol, params, git_head())
    total_pnl = sum(t.realized_pnl for t in stream.trades)
    wins = sum(1 for t in stream.trades if t.realized_pnl > 0)
    print(f"Total net P&L (return units): {total_pnl:+.4f} | win rate: {wins}/{len(stream.trades)}")

    out_path = Path(args.out)
    save_trade_stream(stream, out_path)
    print(f"Saved stream: {out_path} (provenance {stream.provenance_hash[:16]}...)")

    # Round-trip verification: load from disk and confirm identity
    reloaded = load_trade_stream(out_path)
    assert reloaded == stream, "round-trip verification failed"
    print("Round-trip verification: OK")

    # First real diagnostic runs on the persisted stream
    perm = run_permutation_test(reloaded, n_permutations=500, seed=42)
    boot = run_bootstrap_test(reloaded, n_resamples=500, seed=42)
    hist = perm.historical.metrics
    print("\nHistorical path (return units, per-symbol round-trips):")
    print(f"  total_pnl={hist.total_pnl:+.4f}  trades={hist.trade_count}")
    print(f"  max_dd={hist.max_drawdown:.4f}  longest_loss_streak={hist.longest_losing_streak}")
    print(f"  B1 percentile max_drawdown: {perm.historical.percentile['max_drawdown']:.3f}")
    print(f"  B2 percentile total_pnl:    {boot.historical.percentile['total_pnl']:.3f}")
    q = boot.quantiles["total_pnl"]
    print(f"  B2 total_pnl q05/q50/q95:   {q['q0.05']:+.4f} / {q['q0.5']:+.4f} / {q['q0.95']:+.4f}")
    print("\nMethodological rule: conditional diagnostics under the resampling")
    print("assumptions — NOT a forecast of future returns or profitability.")


if __name__ == "__main__":
    main()
