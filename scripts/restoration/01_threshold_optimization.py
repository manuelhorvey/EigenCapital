#!/usr/bin/env python3
"""Threshold optimization — scan optimal BUY/SELL thresholds from walk-forward signal parquets.

For each SELL_ONLY asset, scans threshold space [0.01, 0.99] and computes:
  - BUY WR, BUY total R
  - SELL WR, SELL total R
  - Net total R
  - Optimal threshold that maximizes total R

This is the cheapest experiment — uses existing signal parquets (no retraining).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/restoration/01_threshold_optimization.py
    PYTHONPATH=$PYTHONPATH:. python scripts/restoration/01_threshold_optimization.py --assets CADCHF,ES
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("threshold_opt")

WALKDIR = Path(__file__).resolve().parent.parent.parent / "walkforward"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF",
        "NZDCHF",
        "EURAUD",
    }
)
# ^DJI, USDCHF, EURCHF removed 2026-06-26 after trend-exhaustion features improved BuyWR above breakeven.

DEFAULT_THRESHOLDS = {
    "hi_thresh": 0.575,
    "lo_thresh": 0.425,
}


def load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config

    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def load_signals(asset: str) -> pd.DataFrame | None:
    """Load walk-forward signal parquet for a single asset."""
    paths = [
        WALKDIR / f"{asset}_wf_signals_base.parquet",
        WALKDIR / f"{asset}_wf_signals.parquet",
    ]
    for p in paths:
        if p.exists():
            df = pd.read_parquet(p)
            if not df.empty:
                return df
    return None


def compute_metrics(
    df: pd.DataFrame,
    buy_threshold: float,
    sell_threshold: float,
    tp: float,
    sl: float,
) -> dict:
    """Compute BUY/SELL metrics at given thresholds using tp/sl for R."""
    p_long = df["p_long"].values
    labels = df["label"].values  # 1 = UP/win, 0 = DOWN/loss

    buy_mask = p_long > buy_threshold
    sell_mask = p_long < sell_threshold
    flat_mask = ~buy_mask & ~sell_mask

    n_buy = int(buy_mask.sum())
    n_sell = int(sell_mask.sum())
    n_flat = int(flat_mask.sum())

    # BUY: correct when label == 1, wrong when label == 0
    buy_correct = labels[buy_mask].sum() if n_buy > 0 else 0
    buy_wrong = n_buy - buy_correct if n_buy > 0 else 0
    buy_wr = buy_correct / n_buy if n_buy > 0 else 0.0
    buy_r = buy_correct * tp - buy_wrong * sl if n_buy > 0 else 0.0

    # SELL: correct when label == 0, wrong when label == 1
    sell_correct = (labels[sell_mask] == 0).sum() if n_sell > 0 else 0
    sell_wrong = n_sell - sell_correct if n_sell > 0 else 0
    sell_wr = sell_correct / n_sell if n_sell > 0 else 0.0
    sell_r = sell_correct * tp - sell_wrong * sl if n_sell > 0 else 0.0

    return {
        "n_buy": n_buy,
        "n_sell": n_sell,
        "n_flat": n_flat,
        "buy_wr": round(buy_wr, 4),
        "sell_wr": round(sell_wr, 4),
        "buy_total_r": round(buy_r, 2),
        "sell_total_r": round(sell_r, 2),
        "total_r": round(buy_r + sell_r, 2),
    }


def find_optimal_thresholds(
    df: pd.DataFrame,
    tp: float,
    sl: float,
    step: float = 0.01,
    min_trades: int = 5,
) -> dict:
    """Scan threshold space to find optimal BUY and SELL thresholds.

    Returns dict with best thresholds and their metrics.
    """
    p_long = df["p_long"].values
    labels = df["label"].values
    n = len(df)

    thresholds = np.arange(step, 1.0, step)

    best_buy_theta = 0.5
    best_buy_r = -1e9
    best_sell_theta = 0.5
    best_sell_r = -1e9

    buy_curve: list[dict] = []
    sell_curve: list[dict] = []

    for theta in thresholds:
        # BUY: p_long > theta
        buy_mask = p_long > theta
        n_b = int(buy_mask.sum())
        if n_b >= min_trades:
            bc = labels[buy_mask].sum()
            bw = n_b - bc
            buy_r = bc * tp - bw * sl
            buy_wr = bc / n_b
        else:
            buy_r = -1e9
            buy_wr = 0.0

        if buy_r > best_buy_r:
            best_buy_r = buy_r
            best_buy_theta = theta

        buy_curve.append(
            {"threshold": round(theta, 2), "total_r": round(buy_r, 2), "n_trades": n_b, "wr": round(buy_wr, 4)}
        )  # noqa: E501

        # SELL: p_long < 1-theta (i.e., p_long < threshold maps to complement)
        # Actually: SELL if p_long < sell_threshold. scan sell_threshold from 0.01 to 0.99
        sell_mask = p_long < theta
        n_s = int(sell_mask.sum())
        if n_s >= min_trades:
            sc = (labels[sell_mask] == 0).sum()
            sw = n_s - sc
            sell_r = sc * tp - sw * sl
            sell_wr = sc / n_s
        else:
            sell_r = -1e9
            sell_wr = 0.0

        if sell_r > best_sell_r:
            best_sell_r = sell_r
            best_sell_theta = theta

        sell_curve.append(
            {"threshold": round(theta, 2), "total_r": round(sell_r, 2), "n_trades": n_s, "wr": round(sell_wr, 4)}
        )  # noqa: E501

    # Current default threshold metrics
    default = compute_metrics(df, 0.575, 0.425, tp, sl)

    # Best combined: maximize total R (buy_r + sell_r) across all pairs
    best_combined = default.copy()
    best_combined_buy_th = 0.575
    best_combined_sell_th = 0.425

    for buy_th in thresholds:
        for sell_th in thresholds:
            if sell_th >= buy_th:
                continue
            m = compute_metrics(df, buy_th, sell_th, tp, sl)
            if m["total_r"] > best_combined["total_r"]:
                best_combined = m
                best_combined_buy_th = buy_th
                best_combined_sell_th = sell_th

    # Best BUY-only threshold (ignore SELL)
    best_buy_only = compute_metrics(df, best_buy_theta, 0.0, tp, sl)  # sell_th=0 means all are SELL (never fires)

    # Best SELL-only threshold (ignore BUY)
    best_sell_only = compute_metrics(df, 1.0, best_sell_theta, tp, sl)  # buy_th=1 means no BUY ever fires

    return {
        "default": default,
        "best_combined": {
            **best_combined,
            "buy_th": round(best_combined_buy_th, 3),
            "sell_th": round(best_combined_sell_th, 3),
        },  # noqa: E501
        "best_buy_only": {**best_buy_only, "buy_th": round(best_buy_theta, 3)},
        "best_sell_only": {**best_sell_only, "sell_th": round(best_sell_theta, 3)},
        "buy_curve": buy_curve,
        "sell_curve": sell_curve,
        "n_total": n,
        "up_rate": round(float((labels == 1).mean()), 4),
    }


def main():
    parser = argparse.ArgumentParser(description="Threshold optimization for SELL_ONLY assets")
    parser.add_argument(
        "--assets", type=str, default=None, help="Comma-separated asset names (default: all 8 SELL_ONLY)"
    )  # noqa: E501
    parser.add_argument("--step", type=float, default=0.01, help="Threshold scan step (default 0.01)")
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum trades per bucket")
    args = parser.parse_args()

    assets = [a.strip() for a in args.assets.split(",")] if args.assets else sorted(SELL_ONLY_ASSETS)

    pt_sl = load_pt_sl()

    all_results: dict[str, dict] = {}
    for asset in assets:
        df = load_signals(asset)
        if df is None:
            logger.warning("%s: no signal parquet found — skipping", asset)
            continue
        tp, sl = pt_sl.get(asset, (2.0, 2.0))
        logger.info("%s: %d rows, tp=%.2f sl=%.2f", asset, len(df), tp, sl)
        result = find_optimal_thresholds(df, tp, sl, step=args.step, min_trades=args.min_trades)
        all_results[asset] = result

    # ── Print report ──────────────────────────────────────────────────────
    print("=" * 100)
    print("THRESHOLD OPTIMIZATION REPORT — SELL_ONLY ASSETS")
    print("=" * 100)
    print()

    header = (
        f"{'Asset':>9s}  {'n':>4s}  {'UP%':>5s}  "
        f"{'Default R':>10s}  {'Best Combined':>13s}  "
        f"{'Best BUY-only':>13s}  {'Best SELL-only':>13s}"
    )
    print(header)
    print("-" * len(header))

    for asset in assets:
        r = all_results.get(asset)
        if r is None:
            continue
        d = r["default"]
        bc = r["best_combined"]
        bb = r["best_buy_only"]
        bs = r["best_sell_only"]
        print(
            f"{asset:>9s}  {r['n_total']:>4d}  {r['up_rate']:>4.1%}  "
            f"{d['total_r']:>+10.2f}  "
            f"{bc['total_r']:>+8.2f} (t={bc['buy_th']:.2f}/{bc['sell_th']:.2f})  "
            f"{bb['total_r']:>+8.2f} (t={bb['buy_th']:.2f})  "
            f"{bs['total_r']:>+8.2f} (t={bs['sell_th']:.2f})"
        )

    print()
    print("-" * 100)
    print()

    # ── Detail: Best combined thresholds ─────────────────────────────
    print("DETAIL: Best Combined Threshold vs Default")
    print("-" * 72)
    det_header = f"{'Asset':>9s}  {'Config':>12s}  {'buy_th':>6s}  {'sell_th':>6s}  {'n_buy':>6s}  {'n_sell':>6s}  {'BUY_WR':>7s}  {'SELL_WR':>7s}  {'Total R':>8s}"  # noqa: E501
    print(det_header)
    print("-" * len(det_header))
    for asset in assets:
        r = all_results.get(asset)
        if r is None:
            continue
        bc = r["best_combined"]
        print(
            f"{asset:>9s}  {'best_comb':>12s}  {bc['buy_th']:>6.2f}  {bc['sell_th']:>6.2f}  "
            f"{bc['n_buy']:>6d}  {bc['n_sell']:>6d}  {bc['buy_wr']:>6.1%}  "
            f"{bc['sell_wr']:>6.1%}  {bc['total_r']:>+8.2f}"
        )
        d = r["default"]
        print(
            f"{asset:>9s}  {'default':>12s}  {0.575:>6.2f}  {0.425:>6.2f}  "
            f"{d['n_buy']:>6d}  {d['n_sell']:>6d}  {d['buy_wr']:>6.1%}  "
            f"{d['sell_wr']:>6.1%}  {d['total_r']:>+8.2f}"
        )
        print()

    # ── Summary: CAN threshold optimization fix the inversion? ───────
    print()
    print("=" * 100)
    print("VERDICT: Can threshold optimization restore two-way trading?")
    print("=" * 100)
    print()
    print(f"{'Asset':>9s}  {'Default BUY WR':>15s}  {'Best BUY WR':>13s}  {'Total R Δ':>10s}  {'Restore?':>9s}")
    print("-" * 72)
    for asset in assets:
        r = all_results.get(asset)
        if r is None:
            continue
        d = r["default"]
        bc = r["best_combined"]
        bb = r["best_buy_only"]
        default_buy_wr = d["buy_wr"]
        best_buy_wr = bb["buy_wr"]
        delta_r = bc["total_r"] - d["total_r"]
        can_restore = best_buy_wr > 0.50
        restore_tag = "YES" if can_restore else "NO"

        print(f"{asset:>9s}  {default_buy_wr:>14.1%}  {best_buy_wr:>12.1%}  {delta_r:>+9.2f}  {restore_tag:>9s}")

    print()
    print("NOTE: 'Best BUY WR' uses the optimal BUY-only threshold (may reduce trade count).")
    print("Restoration requires BUY WR > 50% AND total R improvement over default.")
    print()


if __name__ == "__main__":
    main()
