#!/usr/bin/env python3
"""Phase 2 — Capital Scaling Analysis.

Models multiple capital scenarios using the baseline daily R-series
and the production position sizing chain. Evaluates net profit, % return,
absolute return, drawdown, margin utilization, exposure, and capital
efficiency across each scenario.

Key question: Does return scale linearly with additional capital?
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
logger = logging.getLogger("eigencapital.capital_study.phase2")

OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Production config constants
BASE_CAPITAL = 100_000
MAX_POSITION_PCT = 0.15
MAX_RISK_PER_TRADE_PCT = 0.02
MAX_CONCURRENT = 8
MAX_LEVERAGE = 2.0
FACTOR_LIMITS = {
    "CHF": 0.20, "AUD": 0.25, "NZD": 0.25, "JPY": 0.25,
    "GOLD": 0.15, "FX_MAJOR": 0.40, "FX_CROSS": 0.40,
}

CAPITAL_SCENARIOS = [
    ("baseline", 100_000),
    ("plus_25pct", 125_000),
    ("plus_50pct", 150_000),
    ("plus_100pct", 200_000),
    ("plus_200pct", 300_000),
    ("plus_500pct", 600_000),
    ("plus_1000pct", 1_000_000),
]


def compute_atr_pct_from_cache(asset: str) -> float:
    """Read mean ATR_pct from cached OHLCV data for scaling."""
    import glob
    cache_dir = ROOT / "data" / "live" / "cache"
    patterns = [
        cache_dir / f"{asset}.parquet",
        cache_dir / f"{asset}_X.parquet",
        cache_dir / f"{asset}_F.parquet",
        cache_dir / f"{asset.replace('BTCUSD', 'BTC_USD')}.parquet",
    ]
    for p in patterns:
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if hasattr(df.columns, "levels"):
                    df.columns = df.columns.get_level_values(0)
                col_map = {c.lower(): c for c in df.columns}
                high = df[col_map["high"]]
                low = df[col_map["low"]]
                close = df[col_map["close"]]
                tr = pd.concat([
                    (high - low).abs(),
                    (high - close.shift()).abs(),
                    (low - close.shift()).abs(),
                ], axis=1).max(axis=1)
                atr = tr.rolling(14).mean()
                atr_pct = (atr / close).mean()
                return float(atr_pct) if not np.isnan(atr_pct) else 0.005
            except Exception:
                return 0.005
    return 0.005  # default fallback ~0.5%


def compute_R_to_pct_conversion(
    assets: list[str],
    capital: float,
) -> dict[str, float]:
    """Compute the R-to-% conversion factor per asset.

    Each trade of 1R produces a % return on capital:
        return_pct = (1R) * (atr_pct) * (allocation_pct)
    where allocation_pct = max_position_pct / n_assets_active
    """
    n_active = max(len(assets), 1)
    alloc = min(MAX_POSITION_PCT, 1.0 / n_active)
    conv: dict[str, float] = {}
    for a in assets:
        atr_p = compute_atr_pct_from_cache(a)
        conv[a] = atr_p * alloc
    return conv


def load_daily_r() -> tuple[pd.DataFrame, dict[str, tuple[float, float]], list[str]]:
    """Load baseline daily R-series for all assets."""
    from scripts.backtest.backtest_pnl import compute_asset_daily_r, _asset_pt_sl_from_config

    pt_sl_map = _asset_pt_sl_from_config()
    WALKDIR = ROOT / "scripts" / "walkforward"
    parquets = sorted(WALKDIR.glob("*_wf_signals.parquet"))
    SELL_ONLY = {"CADCHF", "NZDCHF", "EURAUD"}

    all_r: dict[str, pd.Series] = {}
    for pq in parquets:
        name = pq.stem.split("_wf_signals")[0]
        if name not in pt_sl_map:
            continue
        tp, sl = pt_sl_map[name]
        df = pd.read_parquet(pq)
        if name in SELL_ONLY:
            df.loc[df["signal"] == 1, "signal"] = 0
        r = compute_asset_daily_r(df, tp, sl)
        all_r[name] = r

    combined = pd.DataFrame(all_r)
    return combined, pt_sl_map, list(all_r.keys())


def evaluate_scenario(
    daily_r: pd.DataFrame,
    assets: list[str],
    capital: float,
    label: str,
) -> dict:
    """Evaluate performance at a given capital level.

    Scenarios differ only in the capital base. Position sizing
    guardrails are constant proportions of capital.

    Returns %-space metrics converted from R-space:
        daily_return_pct = (daily_R * conv_factor) where
        conv_factor = atr_pct * allocation_pct
        allocation_pct = MAX_POSITION_PCT (15%) / n_assets at most
    """
    n_active = len([a for a in assets if a in daily_r.columns])
    conv = compute_R_to_pct_conversion(assets, capital)

    # Convert each asset's daily R to % return
    asset_pct = {}
    for a in assets:
        if a not in daily_r.columns:
            continue
        r_col = daily_r[a]
        c = conv.get(a, 0.005)
        # Cap loss at -max_risk_per_trade_pct per day per asset
        pct = r_col * c
        asset_pct[a] = pct.clip(lower=-MAX_RISK_PER_TRADE_PCT)

    # Portfolio daily % return (equal weighted among active)
    pf_pct = pd.DataFrame(asset_pct).mean(axis=1)
    # Filter days with insufficient assets
    n_active_daily = daily_r[assets].notna().sum(axis=1)
    pf_pct = pf_pct[n_active_daily >= min(12, n_active)]

    # Compute metrics in %-space
    n_days = len(pf_pct)
    if n_days == 0:
        return {"scenario": label, "capital": capital, "error": "no data"}

    vals = pf_pct.values
    n_years = n_days / 252
    cum_growth = np.cumprod(1.0 + vals)
    peak = np.maximum.accumulate(cum_growth)
    dd_pct = (cum_growth - peak) / peak
    total_return_pct = float(cum_growth[-1] - 1.0)
    max_dd_pct = float(dd_pct.min())

    annualized_return = float(cum_growth[-1] ** (1.0 / n_years) - 1.0) if n_years > 0 else 0.0
    mean_daily = float(vals.mean())
    std_daily = float(vals.std())
    sharpe = mean_daily / std_daily * np.sqrt(252) if std_daily > 0 else 0.0

    rho = float(pd.Series(vals).autocorr()) if len(vals) > 1 else 0.0
    sharpe_adj = sharpe * np.sqrt((1.0 - rho) / (1.0 + rho)) if abs(rho) < 1.0 else sharpe

    # Sortino
    downside = vals[vals < 0]
    downside_std = float(downside.std()) if len(downside) > 0 else 0.0
    sortino = mean_daily / downside_std * np.sqrt(252) if downside_std > 0 else 0.0

    # Calmar
    calmar = annualized_return / abs(max_dd_pct) if max_dd_pct < 0 else float("inf")

    # VaR and CVaR
    sorted_vals = np.sort(vals)
    var_95 = float(sorted_vals[int(len(sorted_vals) * 0.05)])
    cvar_95 = float(sorted_vals[:int(len(sorted_vals) * 0.05)].mean()) if int(len(sorted_vals) * 0.05) > 0 else var_95

    # Notional and constraint info
    gross_notional = capital * min(MAX_LEVERAGE, 1.0 / max(1 - abs(max_dd_pct), 0.5))
    notional_used = capital * min(MAX_CONCURRENT * MAX_POSITION_PCT, MAX_LEVERAGE)
    margin_util = notional_used / capital if capital > 0 else 0.0

    # Net profit in $
    net_profit = capital * total_return_pct

    return {
        "scenario": label,
        "capital": capital,
        "net_profit": round(net_profit, 2),
        "total_return_pct": round(total_return_pct * 100, 4),
        "annualized_return_pct": round(annualized_return * 100, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_adj_lo": round(sharpe_adj, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_dd_pct": round(max_dd_pct * 100, 4),
        "var_95": round(var_95 * 100, 4),
        "cvar_95": round(cvar_95 * 100, 4),
        "gross_notional": round(gross_notional, 2),
        "notional_used": round(notional_used, 2),
        "margin_utilization": round(margin_util, 4),
        "n_days": n_days,
        "risk_adjusted_return": round(annualized_return / abs(max_dd_pct), 4) if max_dd_pct != 0 else 0.0,
    }


def main():
    daily_r, pt_sl, assets = load_daily_r()
    logger.info("Loaded %d assets, %d days", len(assets), len(daily_r))

    results = []
    for label, capital in CAPITAL_SCENARIOS:
        r = evaluate_scenario(daily_r, assets, capital, label)
        results.append(r)
        logger.info(
            "  %s ($%d): AR=%+.2f%% Sharpe=%.2f DD=%+.2f%%",
            label, capital,
            r["annualized_return_pct"],
            r["sharpe"],
            r["max_dd_pct"],
        )

    # Determine scaling linearity
    capitals = np.array([r["capital"] for r in results])
    returns = np.array([r["net_profit"] for r in results])
    slope, intercept = np.polyfit(capitals, returns, 1)
    r_squared = 1.0 - np.sum((returns - (slope * capitals + intercept)) ** 2) / np.sum((returns - returns.mean()) ** 2)

    # Return per unit of capital (capital efficiency)
    capital_efficiency = [r["net_profit"] / r["capital"] for r in results]

    output = {
        "scenarios": results,
        "scaling_analysis": {
            "linearity_slope": round(float(slope), 6),
            "linearity_intercept": round(float(intercept), 2),
            "r_squared": round(float(r_squared), 4),
            "interpretation": (
                "linear" if r_squared > 0.99 else
                "sub_linear" if r_squared < 0.90 else
                "near_linear"
            ),
            "capital_efficiency": [
                {"scenario": r["scenario"], "return_per_capital": round(r["net_profit"] / max(r["capital"], 1), 6)}
                for r in results
            ],
        },
        "constraints": {
            "max_position_pct": MAX_POSITION_PCT,
            "max_leverage": MAX_LEVERAGE,
            "max_concurrent": MAX_CONCURRENT,
            "implied_max_notional_at_baseline": round(BASE_CAPITAL * MAX_LEVERAGE, 2),
            "implied_max_notional_at_1m": round(1_000_000 * MAX_LEVERAGE, 2),
        },
        "_methodology": (
            "Daily R-multiples converted to % returns using per-asset ATR_pct × allocation_pct. "
            "Position sizing guardrails applied: 15% max position, 2% max risk per trade, "
            "2.0x max leverage, 8 max concurrent positions. "
            "Returns compound geometrically. Drawdown in % of peak capital."
        ),
    }

    path = OUTPUT_DIR / "phase2_scaling.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Scaling results → %s", path)

    print("\n" + "=" * 72)
    print("PHASE 2 — CAPITAL SCALING ANALYSIS")
    print("=" * 72)
    print(f"{'Scenario':<20s} {'Capital':>10s} {'Net Profit':>12s} {'Ann Return':>10s} {'Sharpe':>8s} {'Max DD':>8s} {'Capital Eff':>10s}")
    print("-" * 72)
    for r in results:
        ce = r["net_profit"] / r["capital"] if r["capital"] > 0 else 0.0
        print(f"{r['scenario']:<20s} ${r['capital']:>8,d} ${r['net_profit']:>+9,.0f} {r['annualized_return_pct']:>+8.2f}% {r['sharpe']:>7.2f} {r['max_dd_pct']:>7.2f}% {ce:>8.4f}")
    print("-" * 72)
    sa = output["scaling_analysis"]
    print(f"  Linearity slope:    {sa['linearity_slope']:.6f}")
    print(f"  R²:                 {sa['r_squared']:.4f}")
    print(f"  Interpretation:     {sa['interpretation']}")
    print("=" * 72)


if __name__ == "__main__":
    main()
