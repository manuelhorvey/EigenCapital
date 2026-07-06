#!/usr/bin/env python3
"""Phase 5 — Market Regime Analysis.

Evaluates performance across different market environments:
strong trends, range-bound, high/low volatility, bullish/bearish,
risk-on/risk-off, and market sessions.

Determines whether 8%+ returns are regime-conditional or regime-independent.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eigencapital.capital_study.phase5")

OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def classify_regime_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Classify each day into market regimes.

    Uses available features from the signal parquets' index dates
    combined with macro proxies (VIX, DXY, close returns).
    """
    # Trend detection using close returns
    df = df.copy()
    df["ret_5d"] = df["close"].pct_change(5)
    df["ret_21d"] = df["close"].pct_change(21)
    df["vol_21d"] = df["ret_5d"].rolling(21).std()

    # Trend strength
    df["trend_regime"] = "RANGE"
    df.loc[df["ret_21d"].abs() > 0.03, "trend_regime"] = "TRENDING"
    df.loc[df["ret_21d"].abs() > 0.07, "trend_regime"] = "STRONG_TREND"

    # Volatility regime
    median_vol = df["vol_21d"].median()
    df["vol_regime"] = "NORMAL_VOL"
    df.loc[df["vol_21d"] > median_vol * 1.5, "vol_regime"] = "HIGH_VOL"
    df.loc[df["vol_21d"] < median_vol * 0.5, "vol_regime"] = "LOW_VOL"

    # Directional regime
    df["dir_regime"] = "NEUTRAL"
    df.loc[df["ret_21d"] > 0.02, "dir_regime"] = "BULLISH"
    df.loc[df["ret_21d"] < -0.02, "dir_regime"] = "BEARISH"

    return df


