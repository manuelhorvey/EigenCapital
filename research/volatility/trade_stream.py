"""Trade population for Question B — PIT-corrected R4 replica replay.

Reuses the FROZEN R4 signal implementation from
scripts/export_r4_trade_stream.py (imported, never modified) and the same
parameters, costs, and weekly schedule. One documented correction versus
the frozen exporter:

  FROZEN BEHAVIOR (defect, documented): execution at the open of the
  signal date itself, while weights use close-of-signal-date information
  (one-bar signal/execution timing violation of its own "next-bar open"
  docstring — verified empirically at acquisition time).

  PIT REPLAY (this module): execution strictly at the open of the NEXT
  trading day after each signal date (searchsorted side='right').

The frozen 1,311-trade stream remains available as a robustness
comparator via load_frozen_stream(). No file under scripts/ or data/mt5/
is ever modified.
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass

import pandas as pd

from research.volatility import config as C

_EXPORTER: object | None = None


def _exporter():
    """Import the frozen exporter module once (read-only reuse)."""
    global _EXPORTER
    if _EXPORTER is None:
        path = C.REPO / "scripts" / "export_r4_trade_stream.py"
        spec = importlib.util.spec_from_file_location("r4_frozen_exporter", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        _EXPORTER = mod
    return _EXPORTER


@dataclass(frozen=True)
class PathTrade:
    """One closed round-trip with fill-level identity for path reconstruction."""

    trade_id: int  # deterministic 1-based index (entry order per symbol)
    instrument: str  # CSV stem e.g. AUDUSDm
    asset: str  # baseline asset name e.g. AUDUSD
    side: str  # LONG | SHORT
    signal_date: pd.Timestamp  # weekly signal row that triggered the entry
    entry_ts: pd.Timestamp  # fill timestamp (open of entry bar)
    exit_ts: pd.Timestamp
    entry_px: float
    exit_px: float
    weight: float  # signed portfolio weight at entry (|w| for costs)
    net_pnl: float  # portfolio return units, net of both cost legs
    costs: float  # portfolio return units (2 * one_way * |w|)
    is_terminal_close: bool  # exit at final close rather than next open


def load_signal_and_data():
    """Frozen params + 8-symbol bars + frozen R4 weights (PIT row-by-row)."""
    m = _exporter()
    params = m.load_config_params()
    data = m.load_bars()
    weights = m.compute_r4_signal(data, params)
    return m, params, data, weights


def _next_day_strict(index: pd.DatetimeIndex, date) -> pd.Timestamp | None:
    pos = index.searchsorted(date, side="right")
    return pd.Timestamp(index[pos]) if pos < len(index) else None


def simulate_portfolio_pit(
    data: dict[str, pd.DataFrame],
    weights: pd.DataFrame,
    params: dict,
) -> dict[str, list[dict]]:
    """Weekly next-strict-day-open replay, executed on EACH SYMBOL'S OWN
    trading calendar.

    Two documented corrections versus the frozen simulator:

    1. Execution day is strictly after the signal date (the frozen exporter
       fills at the open of the signal date itself while weights use
       close-of-signal-date information — a one-bar lookahead).
    2. The fill bar is the symbol's own next bar after the signal, not a
       union-calendar date (XAUUSD has ~10 weekday gaps vs the FX pairs;
       union-calendar fills produced NaN prices there — exclusion, not
       imputation: each symbol only ever fills on its own observed bars).
    """
    cost = params["cost_one_way"]
    weekly = weights.iloc[:: params["rebalance_every"]]
    fills: dict[str, list[dict]] = {s: [] for s in data}
    open_pos: dict[str, dict] = {}
    target: dict[str, float] = {s: 0.0 for s in data}

    def _close(sym: str, ts, px: float) -> None:
        pos = open_pos.pop(sym)
        close_side = "SELL" if pos["weight"] > 0 else "BUY"
        gross = pos["weight"] * (px / pos["entry_px"] - 1.0)
        costs = 2.0 * cost * abs(pos["weight"])
        fills[sym].append(
            {
                "role": "CLOSE",
                "timestamp": pd.Timestamp(ts),
                "side": close_side,
                "fill_price": float(px),
                "weight": pos["weight"],
                "signal_date": pos["signal_date"],
                "net_pnl": gross - costs,
                "costs": costs,
                "entry_ts": pos["entry_ts"],
                "entry_px": pos["entry_px"],
            }
        )

    for w_date in weekly.index:
        for sym, df in data.items():
            exec_ts = _next_day_strict(df.index, w_date)
            if exec_ts is None:
                # no bar for this symbol after the signal — leave position
                # as-is (it will be re-evaluated at the next signal).
                continue
            raw = weekly.at[w_date, sym]
            new_w = 0.0 if pd.isna(raw) else float(raw)
            if abs(new_w - target[sym]) < 1e-9:
                continue
            if sym in open_pos:
                _close(sym, exec_ts, float(df.at[exec_ts, "open"]))
            if abs(new_w) > 1e-9:
                fills[sym].append(
                    {
                        "role": "OPEN",
                        "timestamp": pd.Timestamp(exec_ts),
                        "side": "BUY" if new_w > 0 else "SELL",
                        "fill_price": float(df.at[exec_ts, "open"]),
                        "weight": new_w,
                        "signal_date": pd.Timestamp(w_date),
                    }
                )
                open_pos[sym] = {
                    "weight": new_w,
                    "entry_ts": pd.Timestamp(exec_ts),
                    "entry_px": float(df.at[exec_ts, "open"]),
                    "signal_date": pd.Timestamp(w_date),
                }
            target[sym] = new_w

    for sym, df in data.items():
        if sym in open_pos:
            last_ts = df.index[-1]
            _close(sym, last_ts, float(df.at[last_ts, "close"]))

    # Pair OPEN/CLOSE records chronologically per symbol.
    trades: dict[str, list[dict]] = {}
    for sym, recs in fills.items():
        paired: list[dict] = []
        i = 0
        while i < len(recs):
            op, cl = recs[i], recs[i + 1]
            assert op["role"] == "OPEN" and cl["role"] == "CLOSE", (sym, op, cl)
            assert op["timestamp"] <= cl["timestamp"]
            assert math.isfinite(op["fill_price"]) and math.isfinite(cl["fill_price"])
            paired.append(
                {
                    **cl,
                    "open_side": op["side"],
                    "open_ts": op["timestamp"],
                    "open_px": op["fill_price"],
                    "open_weight": op["weight"],
                    "open_signal": op["signal_date"],
                }
            )
            i += 2
        assert i == len(recs), f"{sym}: unpaired fills (odd count)"
        trades[sym] = paired
    return trades


def build_path_trades(data: dict[str, pd.DataFrame], params: dict, weights: pd.DataFrame) -> list[PathTrade]:
    raw = simulate_portfolio_pit(data, weights, params)
    trades: list[PathTrade] = []
    tid = 0
    for sym in sorted(raw):
        last_ts = data[sym].index[-1]
        for rec in raw[sym]:
            tid += 1
            side = "LONG" if rec["open_side"] == "BUY" else "SHORT"
            trades.append(
                PathTrade(
                    trade_id=tid,
                    instrument=sym,
                    asset=sym[:-1] if sym.endswith("m") else sym,
                    side=side,
                    signal_date=rec["open_signal"],
                    entry_ts=rec["open_ts"],
                    exit_ts=rec["timestamp"],
                    entry_px=rec["open_px"],
                    exit_px=rec["fill_price"],
                    weight=rec["open_weight"],
                    net_pnl=rec["net_pnl"],
                    costs=rec["costs"],
                    is_terminal_close=bool(rec["timestamp"] == last_ts),
                )
            )
    trades.sort(key=lambda t: (t.exit_ts, t.instrument, t.entry_ts))
    # re-deterministic ids after sort
    trades = [PathTrade(**{**t.__dict__, "trade_id": i + 1}) for i, t in enumerate(trades)]
    return trades


def replay_pit_population() -> tuple[list[PathTrade], dict]:
    """Full PIT trade population + provenance dict for the report."""
    m, params, data, weights = load_signal_and_data()
    trades = build_path_trades(data, params, weights)
    provenance = {
        "population": "PIT_R4_D1_REPLAY_V1",
        "frozen_signal_source": "scripts/export_r4_trade_stream.py::compute_r4_signal (imported unmodified)",
        "execution_rule": "weekly weights.iloc[::5]; fill at OPEN of strictly next trading day after signal date",
        "frozen_defect_avoided": "frozen exporter fills at open of signal date itself (close-of-day signal) — lookahead",
        "params": {k: (float(v) if isinstance(v, float) else int(v)) for k, v in params.items()},
        "symbols": sorted({t.instrument for t in trades}),
        "n_trades": len(trades),
        "n_by_symbol": {s: sum(1 for t in trades if t.instrument == s) for s in sorted({t.instrument for t in trades})},
    }
    return trades, provenance


def load_frozen_stream():
    """The frozen TS-R4-D1-0001 stream (robustness comparator only).

    Regenerated deterministically via the exporter's own functions; if a
    persisted file exists under reports/ it is preferred.
    """
    from eigencapital.research.monte_carlo.persistence import load_trade_stream

    default = C.REPO / "reports" / "r1_monte_carlo" / "trade_stream_R4_daily.json"
    if default.is_file():
        return load_trade_stream(default)
    m = _exporter()
    params = m.load_config_params()
    data = m.load_bars()
    weights = m.compute_r4_signal(data, params)
    fills, trades_by_symbol = m.simulate_portfolio(data, weights, params)
    import subprocess

    try:
        commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, cwd=C.REPO).strip()
    except (subprocess.CalledProcessError, OSError):
        commit = ""
    return m.build_stream(fills, trades_by_symbol, params, commit)
