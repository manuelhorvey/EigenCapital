#!/usr/bin/env python3
"""
Reconstruct live-equivalent portfolio weights for any historical period
and verify they match what the live engine actually used.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/replay_rebalance.py
    PYTHONPATH=$PYTHONPATH:. python scripts/replay_rebalance.py --verify
    PYTHONPATH=$PYTHONPATH:. python scripts/replay_rebalance.py --save weights.csv
    PYTHONPATH=$PYTHONPATH:. python scripts/replay_rebalance.py --compare
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from shared.portfolio_weights import rolling_weight_matrix

logger = logging.getLogger("replay_rebalance")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"
DATADIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "paper_trading.yaml"


def load_price_data(
    assets: list[str],
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load daily close prices for all assets over the available history.

    Uses yfinance as fallback source matching the live data_fetch.py path.
    """
    import yfinance as yf

    price_data: dict[str, pd.Series] = {}
    for asset in assets:
        try:
            ticker = _asset_ticker(asset)
            hist = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                price_data[asset] = hist["Close"].squeeze()
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", asset, e)

    if not price_data:
        return pd.DataFrame()

    df = pd.DataFrame(price_data)
    df = df.dropna(how="all", axis=1)
    if start:
        df = df[df.index >= start]
    if end:
        df = df[df.index <= end]
    return df


def _asset_ticker(asset: str) -> str:
    """Map asset name to yfinance ticker."""
    import yaml

    if not CONFIG_PATH.exists():
        return asset
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    acfg = (cfg.get("assets") or {}).get(asset, {})
    return acfg.get("ticker", asset)


def load_signal_parquets(walk_dir: str | Path = WALKDIR, tag: str = "base") -> dict[str, pd.DataFrame]:
    """Load per-asset signal parquets."""
    walk_dir = Path(walk_dir)
    suffix = f"_wf_signals_{tag}.parquet"
    signals: dict[str, pd.DataFrame] = {}
    for fpath in sorted(walk_dir.glob(f"*{suffix}")):
        asset = fpath.name.replace(suffix, "")
        df = pd.read_parquet(fpath)
        if not df.empty:
            signals[asset] = df.sort_index()
    return signals


def load_wal_events(wal_dir: str | Path, event_type: str = "portfolio_weights") -> list[dict]:
    """Load WAL events of a given type from JSONL files."""

    wal_dir = Path(wal_dir)
    events: list[dict] = []
    for fpath in sorted(wal_dir.glob(f"*{event_type}*")):
        with open(fpath) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return events


def compute_portfolio_r_from_signals(
    asset_daily_r: dict[str, pd.Series],
    weights_df: pd.DataFrame,
    min_assets: int = 15,
) -> pd.Series:
    """Compute weighted portfolio daily R from weight matrix and per-asset daily R."""
    combined = pd.DataFrame(asset_daily_r)
    if hasattr(combined.index, "tz") and combined.index.tz is not None:
        combined.index = combined.index.tz_localize(None)
    aligned_w = weights_df.reindex(combined.index, method="ffill").bfill()
    valid_dates = aligned_w.index.intersection(combined.index)
    portfolio_r = (combined.loc[valid_dates] * aligned_w.loc[valid_dates].values).sum(axis=1)
    n_assets = combined.loc[valid_dates].notna().sum(axis=1)
    portfolio_r = portfolio_r[n_assets >= min_assets]
    return portfolio_r


def compare_to_wal(
    reconstructed: pd.DataFrame,
    wal_events: list[dict],
    tolerance: float = 0.01,
) -> dict:
    """Compare reconstructed weights to actual WAL events.

    Returns dict of divergences keyed by cycle number.
    """
    divergences: dict = {}
    for event in wal_events:
        event_date = event.get("timestamp", "")[:10]
        if event_date not in reconstructed.index:
            continue
        reconstructed_w = reconstructed.loc[event_date].to_dict()
        actual_w = event.get("weights", {})

        all_assets = set(reconstructed_w) | set(actual_w)
        deltas = {a: abs(reconstructed_w.get(a, 0) - actual_w.get(a, 0)) for a in sorted(all_assets)}
        max_delta = max(deltas.values())
        if max_delta > tolerance:
            divergences[event.get("cycle", "?")] = {
                "date": event_date,
                "max_delta": max_delta,
                "assets": {a: d for a, d in deltas.items() if d > tolerance},
            }
    return divergences


def equal_weight_portfolio_r(asset_daily_r: dict[str, pd.Series], min_assets: int = 15) -> pd.Series:
    """Equal-weight portfolio daily R (legacy method)."""
    combined = pd.DataFrame(asset_daily_r)
    n_assets = combined.notna().sum(axis=1)
    portfolio_r = combined.mean(axis=1)
    return portfolio_r[n_assets >= min_assets]


def compute_asset_daily_r_from_parquet(
    df: pd.DataFrame,
    tp: float,
    sl: float,
) -> pd.Series:
    """Compute daily R-multiple series from signal parquet."""
    r = np.zeros(len(df), dtype=float)
    signals = df["signal"].values
    labels = df["label"].values

    buy_mask = signals == 1
    sell_mask = signals == -1

    r[buy_mask & (labels == 1)] = tp
    r[buy_mask & (labels == 0)] = -sl
    r[sell_mask & (labels == 0)] = tp
    r[sell_mask & (labels == 1)] = -sl

    return pd.Series(r, index=df.index, name="daily_r")


