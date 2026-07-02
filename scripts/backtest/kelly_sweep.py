#!/usr/bin/env python3
"""
Kelly fraction sweep — validate [0.1, 0.25, 0.5, 1.0] fractions against
portfolio total_R and max_dd using walk-forward signal parquets.

Each trade's R-multiple is scaled by the Kelly multiplier computed from
p_long (calibrated probability) and the asset's TP/SL config.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/backtest/kelly_sweep.py

Output:
    Prints a comparison table for all sweep fractions.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from shared.kelly import compute_kelly_multiplier

logger = logging.getLogger("kelly_sweep")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"


def _asset_pt_sl_from_config() -> dict[str, tuple[float, float]]:
    """Load per-asset pt_sl from the production config."""
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def _load_signal_parquet(parquet_path: str) -> pd.DataFrame | None:
    """Load a single asset's OOS signal parquet."""
    df = pd.read_parquet(parquet_path)
    if df.empty:
        return None
    return df.sort_index()


def compute_kelly_scaled_daily_r(
    df: pd.DataFrame,
    tp: float,
    sl: float,
    fraction: float,
    max_cap: float = 1.0,
    min_edge: float = 0.0,
) -> pd.Series:
    """Compute daily R-multiple series with Kelly scaling.

    Each non-flat signal's R-multiple is multiplied by the Kelly multiplier
    computed from p_long and the asset's TP/SL config.
    """
    r = np.zeros(len(df), dtype=float)
    signals = df["signal"].values
    labels = df["label"].values
    p_long = df["p_long"].values.astype(float) if "p_long" in df.columns else np.full(len(df), 0.5)

    n_skipped = 0

    for i in range(len(df)):
        signal = int(signals[i])
        if signal == 0:
            continue

        # Determine probability for Kelly computation:
        # BUY: use p_long directly
        # SELL: winning probability = 1 - p_long (SELL wins when label=0)
        prob = float(p_long[i]) if signal == 1 else 1.0 - float(p_long[i])

        kelly_mult = compute_kelly_multiplier(
            prob_long=prob,
            tp_mult=tp,
            sl_mult=sl,
            fraction=fraction,
            max_cap=max_cap,
            min_edge=min_edge,
        )

        if kelly_mult <= 0:
            n_skipped += 1
            continue

        label = int(labels[i])
        if signal == 1:  # BUY  # noqa: SIM108
            base_r = tp if label == 1 else -sl
        else:  # SELL
            base_r = tp if label == 0 else -sl

        r[i] = base_r * kelly_mult

    if n_skipped > 0:
        pass  # logged at caller level if needed

    return pd.Series(r, index=df.index, name="daily_r")


