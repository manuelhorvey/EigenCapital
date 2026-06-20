#!/usr/bin/env python3
"""
Walk-forward PnL backtest from OOS signal parquets.

Reads per-asset signal parquets (signal, label, p_long) from the walk-
forward output directory, computes R-multiple PnL using triple-barrier
label semantics (TP/SL first-touch), and reports per-asset and portfolio-
level metrics.

Usage:
    # Base-only (default)
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py

    # Compare ensemble vs base
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py --ensemble-tag ensemble

    # Custom signal tag and output path
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest_pnl.py --tag base --output pnl_results.csv

R-multiples assume equal risk-per-trade (1R = ATR * sl_mult for each asset).
Does not reflect live position sizing, correlation-adjusted portfolio risk,
or transaction costs.  Not currency PnL.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("backtest_pnl")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"

# ── Core PnL function (isolated, testable) ──────────────────────────────────


def compute_trade_pnl(signal: int, label: int, tp: float, sl: float) -> float:
    """Return PnL in R-multiples for a single trade.

    Parameters
    ----------
    signal : int
        -1 (SELL), 0 (FLAT), or 1 (BUY).
    label : int
        Binary triple-barrier label from the LONG perspective:
        0 = lower (SL) hit first, 1 = upper (TP) hit first.
    tp, sl : float
        Take-profit and stop-loss multipliers in ATR units.

    Semantics
        BUY  (signal=1):  label=1 → TP hit first → +tp × R
                           label=0 → SL hit first → -sl × R
        SELL (signal=-1): label=1 → upper(SL) hit → -sl × R
                           label=0 → lower(TP) hit → +tp × R
        FLAT (signal=0):  0.0 regardless of label.
    """
    if signal == 1:
        return tp if label == 1 else -sl
    if signal == -1:
        return tp if label == 0 else -sl
    return 0.0


# ── Per-asset processing ────────────────────────────────────────────────────


def load_asset_signals(parquet_path: str) -> pd.DataFrame:
    """Load a single asset's OOS signal parquet."""
    df = pd.read_parquet(parquet_path)
    if df.empty:
        return df
    return df.sort_index()


def _asset_pt_sl_from_config() -> dict[str, tuple[float, float]]:
    """Load per-asset pt_sl from the production config (same as walk-forward)."""
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def compute_asset_daily_r(
    df: pd.DataFrame,
    tp: float,
    sl: float,
) -> pd.Series:
    """Compute daily R-multiple series from a signal parquet.

    Each non-flat signal is converted to its R-multiple via
    ``compute_trade_pnl``.  Flat signals contribute 0.0 for that day.
    Returns a daily-frequency Series indexed by the parquet's datetime index.
    """
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


def asset_metrics(daily_r: pd.Series) -> dict:
    """Compute summary metrics from a daily R series.

    Returns
    -------
    dict with keys: n_trades (non-flat days), win_rate, total_R,
    avg_R, profit_factor, sharpe (annualised), max_drawdown, calmar.
    """
    n_trades = int((daily_r != 0).sum())
    if n_trades == 0:
        return {k: 0.0 for k in ("n_trades", "win_rate", "total_R", "avg_R",
                                 "profit_factor", "sharpe", "sharpe_adj",
                                 "max_dd_R", "calmar")}

    wins = daily_r[daily_r > 0]
    losses = daily_r[daily_r < 0]
    total_R = float(daily_r.sum())
    avg_R = float(daily_r[daily_r != 0].mean())
    win_rate = len(wins) / n_trades
    profit_factor = abs(wins.sum() / losses.sum()) if len(losses) > 0 else float("inf")

    # Sharpe from daily R (annualised, 252 trading days)
    sharpe = float(daily_r.mean() / daily_r.std() * np.sqrt(252)) if daily_r.std() > 0 else 0.0

    # Autocorrelation-adjusted Sharpe (Lo, 2002)
    rho = daily_r.autocorr() if len(daily_r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    # Drawdown in R-units (peak-to-trough from cumulative R)
    cum = daily_r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())
    calmar = float(total_R / abs(max_dd_r)) if max_dd_r < 0 else float("inf")

    # Loss clustering — count days where >30% of this asset's trades lose
    # (single asset version; cross-asset done at portfolio level)
    loss_cluster_pct = float(len(losses) / max(n_trades, 1))

    return {
        "n_trades": n_trades,
        "win_rate": round(win_rate, 4),
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj": round(sharpe_adj, 4),
        "max_dd_R": round(max_dd_r, 2),
        "calmar": round(calmar, 2),
        "loss_ratio": round(loss_cluster_pct, 4),
    }


