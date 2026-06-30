"""Per-asset TP/SL quality check — EV, breakeven WR, MFE/MAE capture classification.

Classifies each asset's current (tp_mult, sl_mult) configuration as:

- OPTIMAL — positive expectancy, good barrier geometry
- TP_TOO_TIGHT — MFE consistently exceeds TP distance
- SL_TOO_WIDE — SL distance far exceeds MAE (unnecessary risk)
- UNBALANCED — large directional asymmetry between BUY and SELL
- INVALID — negative or zero EV, breakeven WR exceeds actual WR
- INSUFFICIENT_DATA — fewer than 5 trades available
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import numpy as np
import pandas as pd

from scripts.optimization.trade_outcome_repository import TradeOutcomeRepository

logger = logging.getLogger("quorrin.optimization.per_asset_quality")

TP_TIGHT_THRESHOLD = 0.80
SL_WIDE_THRESHOLD = 0.50
ASYMMETRY_THRESHOLD = 0.30
MIN_TRADES = 5


def _classify(row: dict[str, Any]) -> str:
    """Classify a single asset's TP/SL configuration based on computed metrics."""
    n = row.get("n_trades", 0)
    if n < MIN_TRADES:
        return "INSUFFICIENT_DATA"

    ev = row.get("ev", 0.0)
    pf = row.get("profit_factor", 0.0)
    if ev <= 0 or pf <= 1.0:
        return "INVALID"

    buy_wr = row.get("buy_wr", 0.0)
    sell_wr = row.get("sell_wr", 0.0)
    asymmetry = abs(buy_wr - sell_wr)
    if asymmetry > ASYMMETRY_THRESHOLD:
        return "UNBALANCED"

    mfe_capture = row.get("mfe_capture_ratio", 0.0)
    mae_tolerance = row.get("mae_tolerance_ratio", 0.0)

    flags = []
    if mfe_capture > TP_TIGHT_THRESHOLD:
        flags.append("TP_TOO_TIGHT")
    if mae_tolerance < SL_WIDE_THRESHOLD:
        flags.append("SL_TOO_WIDE")

    if len(flags) == 1:
        return flags[0]
    if len(flags) == 2:
        return "UNBALANCED"

    return "OPTIMAL"


def compute_quality(outcomes: pd.DataFrame, directional: pd.DataFrame) -> list[dict[str, Any]]:
    """Compute per-asset quality metrics from outcome data.

    Parameters
    ----------
    outcomes : pd.DataFrame
        Flat outcome table from TradeOutcomeRepository.get_outcomes().
    directional : pd.DataFrame
        Directional summary from TradeOutcomeRepository.get_directional_outcomes().

    Returns
    -------
    list of dicts with quality metrics per asset.
    """
    dir_map = {}
    if not directional.empty:
        for _, r in directional.iterrows():
            dir_map[r["asset"]] = r

    results: list[dict[str, Any]] = []
    for asset, grp in outcomes.groupby("asset"):
        n = len(grp)
        wins = (grp["realized_r"] > 0).sum()
        losses = n - wins
        wr = wins / n if n > 0 else 0.0
        avg_r = grp["realized_r"].mean()
        total_r = grp["realized_r"].sum()

        tp_mult = float(grp["tp_mult"].iloc[0])
        sl_mult = float(grp["sl_mult"].iloc[0])
        be_wr = sl_mult / (tp_mult + sl_mult) if (tp_mult + sl_mult) > 0 else 1.0

        ev = wr * tp_mult - (1 - wr) * sl_mult
        pf = (wins * tp_mult) / (losses * sl_mult + 1e-10) if losses > 0 else float("inf")

        avg_mae = grp["mae"].mean()
        avg_mfe = grp["mfe"].mean()
        entry_price = grp["entry_price"].abs().mean()

        tp_distance = tp_mult * sl_mult * entry_price if entry_price > 0 else 1.0
        sl_distance = sl_mult * entry_price if entry_price > 0 else 1.0

        mfe_capture_ratio = avg_mfe / (tp_distance + 1e-10)
        mae_tolerance_ratio = avg_mae / (sl_distance + 1e-10)

        buy_wr = float(dir_map.get(asset, {}).get("buy_wr", 0.0))
        sell_wr = float(dir_map.get(asset, {}).get("sell_wr", 0.0))
        directional_asymmetry = abs(buy_wr - sell_wr)

        row = {
            "asset": asset,
            "n_trades": n,
            "win_rate": round(wr, 4),
            "avg_r": round(avg_r, 4),
            "total_r": round(total_r, 4),
            "tp_mult": tp_mult,
            "sl_mult": sl_mult,
            "breakeven_wr": round(be_wr, 4),
            "ev": round(ev, 4),
            "profit_factor": round(pf, 4) if pf != float("inf") else None,
            "buy_wr": round(buy_wr, 4),
            "sell_wr": round(sell_wr, 4),
            "directional_asymmetry": round(directional_asymmetry, 4),
            "mfe_capture_ratio": round(mfe_capture_ratio, 4),
            "mae_tolerance_ratio": round(mae_tolerance_ratio, 4),
        }
        row["classification"] = _classify(row)
        results.append(row)

    return sorted(results, key=lambda x: x["classification"])