def load_pt_sl_from_config() -> dict[str, tuple[float, float]]:
    """Load per-asset pt_sl from the production config."""
    import yaml

    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in (cfg.get("assets") or {}).items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def print_comparison(
    equal_weight_r: pd.Series,
    risk_parity_r: pd.Series,
    weight_df: pd.DataFrame,
) -> None:
    """Print side-by-side comparison of equal-weight vs risk-parity metrics."""
    from quorrin.domain.value_objects.statistical_metrics import sharpe_ratio

    def _metrics(r):
        sr = sharpe_ratio(r.values)
        cum = r.cumsum()
        running_max = cum.expanding().max()
        dd = cum - running_max
        max_dd = float(dd.min())
        calmar = float(r.sum() / abs(max_dd)) if max_dd < 0 else float("inf")
        return {
            "total_R": round(float(r.sum()), 2),
            "sharpe": round(sr, 4),
            "max_dd_R": round(max_dd, 2),
            "calmar": round(calmar, 2),
            "n_days": len(r),
        }

    eq = _metrics(equal_weight_r)
    rp = _metrics(risk_parity_r)

    print("=" * 72)
    print("PORTFOLIO COMPARISON")
    print("=" * 72)
    print(f"{'Metric':<20} {'Equal-Weight':<20} {'Risk Parity':<20} {'Delta':<20}")
    print("-" * 72)
    for k in ["total_R", "sharpe", "max_dd_R", "calmar", "n_days"]:
        eq_v = eq.get(k, 0)
        rp_v = rp.get(k, 0)
        if isinstance(eq_v, (int, float)) and isinstance(rp_v, (int, float)):
            delta = rp_v - eq_v
            print(f"{k:<20} {eq_v:<20.4f} {rp_v:<20.4f} {delta:<+20.4f}")
        else:
            print(f"{k:<20} {eq_v:<20} {rp_v:<20}")

    print()
    print("AVERAGE WEIGHT BY METHOD")
    print("-" * 72)
    mean_w = weight_df.mean().sort_values(ascending=False)
    for asset, w in mean_w.items():
        print(f"  {asset:<12} {w:.4f}")

    print()
    print("WEIGHT TURNOVER (mean absolute change per day)")
    turnover = weight_df.diff().abs().sum(axis=1).mean()
    print(f"  Mean daily turnover: {turnover:.4f}")


def main():
    parser = argparse.ArgumentParser(description="Replay portfolio weights and verify parity")
    parser.add_argument("--verify", action="store_true", help="Compare reconstructed weights vs WAL events")
    parser.add_argument("--save", type=str, default=None, help="Save weight matrix to CSV")
    parser.add_argument("--method", default="risk_parity_v1", choices=["equal_v1", "risk_parity_v1", "hrp_v1"])
    parser.add_argument("--window", type=int, default=252, help="Covariance window (default 252)")
    parser.add_argument("--compare", action="store_true", help="Compare equal-weight vs risk-parity metrics")
    parser.add_argument("--tag", default="base", help="Signal parquet tag (default base)")
    parser.add_argument("--wal-dir", type=str, default=None, help="WAL directory for --verify")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    pt_sl = load_pt_sl_from_config()
    assets = list(pt_sl.keys())
    if not assets:
        logger.error("No assets found in config")
        return

    print(f"Loading price data for {len(assets)} assets...")
    prices = load_price_data(assets)
    if prices.empty:
        logger.error("No price data loaded — cannot reconstruct weights")
        return

    returns = prices.pct_change().dropna()
    print(f"Returns shape: {returns.shape}")

    print(f"Reconstructing {args.method} weights (window={args.window})...")
    weights = rolling_weight_matrix(returns, args.method, window=args.window)
    print(f"Weight matrix shape: {weights.shape}")

    if weights.empty:
        logger.error("Weight matrix is empty — insufficient data")
        return

    if args.save:
        out_path = Path(args.save)
        weights.to_csv(out_path)
        print(f"Saved weight matrix to {out_path}")

    if args.verify:
        wal_dir = args.wal_dir or str(DATADIR / "live" / "wal")
        wal_events = load_wal_events(wal_dir)
        if not wal_events:
            print("No WAL portfolio_weights events found — cannot verify")
        else:
            divergences = compare_to_wal(weights, wal_events)
            if divergences:
                print(f"DIVERGENCES FOUND: {len(divergences)} cycles")
                for cycle, info in sorted(divergences.items()):
                    print(f"  Cycle {cycle} ({info['date']}): max Δ={info['max_delta']:.4f}")
                    for asset, delta in info["assets"].items():
                        print(f"    {asset}: Δ={delta:.4f}")
            else:
                print("PARITY CONFIRMED: all cycles within tolerance")

    if args.compare:
        print(f"\nLoading signals (tag={args.tag})...")
        signals = load_signal_parquets(tag=args.tag)

        print("Computing per-asset daily R series...")
        daily_r = {}
        for asset, df in signals.items():
            tp, sl = pt_sl.get(asset, (2.0, 2.0))
            daily_r[asset] = compute_asset_daily_r_from_parquet(df, tp, sl)

        common_assets = set(daily_r) & set(weights.columns)
        if not common_assets:
            logger.error("No overlapping assets between signals and weights")
            return

        print(f"Computing portfolio metrics ({len(common_assets)} overlapping assets)...")

        eq_r = equal_weight_portfolio_r(daily_r)
        rp_r = compute_portfolio_r_from_signals(daily_r, weights)

        print_comparison(eq_r, rp_r, weights)


if __name__ == "__main__":
    main()
