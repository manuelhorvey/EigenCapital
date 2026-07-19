#!/usr/bin/env python3
"""
Monte Carlo drawdown simulation — bootstraps daily portfolio returns from
walk-forward OOS signal parquets to estimate drawdown risk over
1-year, 3-year, and 5-year horizons.

V2: Converts R-multiples to % portfolio returns using per-asset ATR_pct
and allocation weights. The old R-space version (p_positive_return ~ 1.0)
answered the wrong question. This version reports actual % capital outcomes.

Methodology
-----------
For each asset on each day with an active signal:

    return_pct = daily_R * ATR_pct * allocation_pct

Where:
    daily_R     = compute_trade_pnl(signal, label, tp, sl)  -- +/-tp_mult or +/-sl_mult
    ATR_pct     = ATR / close_price  (14-day ATR from OHLCV data)
    allocation  = 1 / N_active       (equal-weight across active assets)

The portfolio daily % return is the sum of per-asset % returns.
Then we block-bootstrap these daily % returns to estimate drawdown risk.

Still NOT captured (conservative estimates):
    - Slippage, spread costs, commissions
    - Position sizing guardrails (drawdown taper, position caps, leverage budget)
    - MT5 lot quantization (0.01 lot minimum)
    - Partial fills and execution delay
    - Intraday risk (all returns assumed daily close-to-close)

Results are optimistic — use as upper-bound estimate.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/monte_carlo_drawdown.py
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/monte_carlo_drawdown.py --n-sim 50000 --output mc_results.json
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from shared.volatility import compute_atr_pct

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("monte_carlo")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"  # scripts/walkforward/ (matches subprocess outputs)
RAWDIR = Path(__file__).resolve().parent.parent.parent / "data" / "raw"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "NZDCHF",
        "EURAUD",
    }
)

SELL_ONLY_ACTIVE = True


def compute_trade_pnl(signal: int, label: int, tp: float, sl: float) -> float:
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


def _resolve_ohlcv_path(asset_name: str) -> str | None:
    base = asset_name.replace("^", "").replace("=X", "").replace("=F", "")
    candidates = [
        Path(RAWDIR) / f"{asset_name}_X_1d.parquet",
        Path(RAWDIR) / f"{base}_1d.parquet",
        Path(RAWDIR) / f"{base}_F_1d.parquet",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def _fetch_ohlcv(ticker: str, asset_name: str) -> pd.DataFrame:
    """Fetch OHLCV data — try local parquet first, fall back to yfinance."""
    local_path = _resolve_ohlcv_path(asset_name)
    if local_path is not None:
        logger.debug("  %s: loading OHLCV from %s", asset_name, local_path)
        return pd.read_parquet(local_path)
    logger.debug("  %s: no local OHLCV — fetching from yfinance (%s)", asset_name, ticker)
    try:
        from features.data_fetch import fetch_asset_ohlcv
        df = fetch_asset_ohlcv(ticker)
        if df.empty:
            logger.warning("  %s: yfinance OHLCV returned empty", asset_name)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("  %s: yfinance OHLCV failed: %s", asset_name, exc)
        return pd.DataFrame()


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def load_asset_tickers() -> dict[str, str]:
    """Load per-asset yfinance tickers from the production config."""
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, str] = {}
    for name, acfg in cfg.assets.items():
        result[name] = str(acfg.get("ticker", name))
    return result


def load_daily_portfolio_returns(
    sell_only: bool = True,
    tag: str = "",
) -> tuple[pd.Series, pd.Series]:
    if tag:
        pattern = Path(WALKDIR) / f"*_wf_signals_{tag}.parquet"
    else:
        pattern = Path(WALKDIR) / "*_wf_signals.parquet"
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No signal parquets found in {WALKDIR}")

    pt_sl = load_pt_sl()
    tickers = load_asset_tickers()

    asset_signals: dict[str, pd.DataFrame] = {}
    asset_atr: dict[str, pd.Series] = {}
    for fpath in files:
        stem = Path(fpath).name
        suffix = f"_wf_signals_{tag}.parquet" if tag else "_wf_signals.parquet"
        name = stem.replace(suffix, "")
        if name not in pt_sl:
            logger.warning("No pt_sl config for %s — skipping", name)
            continue

        df = pd.read_parquet(fpath)
        # Normalise to timezone-naive UTC date for cross-asset alignment
        if df.index.tz is not None:
            df.index = df.index.tz_convert("UTC").tz_localize(None)
        asset_signals[name] = df

        ticker = tickers.get(name, name)
        ohlcv = _fetch_ohlcv(ticker, name)
        if ohlcv.empty:
            logger.warning("  %s: no OHLCV data — ATR_pct set to 0", name)
            asset_atr[name] = pd.Series(0.0, index=df.index)
        else:
            atr_pct = compute_atr_pct(ohlcv, period=14)
            if atr_pct.index.tz is not None:
                atr_pct.index = atr_pct.index.tz_convert("UTC").tz_localize(None)
            atr_aligned = atr_pct.reindex(df.index, method="ffill").fillna(0.0)
            asset_atr[name] = atr_aligned

        logger.info("  %s: loaded %d signals + ATR_pct", name, len(df))

    all_dates = sorted(set(d for df in asset_signals.values() for d in df.index))
    r_daily: list[float] = []
    pct_daily: list[float] = []

    for d in all_dates:
        day_rs: list[float] = []
        day_pcts: list[float] = []

        for name, df in asset_signals.items():
            if d not in df.index:
                continue
            row = df.loc[d]
            sig = int(row["signal"])
            if sell_only and name in SELL_ONLY_ASSETS and sig == 1:
                sig = 0
            if sig == 0:
                continue

            lbl = int(row["label"])
            tp, sl = pt_sl.get(name, (2.0, 2.0))
            r = compute_trade_pnl(sig, lbl, tp, sl)

            day_rs.append(r)

            atr_p = asset_atr[name].loc[d] if d in asset_atr[name].index else 0.0
            day_pcts.append(r * atr_p)

        if day_rs:
            r_daily.append(float(np.mean(day_rs)))
            pct_daily.append(float(np.mean(day_pcts)))
        else:
            r_daily.append(0.0)
            pct_daily.append(0.0)

    idx = pd.DatetimeIndex(all_dates)
    return pd.Series(r_daily, index=idx), pd.Series(pct_daily, index=idx)


def simulate_equity_curves(
    daily_returns: np.ndarray,
    n_simulations: int = 10_000,
    horizons_days: list[int] | None = None,
    block_size: int = 10,
    seed: int = 42,
    is_pct: bool = False,
) -> dict:
    if horizons_days is None:
        horizons_days = [252, 756, 1260]

    rng = np.random.default_rng(seed)
    n_obs = len(daily_returns)
    n_blocks_total = n_obs - block_size + 1

    results: dict[int, list[dict]] = {h: [] for h in horizons_days}

    units = "%" if is_pct else "R"
    logger.info(
        "Running %d simulations across %d horizons (%s-space, block_size=%d)...",
        n_simulations,
        len(horizons_days),
        units,
        block_size,
    )
    t0 = time.monotonic()

    for sim_idx in range(n_simulations):
        if sim_idx > 0 and sim_idx % 2000 == 0:
            elapsed = time.monotonic() - t0
            rate = sim_idx / elapsed
            eta = (n_simulations - sim_idx) / rate
            logger.info("  %d/%d simulations (%.1f/s, ETA %.0fs)", sim_idx, n_simulations, rate, eta)

        for h in horizons_days:
            n_blocks_needed = int(np.ceil(h / block_size))
            n_total = n_blocks_needed * block_size
            sampled = np.empty(n_total, dtype=daily_returns.dtype)

            for b in range(n_blocks_needed):
                start = rng.integers(0, n_blocks_total)
                sampled[b * block_size : (b + 1) * block_size] = daily_returns[start : start + block_size]

            sampled_returns = sampled[:h]

            if is_pct:
                growth = 1.0 + sampled_returns
                equity = np.cumprod(growth)
                peak = np.maximum.accumulate(equity)
                drawdown = (equity - peak) / peak
                total_return = float(equity[-1] - 1.0)
                max_dd = float(np.min(drawdown))
            else:
                equity = np.cumsum(sampled_returns)
                peak = np.maximum.accumulate(equity)
                drawdown = equity - peak
                total_return = float(np.sum(sampled_returns))
                max_dd = float(np.min(drawdown))

            n_up = int(np.sum(sampled_returns > 0))

            results[h].append(
                {
                    "total_return": total_return,
                    "max_dd": max_dd,
                    "n_up": n_up,
                    "n_total": h,
                }
            )

    elapsed = time.monotonic() - t0
    logger.info("Done — %d simulations in %.1fs (%.1f/s)", n_simulations, elapsed, n_simulations / elapsed)
    return results


def compute_dd_var(values: list[float], percentile: float) -> float:
    sorted_v = sorted(values)
    idx = int(len(sorted_v) * percentile)
    return sorted_v[idx]


def analyze_results(results: dict[int, list[dict]]) -> dict:
    summary: dict = {}
    for horizon, sims in results.items():
        dd_values = [s["max_dd"] for s in sims]
        tr_values = [s["total_return"] for s in sims]
        up_ratios = [s["n_up"] / s["n_total"] for s in sims]

        year_label = f"{horizon // 252}y" if horizon % 252 == 0 else f"{horizon}d"
        summary[year_label] = {
            "horizon_days": horizon,
            "n_simulations": len(sims),
            "expected_total_return": round(float(np.mean(tr_values)), 6),
            "median_total_return": round(float(np.median(tr_values)), 6),
            "std_total_return": round(float(np.std(tr_values)), 6),
            "expected_max_dd": round(float(np.mean(dd_values)), 6),
            "median_max_dd": round(float(np.median(dd_values)), 6),
            "std_max_dd": round(float(np.std(dd_values)), 6),
            "var_95_dd": round(compute_dd_var(dd_values, 0.05), 6),
            "var_99_dd": round(compute_dd_var(dd_values, 0.01), 6),
            "worst_dd": round(float(np.min(dd_values)), 6),
            "best_dd": round(float(np.max(dd_values)), 6),
            "p_positive_return": round(float(np.mean([v > 0 for v in tr_values])), 6),
            "expected_up_ratio": round(float(np.mean(up_ratios)), 6),
        }

    return summary


def format_report(summary: dict, units: str) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"MONTE CARLO DRAWDOWN SIMULATION ({units}-space)")
    lines.append("=" * 72)
    lines.append(f"SELL_ONLY filter active: {SELL_ONLY_ACTIVE}")
    lines.append(f"Assets: 16 ({len(SELL_ONLY_ASSETS)} SELL_ONLY, {16 - len(SELL_ONLY_ASSETS)} full two-way)")
    lines.append(f"Units: {units} of capital")
    lines.append("")

    for label in sorted(summary.keys()):
        s = summary[label]
        lines.append("-" * 72)
        lines.append(f"Horizon: {label} ({s['horizon_days']} trading days)")
        lines.append(f"Simulations: {s['n_simulations']:,}")
        lines.append("")
        lines.append(f"  -- Return ({units}) --")
        lines.append(f"  Expected total:     {s['expected_total_return']:>10.4f}")
        lines.append(f"  Median total:       {s['median_total_return']:>10.4f}")
        lines.append(f"  Std total:          {s['std_total_return']:>10.4f}")
        lines.append(f"  P(positive return): {s['p_positive_return']:>7.1%}")
        lines.append("")
        lines.append(f"  -- Drawdown ({units}) --")
        lines.append(f"  Expected max DD:    {s['expected_max_dd']:>10.4f}")
        lines.append(f"  Median max DD:      {s['median_max_dd']:>10.4f}")
        lines.append(f"  95%% VaR of DD:      {s['var_95_dd']:>10.4f}  (5%% chance of worse)")
        lines.append(f"  99%% VaR of DD:      {s['var_99_dd']:>10.4f}  (1%% chance of worse)")
        lines.append(f"  Worst DD observed:  {s['worst_dd']:>10.4f}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("NOTES:")
    if units == "R":
        lines.append("  R-multiples are additive, dimensionless. P~1.0 expected.")
        lines.append("  This is the LEGACY methodology. Use %-space for real drawdown estimates.")
    else:
        lines.append("  %-space uses geometric compounding (cumulative product).")
        lines.append("  Still NOT captured: slippage, spread, commissions, position sizing guardrails,")
        lines.append("  MT5 lot quantization, partial fills, intraday risk.")
        lines.append("  Results are optimistic -- use as upper-bound estimate.")
    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo drawdown simulation with ATR_pct conversion")
    parser.add_argument("--n-sim", type=int, default=10_000, help="Number of simulations (default: 10,000)")
    parser.add_argument("--output", default=None, help="Path to save JSON results (optional)")
    parser.add_argument("--no-sell-only", action="store_true", help="Disable SELL_ONLY filter")
    parser.add_argument("--tag", default="", help="Signal parquet tag suffix (retrained, baseline, etc.)")
    parser.add_argument("--r-space", action="store_true", help="Also run legacy R-space version")

    args = parser.parse_args()

    global SELL_ONLY_ACTIVE
    SELL_ONLY_ACTIVE = not args.no_sell_only

    logger.info("Loading daily portfolio returns with ATR_pct conversion (tag=%s)...", args.tag or "(none)")
    r_series, pct_series = load_daily_portfolio_returns(sell_only=SELL_ONLY_ACTIVE, tag=args.tag)

    logger.info("Loaded %d daily returns", len(r_series))
    logger.info("  R-space:   mean=%.6f  std=%.6f  total=%.2f", r_series.mean(), r_series.std(), r_series.sum())
    logger.info(
        "  %%-space:   mean=%.6f  std=%.6f  total=%.4f%%", pct_series.mean(), pct_series.std(), pct_series.sum() * 100
    )

    for is_pct, series, label in [(False, r_series, "R-space"), (True, pct_series, "%-space")]:
        vals = series.values
        if is_pct:
            growth = 1.0 + vals
            equity = np.cumprod(growth)
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            total_ret = equity[-1] - 1.0
            max_dd_val = dd.min()
        else:
            equity = np.cumsum(vals)
            peak = np.maximum.accumulate(equity)
            dd = equity - peak
            total_ret = vals.sum()
            max_dd_val = dd.min()

        sharpe = (vals.mean() / vals.std() * np.sqrt(252)) if vals.std() > 0 else 0
        logger.info("Empirical %s: total=%.4f  max_dd=%.4f  Sharpe=%.2f", label, total_ret, max_dd_val, sharpe)

    logger.info("Running %%-space Monte Carlo...")
    pct_results = simulate_equity_curves(
        daily_returns=pct_series.values,
        n_simulations=args.n_sim,
        horizons_days=[252, 756, 1260],
        is_pct=True,
    )
    pct_summary = analyze_results(pct_results)
    print(format_report(pct_summary, units="%"))

    if args.r_space:
        logger.info("Running R-space Monte Carlo (legacy, comparison only)...")
        r_results = simulate_equity_curves(
            daily_returns=r_series.values,
            n_simulations=args.n_sim,
            horizons_days=[252, 756, 1260],
            is_pct=False,
        )
        r_summary = analyze_results(r_results)
        print(format_report(r_summary, units="R"))

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        combined = {
            "sell_only_active": SELL_ONLY_ACTIVE,
            "n_simulations": args.n_sim,
            "n_empirical_days": len(r_series),
            "empirical": {
                "r_space": {
                    "total": round(float(r_series.sum()), 4),
                    "mean": round(float(r_series.mean()), 6),
                    "std": round(float(r_series.std()), 6),
                    "sharpe": round(float(r_series.mean() / r_series.std() * np.sqrt(252)), 4)
                    if r_series.std() > 0
                    else 0,
                },
                "pct_space": {
                    "total_pct": round(float(pct_series.sum() * 100), 4),
                    "mean_pct": round(float(pct_series.mean() * 100), 6),
                    "std_pct": round(float(pct_series.std() * 100), 6),
                    "sharpe": round(float(pct_series.mean() / pct_series.std() * np.sqrt(252)), 4)
                    if pct_series.std() > 0
                    else 0,
                },
            },
            "pct_space": pct_summary,
        }
        if args.r_space:
            combined["r_space"] = r_summary

        with open(out_path, "w") as f:
            json.dump(combined, f, indent=2)
        logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