# ── Portfolio aggregation ────────────────────────────────────────────────────


def build_portfolio_daily_r(
    asset_series: dict[str, pd.Series],
    min_assets: int = 15,
) -> pd.DataFrame:
    """Build equal-weight portfolio daily R series.

    Parameters
    ----------
    asset_series : dict[str, pd.Series]
        Per-asset daily R series (indexed by datetime).
    min_assets : int
        Minimum number of assets required on a given day to include it.

    Returns
    -------
    DataFrame with columns: 'portfolio_r', 'n_assets', 'frac_red'.
    Index is the sorted union of all asset dates.
    """
    combined = pd.DataFrame(asset_series)
    n_assets = combined.notna().sum(axis=1)
    frac_red = (combined < 0).sum(axis=1) / n_assets.replace(0, 1)

    portfolio_r = combined.mean(axis=1)  # equal-weight across available assets

    result = pd.DataFrame({
        "portfolio_r": portfolio_r,
        "n_assets": n_assets,
        "frac_red": frac_red,
    })
    # Apply minimum-asset floor
    result = result[result["n_assets"] >= min_assets].copy()
    return result


def portfolio_metrics(
    pf_df: pd.DataFrame,
    loss_cluster_threshold: float = 0.30,
) -> dict:
    """Compute portfolio-level metrics.

    Parameters
    ----------
    pf_df : DataFrame from build_portfolio_daily_r.
    loss_cluster_threshold : float
        Fraction of active assets that must be red to count as a
        "loss cluster" day (default 0.30).

    Returns
    -------
    dict of metrics.
    """
    r = pf_df["portfolio_r"]
    n_days = len(r)
    if n_days == 0:
        return {k: 0.0 for k in ("n_days", "total_R", "avg_R", "sharpe",
                                 "sharpe_adj", "max_dd_R", "calmar",
                                 "n_loss_cluster_days", "n_weekly_clusters",
                                 "median_n_assets")}

    total_R = float(r.sum())
    avg_R = float(r.mean())
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0

    cum = r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())
    calmar = float(total_R / abs(max_dd_r)) if max_dd_r < 0 else float("inf")

    # Autocorrelation-adjusted Sharpe (Lo, 2002)
    rho = r.autocorr() if len(r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    # Loss cluster days: >threshold fraction of active assets red
    cluster_days = (pf_df["frac_red"] > loss_cluster_threshold).sum()

    # Weekly cluster: weeks with >= 2 cluster days
    weekly_clusters = (
        pf_df[pf_df["frac_red"] > loss_cluster_threshold]
        .resample("W")["frac_red"]
        .count()
    )
    n_weekly_clusters = int((weekly_clusters >= 2).sum())

    return {
        "n_days": n_days,
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj": round(sharpe_adj, 4),
        "max_dd_R": round(max_dd_r, 2),
        "calmar": round(calmar, 2),
        "n_loss_cluster_days": int(cluster_days),
        "n_weekly_clusters": n_weekly_clusters,
        "median_n_assets": int(pf_df["n_assets"].median()),
    }


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Walk-forward PnL backtest from OOS signal parquets"
    )
    parser.add_argument(
        "--tag",
        default="base",
        help="Signal parquet suffix (default 'base' → *_wf_signals_base.parquet)",
    )
    parser.add_argument(
        "--ensemble-tag",
        default=None,
        help="Second tag for ensemble-vs-base comparison (e.g. 'ensemble')",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path for per-asset metrics (default: walkforward/pnl_backtest_{tag}.csv)",
    )
    parser.add_argument(
        "--min-assets",
        type=int,
        default=15,
        help="Minimum assets for portfolio day inclusion (default 15)",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.30,
        help="Loss cluster threshold as fraction of active assets (default 0.30)",
    )
    parser.add_argument(
        "--sell-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply SELL-only filter for the 9 assets with inverted BUY calibration (default: True)",
    )
    args = parser.parse_args()
    tag = args.tag

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 72)
    print("WALK-FORWARD PnL BACKTEST")
    print("=" * 72)
    print()
    print("  R-multiples assume equal risk-per-trade (1R = ATR * sl_mult per asset).")
    print("  Does not reflect live position sizing, correlation-adjusted portfolio risk,")
    print("  or transaction costs.  Not currency PnL.")
    print()

    # Load per-asset pt_sl
    pt_sl_map = _asset_pt_sl_from_config()
    logger.info("Loaded pt_sl for %d assets from production config", len(pt_sl_map))

    # Discover signal parquets
    pattern = f"*_wf_signals_{tag}.parquet"
    parquets = sorted(WALKDIR.glob(pattern))
    if not parquets:
        logger.error("No parquets matching %s in %s", pattern, WALKDIR)
        sys.exit(1)
    logger.info("Found %d signal parquets for tag '%s'", len(parquets), tag)

    # Process each asset
    all_daily_r: dict[str, pd.Series] = {}
    per_asset_rows: list[dict] = []

    for pq in parquets:
        stem = pq.stem  # e.g. EURUSD_wf_signals_base
        # Asset name is everything before _wf_signals
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            logger.warning("No pt_sl config for %s — skipping", asset)
            continue
        tp, sl = pt_sl_map[asset]

        df = load_asset_signals(str(pq))
        if df.empty:
            logger.warning("%s: empty signal parquet — skipping", asset)
            continue

        # SELL-only filter for 9 assets with inverted BUY calibration
        if args.sell_only:
            SELL_ONLY_ASSETS = frozenset({
                "CADCHF", "AUDUSD", "ES", "NQ", "NZDCHF",
                "EURAUD", "^DJI", "USDCHF", "EURCHF",
            })
            if asset in SELL_ONLY_ASSETS:
                n_override = (df["signal"] == 1).sum()
                df.loc[df["signal"] == 1, "signal"] = 0
                if n_override > 0:
                    logger.info("%s: sell-only filter — overrode %d BUY signals to FLAT", asset, n_override)

        daily_r = compute_asset_daily_r(df, tp, sl)
        all_daily_r[asset] = daily_r

        metrics = asset_metrics(daily_r)
        metrics["asset"] = asset
        metrics["tp"] = tp
        metrics["sl"] = sl
        per_asset_rows.append(metrics)

    # Per-asset summary table
    per_asset_df = pd.DataFrame(per_asset_rows)
    per_asset_df = per_asset_df.set_index("asset")

    print("\nPer-Asset Results")
    print("-" * 72)
    display_cols = ["n_trades", "win_rate", "total_R", "avg_R",
                    "profit_factor", "sharpe", "sharpe_adj", "max_dd_R", "calmar"]
    print(per_asset_df[display_cols].to_string(float_format="%.4f"))
    print()

    # Portfolio-level
    pf_df = build_portfolio_daily_r(
        all_daily_r,
        min_assets=args.min_assets,
    )
    pf_metrics = portfolio_metrics(
        pf_df,
        loss_cluster_threshold=args.cluster_threshold,
    )

    print(f"Portfolio (equal-weight, ≥{args.min_assets} assets)")
    print("-" * 72)
    for k, v in pf_metrics.items():
        print(f"  {k:25s} = {v}")
    print()

    # Save per-asset metrics
    output_path = args.output or str(WALKDIR / f"pnl_backtest_{tag}.csv")
    per_asset_df.to_csv(output_path)
    logger.info("Per-asset metrics -> %s", output_path)

    # Save portfolio equity curve
    eq_path = WALKDIR / f"portfolio_equity_{tag}.csv"
    pf_df.to_csv(eq_path)
    logger.info("Portfolio equity curve -> %s", eq_path)

    # ── Compare mode ────────────────────────────────────────────────────
    if args.ensemble_tag:
        print("\n" + "=" * 72)
        print(f"COMPARE: {args.tag} vs {args.ensemble_tag}")
        print("=" * 72)

        # Load ensemble signals
        ensemble_pattern = f"*_wf_signals_{args.ensemble_tag}.parquet"
        ensemble_parquets = sorted(WALKDIR.glob(ensemble_pattern))
        ensemble_map: dict[str, pd.Series] = {}
        for pq in ensemble_parquets:
            stem = pq.stem
            asset = stem.split("_wf_signals")[0]
            if asset not in pt_sl_map:
                continue
            tp, sl = pt_sl_map[asset]
            df = load_asset_signals(str(pq))
            if df.empty:
                continue
            daily_r = compute_asset_daily_r(df, tp, sl)
            ensemble_map[asset] = daily_r

        # Delta per asset
        deltas = []
        common_assets = sorted(set(per_asset_df.index) & set(ensemble_map.keys()))
        for asset in common_assets:
            d1 = all_daily_r[asset].sum()
            d2 = ensemble_map[asset].sum()
            deltas.append({
                "asset": asset,
                "base_total_R": round(float(d1), 2),
                "ensemble_total_R": round(float(d2), 2),
                "delta_R": round(float(d2 - d1), 2),
            })
        delta_df = pd.DataFrame(deltas).set_index("asset")
        delta_df["pct_change"] = (
            delta_df["delta_R"] / delta_df["base_total_R"].replace(0, 1) * 100
        )
        print(delta_df.to_string(float_format="%.4f"))

        # Portfolio-level comparison
        pf_ensemble = build_portfolio_daily_r(
            ensemble_map,
            min_assets=args.min_assets,
        )
        # Align dates
        common_dates = pf_df.index.intersection(pf_ensemble.index)
        r_base = pf_df.loc[common_dates, "portfolio_r"]
        r_ens = pf_ensemble.loc[common_dates, "portfolio_r"]
        delta_total = r_ens.sum() - r_base.sum()
        paired = pd.DataFrame({"base": r_base, "ensemble": r_ens})
        n_wins = (paired["ensemble"] > paired["base"]).sum()
        n_losses = (paired["ensemble"] < paired["base"]).sum()
        n_ties = len(paired) - n_wins - n_losses
        from scipy.stats import binomtest
        n_non_ties = n_wins + n_losses
        pooled_p = (
            binomtest(n_wins, n_non_ties, p=0.5, alternative="two-sided").pvalue
            if n_non_ties > 0
            else 1.0
        )

        print(f"\nPortfolio delta (ensemble - base): {delta_total:+.2f} R over {len(common_dates)} days")
        print(f"  Days ensemble wins: {n_wins}, loses: {n_losses}, ties: {n_ties}")
        print(f"  Sign test (pooled): p = {pooled_p:.4f}")

        comp_path = WALKDIR / f"pnl_comparison_{tag}_vs_{args.ensemble_tag}.csv"
        delta_df.to_csv(comp_path)
        logger.info("Comparison detail -> %s", comp_path)