def print_report(results: list[dict[str, Any]]) -> None:
    """Print a human-readable quality report."""
    print("=" * 90)
    print("  PER-ASSET TP/SL QUALITY REPORT")
    print("=" * 90)

    classifications = {}
    for r in results:
        classifications.setdefault(r["classification"], []).append(r)

    for cls in ["OPTIMAL", "TP_TOO_TIGHT", "SL_TOO_WIDE", "UNBALANCED", "INVALID", "INSUFFICIENT_DATA"]:
        assets = classifications.get(cls, [])
        if not assets:
            continue
        print(f"\n{'─' * 90}")
        print(f"  {cls} ({len(assets)} assets)")
        print(f"{'─' * 90}")
        header = (
            f"  {'Asset':12s} {'Trades':>6s} {'WR':>6s} {'AvgR':>7s} {'EV':>7s} "
            f"{'PF':>5s} {'BEWR':>6s} {'BuyWR':>6s} {'SellWR':>7s} "
            f"{'MFEcap':>7s} {'MAEtol':>7s}"
        )
        print(header)
        print(f"  {'-' * 88}")
        for r in assets:
            pf_str = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else "  ∞"
            print(
                f"  {r['asset']:12s} {r['n_trades']:>6d} {r['win_rate']:>6.1%} "
                f"{r['avg_r']:>+7.3f} {r['ev']:>+7.3f} {pf_str:>5s} "
                f"{r['breakeven_wr']:>6.1%} {r['buy_wr']:>6.1%} {r['sell_wr']:>7.1%} "
                f"{r['mfe_capture_ratio']:>7.2f} {r['mae_tolerance_ratio']:>7.2f}"
            )

    print(f"\n{'=' * 90}")
    summary = {k: len(v) for k, v in classifications.items()}
    print(f"  SUMMARY: {sum(summary.values())} assets — {summary}")
    print(f"{'=' * 90}")
    print()


def print_detail(results: list[dict[str, Any]]) -> None:
    """Print a detailed, machine-readable table for all assets."""
    header = (
        f"{'Asset':12s} {'Cls':14s} {'N':>3s} {'WR':>5s} {'AvgR':>7s} {'EV':>7s} {'PF':>5s} "
        f"{'BE':>5s} {'Buy':>5s} {'Sell':>5s} {'Asym':>5s} {'MFEcap':>6s} {'MAEtol':>6s}"
    )
    print(f"\n{header}")
    print(f"{'-' * len(header)}")
    for r in results:
        pf_str = f"{r['profit_factor']:>5.2f}" if r["profit_factor"] is not None else "    ∞"
        mfe_str = f"{r['mfe_capture_ratio']:>6.2f}" if np.isfinite(r.get("mfe_capture_ratio", 0) or 0) else "   nan"
        mae_str = f"{r['mae_tolerance_ratio']:>6.2f}" if np.isfinite(r.get("mae_tolerance_ratio", 0) or 0) else "   nan"
        cls_short = r["classification"][:14]
        print(
            f"{r['asset']:12s} {cls_short:14s} {r['n_trades']:>3d} "
            f"{r['win_rate']:>5.1%} {r['avg_r']:>+7.3f} {r['ev']:>+7.3f} "
            f"{pf_str} "
            f"{r['breakeven_wr']:>5.1%} {r['buy_wr']:>5.1%} {r['sell_wr']:>5.1%} "
            f"{r['directional_asymmetry']:>5.2f} {mfe_str} {mae_str}"
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    repo = TradeOutcomeRepository()
    outcomes = repo.get_outcomes()
    if outcomes.empty:
        print("No trade outcomes found in database.")
        sys.exit(1)

    directional = repo.get_directional_outcomes()
    results = compute_quality(outcomes, directional)
    print_report(results)
    print_detail(results)


if __name__ == "__main__":
    main()