def portfolio_metrics_from_r(r: pd.Series) -> dict:
    """Compute portfolio-level metrics from a daily R series."""
    n_days = len(r)
    if n_days == 0:
        return {"n_days": 0, "total_R": 0.0, "avg_R": 0.0, "sharpe": 0.0, "sharpe_adj": 0.0, "max_dd_R": 0.0}

    total_R = float(r.sum())
    avg_R = float(r.mean())
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0

    cum = r.cumsum()
    running_max = cum.expanding().max()
    dd_r = cum - running_max
    max_dd_r = float(dd_r.min())

    rho = r.autocorr() if len(r) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    return {
        "n_days": n_days,
        "total_R": round(total_R, 2),
        "avg_R": round(avg_R, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj": round(sharpe_adj, 4),
        "max_dd_R": round(max_dd_r, 2),
    }


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    SWEEP_FRACTIONS = [0.1, 0.25, 0.5, 1.0]
    WEIGHT_METHOD = "factor_constrained_v2"

    pt_sl_map = _asset_pt_sl_from_config()
    logger.info("Loaded pt_sl for %d assets", len(pt_sl_map))

    # Discover signal parquets
    parquets = sorted(WALKDIR.glob("*_wf_signals.parquet"))
    if not parquets:
        logger.error("No signal parquets found in %s", WALKDIR)
        sys.exit(1)
    logger.info("Found %d signal parquets", len(parquets))

    # Load all asset data once
    from scripts.backtest.backtest_pnl import _asset_pt_sl_from_config as _  # noqa: F811

    all_asset_data: dict[str, dict] = {}
    asset_ic: dict[str, float] = {}
    SELL_ONLY_ASSETS = frozenset({"CADCHF", "NZDCHF", "EURAUD"})

    for pq in parquets:
        stem = pq.stem
        asset = stem.split("_wf_signals")[0]
        if asset not in pt_sl_map:
            logger.debug("Skipping %s (no config)", asset)
            continue

        tp, sl = pt_sl_map[asset]
        df = _load_signal_parquet(str(pq))
        if df is None:
            continue

        # Apply SELL-only filter (same as backtest_pnl.py)
        if asset in SELL_ONLY_ASSETS:
            df.loc[df["signal"] == 1, "signal"] = 0

        # Compute IC for conviction weighting
        if "p_long" in df.columns and "label" in df.columns and len(df) >= 20:
            from scipy.stats import spearmanr

            ic_val, _ = spearmanr(df["p_long"].astype(float), df["label"].astype(float))
            asset_ic[asset] = float(ic_val) if not np.isnan(ic_val) else 0.0
        else:
            asset_ic[asset] = 0.0

        all_asset_data[asset] = {"df": df, "tp": tp, "sl": sl}

    if not all_asset_data:
        logger.error("No assets loaded")
        sys.exit(1)

    print("=" * 72)
    print("KELLY FRACTION SWEEP")
    print("=" * 72)
    print(f"\n  Weight method: {WEIGHT_METHOD}")
    print(f"  Assets: {len(all_asset_data)}")
    print(f"  Fractions: {SWEEP_FRACTIONS}")
    print()

    results: list[dict] = []
    from scripts.backtest.backtest_pnl import build_portfolio_daily_r, portfolio_metrics

    for fraction in SWEEP_FRACTIONS:
        all_daily_r: dict[str, pd.Series] = {}
        for asset, data in all_asset_data.items():
            daily_r = compute_kelly_scaled_daily_r(data["df"], data["tp"], data["sl"], fraction=fraction)
            all_daily_r[asset] = daily_r

        conviction = asset_ic if WEIGHT_METHOD.startswith("conviction") else None
        pf_df = build_portfolio_daily_r(
            all_daily_r,
            min_assets=15,
            weight_method=WEIGHT_METHOD,
            conviction=conviction,
        )
        pf_metrics = portfolio_metrics(pf_df)

        results.append(
            {
                "fraction": fraction,
                "total_R": pf_metrics["total_R"],
                "sharpe_adj": pf_metrics["sharpe_adj"],
                "max_dd_R": pf_metrics["max_dd_R"],
                "n_days": pf_metrics["n_days"],
                "calmar": pf_metrics["calmar"],
            }
        )

    # Also run a "no kelly" baseline (kelly multiplier = 1.0 for all trades)
    all_daily_r_base: dict[str, pd.Series] = {}
    for asset, data in all_asset_data.items():
        from scripts.backtest.backtest_pnl import compute_asset_daily_r

        daily_r = compute_asset_daily_r(data["df"], data["tp"], data["sl"])
        all_daily_r_base[asset] = daily_r

    conviction = asset_ic if WEIGHT_METHOD.startswith("conviction") else None
    pf_df_base = build_portfolio_daily_r(
        all_daily_r_base, min_assets=15, weight_method=WEIGHT_METHOD, conviction=conviction
    )
    pf_metrics_base = portfolio_metrics(pf_df_base)

    # Print comparison table
    print(f"{'Fraction':<12} {'total_R':<12} {'sharpe_adj':<12} {'max_dd_R':<12} {'Calmar':<12} {'n_days':<8}")
    print("-" * 60)
    print(
        f"{'none':<12} {pf_metrics_base['total_R']:<12.2f} {pf_metrics_base['sharpe_adj']:<12.4f} "
        f"{pf_metrics_base['max_dd_R']:<12.2f} {pf_metrics_base['calmar']:<12.2f} "
        f"{pf_metrics_base['n_days']:<8}"
    )
    for r in results:
        delta_r = r["total_R"] - pf_metrics_base["total_R"]
        delta_dd = r["max_dd_R"] - pf_metrics_base["max_dd_R"]
        print(
            f"{r['fraction']:<12} {r['total_R']:<12.2f} {r['sharpe_adj']:<12.4f} "
            f"{r['max_dd_R']:<12.2f} {r['calmar']:<12.2f} "
            f"{r['n_days']:<8}"
        )
        print(f"{'':>12} {'ΔR=' + f'{delta_r:+.2f}':<12} {'':12} {'ΔDD=' + f'{delta_dd:+.2f}':<12}")
    print()

    # Recommend best fraction
    best = max(results, key=lambda r: r["total_R"])
    best_low_dd = min(results, key=lambda r: r["max_dd_R"])
    print(f"Best by total_R: fraction={best['fraction']} (total_R={best['total_R']}, max_dd_R={best['max_dd_R']})")
    print(
        f"Best by max_dd: fraction={best_low_dd['fraction']} (total_R={best_low_dd['total_R']}, max_dd_R={best_low_dd['max_dd_R']})"  # noqa: E501
    )  # noqa: E501
    print()


if __name__ == "__main__":
    main()