# ── Self-test ──────────────────────────────────────────────────────────────


def _test_pnl():
    """Run unit tests on compute_trade_pnl."""
    cases = [
        # (signal, label, tp, sl, expected)
        (1, 1, 2.0, 2.0, 2.0),   # BUY, TP hit
        (1, 0, 2.0, 2.0, -2.0),  # BUY, SL hit
        (-1, 0, 2.0, 2.0, 2.0),  # SELL, lower(TP) hit
        (-1, 1, 2.0, 2.0, -2.0), # SELL, upper(SL) hit
        (0, 1, 2.0, 2.0, 0.0),   # FLAT
        (0, 0, 2.0, 2.0, 0.0),   # FLAT
        (1, 0, 1.5, 3.0, -3.0),  # BUY, EURUSD-like, SL hit
        (-1, 0, 1.5, 3.0, 1.5),  # SELL, EURUSD-like, TP hit (lower)
        (-1, 1, 1.5, 3.0, -3.0), # SELL, EURUSD-like, SL hit (upper)
        (1, 1, 1.0, 3.0, 1.0),   # BUY, GBPNZD-like, TP hit
        (-1, 0, 1.0, 3.0, 1.0),  # SELL, GBPNZD-like, TP hit
        (-1, 1, 1.0, 3.0, -3.0), # SELL, GBPNZD-like, SL hit
    ]
    failures = 0
    for signal, label, tp, sl, expected in cases:
        result = compute_trade_pnl(signal, label, tp, sl)
        ok = abs(result - expected) < 1e-9
        status = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
            print(
                f"  {status}: signal={signal:+d} label={label} "
                f"tp={tp} sl={sl} → {result:.1f} (expected {expected:.1f})"
            )
    if failures == 0:
        print(f"All {len(cases)} PnL tests passed.")
    else:
        print(f"{failures}/{len(cases)} PnL tests FAILED.")
    return failures


if __name__ == "__main__":
    # Always run self-test first
    errs = _test_pnl()
    if errs:
        sys.exit(1)
    main()