def main():
    # Load portfolio daily R series
    from scripts.capital_study.phase2_scaling import load_daily_r, compute_R_to_pct_conversion

    daily_r, pt_sl, assets = load_daily_r()
    logger.info("Loaded %d assets, %d days for regime analysis", len(assets), len(daily_r))

    # Load ^DJI close as proxy for US equity regime
    dji_path = ROOT / "data" / "live" / "cache" / "^DJI.parquet"
    if dji_path.exists():
        dji = pd.read_parquet(dji_path)
        dji_close = dji["Close"]["^DJI"].to_frame("close")
        dji_close.index = dji_close.index.tz_localize("UTC")  # match pf_r tz
        df = classify_regime_daily(dji_close)
        logger.info("Loaded ^DJI for regime classification (%d days)", len(df))
    else:
        logger.warning("No ^DJI data — using synthetic regime classification")
        idx = daily_r.index
        df = pd.DataFrame({"close": np.cumsum(np.random.randn(len(idx)) * 0.01 + 0.0003)}, index=idx)
        df = classify_regime_daily(df)

    # Convert to %-space for CAGR and regime analysis
    conv = compute_R_to_pct_conversion(assets, 100_000)
    asset_pct = {}
    for a in assets:
        if a not in daily_r.columns:
            continue
        c = conv.get(a, 0.005)
        asset_pct[a] = (daily_r[a] * c).clip(lower=-0.02)
    pf_pct = pd.DataFrame(asset_pct).mean(axis=1)
    n_active = daily_r[assets].notna().sum(axis=1)
    pf_pct = pf_pct[n_active >= 12]

    # Align portfolio %-returns with regime dates
    regime_performance: dict[str, dict] = {}
    regime_cols = ["trend_regime", "vol_regime", "dir_regime"]

    for col in regime_cols:
        regime_performance[col] = {}
        for regime, group in df.groupby(col):
            overlap = pf_pct.index.intersection(group.index)
            if len(overlap) < 5:
                continue
            regime_pct = pf_pct.loc[overlap]
            n_days = len(regime_pct)

            # %-space metrics
            total_ret_pct = float(np.cumprod(1.0 + regime_pct.values)[-1] - 1.0)
            mean_pct = float(regime_pct.mean())
            std_pct = float(regime_pct.std())
            sharpe = mean_pct / std_pct * np.sqrt(252) if std_pct > 0 else 0.0
            win_days = int((regime_pct > 0).sum())
            wr = win_days / n_days if n_days > 0 else 0.0
            cum = np.cumprod(1.0 + regime_pct.values)
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak) / peak
            max_dd_pct = float(dd.min())

            # %-space CAGR
            n_years = n_days / 252
            cagr = cum[-1] ** (1.0 / n_years) - 1.0 if n_years > 0 else 0.0

            # Bootstrap p(return > 0.08 annualized)
            rng = np.random.default_rng(42)
            vals = regime_pct.values
            n_bootstrap = 500
            boot_8pct = 0
            for _ in range(n_bootstrap):
                idx_b = rng.integers(0, len(vals), len(vals))
                b = vals[idx_b]
                b_cagr = np.cumprod(1.0 + b)[-1] ** (1.0 / n_years) - 1.0 if n_years > 0 else 0.0
                if b_cagr > 0.08:
                    boot_8pct += 1

            regime_performance[col][str(regime)] = {
                "n_days": n_days,
                "total_return_pct": round(total_ret_pct * 100, 4),
                "cagr_pct": round(cagr * 100, 4),
                "mean_daily_pct": round(mean_pct * 100, 6),
                "sharpe": round(sharpe, 4),
                "win_day_rate": round(wr, 4),
                "max_dd_pct": round(max_dd_pct * 100, 4),
                "p_annual_return_gt_8pct": round(boot_8pct / n_bootstrap, 4),
                "days_share": round(n_days / max(len(pf_pct), 1), 4),
            }
            logger.info(
                "  %s[%s]: %d days CAGR=%.2f%% Sharpe=%.2f p>8%%=%.0f%%",
                col, regime, n_days, cagr * 100, sharpe,
                boot_8pct / n_bootstrap * 100,
            )

    # Regime independence score (std of CAGR across regime buckets)
    regime_scores = regime_performance.get("trend_regime", {})
    regime_cagrs = [r["cagr_pct"] for r in regime_scores.values()]
    independence_score = float(np.std(regime_cagrs)) if regime_cagrs else 0.0

    output = {
        "regime_performance": regime_performance,
        "regime_independence": {
            "score": round(independence_score, 6),
            "interpretation": (
                "highly_regime_dependent" if independence_score > 0.1 else
                "moderately_regime_dependent" if independence_score > 0.05 else
                "regime_independent"
            ),
        },
        "daily_classification_count": len(df),
        "_methodology": (
            "Regimes classified using ^DJI daily returns. Trend = abs(21d return). "
            "Vol = 21d rolling std of 5d returns. Direction = sign of 21d return. "
            "Mesures computed in %-space (R × ATR_pct × allocation_pct). "
            "P(return > 8%) from 500 bootstrap iterations per regime bucket."
        ),
    }

    path = OUTPUT_DIR / "phase5_regime.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Regime analysis → %s", path)

    print("\n" + "=" * 72)
    print("PHASE 5 — MARKET REGIME ANALYSIS")
    print("=" * 72)
    for col, regimes in regime_performance.items():
        print(f"\n  {col}:")
        print(f"  {'Regime':<20s} {'Days':>6s} {'CAGR':>8s} {'Sharpe':>8s} {'WinRt':>7s} {'MaxDD':>7s} {'P>8%':>7s}")
        print(f"  {'-'*63}")
        for reg, m in sorted(regimes.items()):
            print(f"  {str(reg):<20s} {m['n_days']:>6d} {m['cagr_pct']:>+7.2f}% {m['sharpe']:>7.2f} "
                  f"{m['win_day_rate']:>6.1%} {m['max_dd_pct']:>6.2f}% {m['p_annual_return_gt_8pct']:>6.0%}")
    ri = output["regime_independence"]
    print(f"\n  Regime independence score: {ri['score']:.6f} ({ri['interpretation']})")
    print("=" * 72)


if __name__ == "__main__":
    main()
