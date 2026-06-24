#!/usr/bin/env python3
"""
Per-direction win rate monitoring — compares live and walk-forward OOS
per-direction performance.

Fast signal: if SELL WR on a SELL_ONLY asset drops >10pp below baseline,
the model is degrading regardless of whether the BUY/SELL asymmetry is
closing.

Slow signal: OOS BUY WR trend on SELL_ONLY assets — if it crosses >30%,
the asymmetry may be healing (reopen investigation).

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/check_direction_win_rates.py
    PYTHONPATH=$PYTHONPATH:. python scripts/check_direction_win_rates.py --live-db data/live/state.db

All data is read-only (signal parquets, baseline CSV, state.db trades).
No new pipeline code, no model loading, no inference.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("check_direction_wr")

WALKDIR = Path(__file__).resolve().parent.parent / "walkforward"
BASELINE_CSV = WALKDIR / "pnl_backtest_base.csv"

SELL_ONLY_ASSETS: frozenset[str] = frozenset(
    {
        "CADCHF", "AUDUSD", "ES", "NQ", "NZDCHF",
        "EURAUD", "^DJI", "USDCHF", "EURCHF",
        "NZDUSD", "EURNZD",
    }
)

ALERT_SELL_DRIFT_PP = 10.0  # SELL WR drop >10pp → alert
ALERT_BUY_OOS_WR = 0.30  # OOS BUY WR > 30% → asymmetry may be healing


def compute_dir_wr_from_parquets() -> dict[str, dict]:
    """Compute per-direction win rates from all walk-forward signal parquets.

    Returns dict[asset_name, {buy_wr, sell_wr, n_buy, n_sell, buy_r, sell_r}].
    """
    pt_sl = _load_pt_sl()
    files = sorted(Path(WALKDIR).glob("*_wf_signals.parquet"))
    if not files:
        logger.error("No signal parquets found in %s", WALKDIR)
        return {}

    results: dict[str, dict] = {}
    for fpath in files:
        name = fpath.stem.replace("_wf_signals", "")
        if name not in pt_sl:
            continue
        tp, sl = pt_sl[name]
        df = pd.read_parquet(fpath)

        buy = df[df["signal"] == 1]
        sell = df[df["signal"] == -1]

        n_buy = len(buy)
        n_sell = len(sell)

        buy_wr = float(buy["label"].mean()) if n_buy > 0 else 0.0
        sell_wr = float((sell["label"] == 0).mean()) if n_sell > 0 else 0.0

        buy_r = float((buy["label"] * tp - (1 - buy["label"]) * sl).sum()) if n_buy > 0 else 0.0
        sell_r = float(((sell["label"] == 0) * tp - (sell["label"] == 1) * sl).sum()) if n_sell > 0 else 0.0

        results[name] = {
            "buy_wr": round(buy_wr, 4),
            "sell_wr": round(sell_wr, 4),
            "n_buy": n_buy,
            "n_sell": n_sell,
            "buy_total_r": round(buy_r, 2),
            "sell_total_r": round(sell_r, 2),
        }

    return results


def load_live_trades(db_path: str) -> dict[str, dict]:
    """Load live per-direction win rates from state.db.

    Returns same structure as compute_dir_wr_from_parquets, or empty dict
    if db is missing or empty.
    """
    if not os.path.isfile(db_path):
        logger.warning("Live DB not found at %s — skipping live comparison", db_path)
        return {}

    try:
        conn = sqlite3.connect(db_path)
        query = """
            SELECT asset, side, COUNT(*) as n,
                   SUM(CASE WHEN return > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(return) AS total_r
            FROM trades
            WHERE side IS NOT NULL AND side != ''
            GROUP BY asset, side
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
    except Exception as e:
        logger.warning("Failed to query live DB: %s — skipping live comparison", e)
        return {}

    if df.empty:
        logger.info("Live trades table is empty — no live data yet")
        return {}

    results: dict[str, dict] = {}
    for asset in df["asset"].unique():
        asset_df = df[df["asset"] == asset]
        buy_row = asset_df[asset_df["side"].str.lower().isin(["buy", "long"])]
        sell_row = asset_df[asset_df["side"].str.lower().isin(["sell", "short"])]

        if not buy_row.empty and buy_row["n"].iloc[0] > 0:
            buy_wr = float(buy_row["wins"].iloc[0] / buy_row["n"].iloc[0])
        else:
            buy_wr = 0.0
        if not sell_row.empty and sell_row["n"].iloc[0] > 0:
            sell_wr = float(sell_row["wins"].iloc[0] / sell_row["n"].iloc[0])
        else:
            sell_wr = 0.0
        n_buy = int(buy_row["n"].iloc[0]) if not buy_row.empty else 0
        n_sell = int(sell_row["n"].iloc[0]) if not sell_row.empty else 0
        buy_r = float(buy_row["total_r"].iloc[0]) if not buy_row.empty else 0.0
        sell_r = float(sell_row["total_r"].iloc[0]) if not sell_row.empty else 0.0

        results[asset] = {
            "buy_wr": round(buy_wr, 4),
            "sell_wr": round(sell_wr, 4),
            "n_buy": n_buy,
            "n_sell": n_sell,
            "buy_total_r": round(buy_r, 2),
            "sell_total_r": round(sell_r, 2),
        }

    return results


def _load_pt_sl() -> dict[str, tuple[float, float]]:
    from paper_trading.config_manager import get_config
    cfg = get_config()
    result: dict[str, tuple[float, float]] = {}
    for name, acfg in cfg.assets.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        result[name] = (tp, sl)
    return result


def format_report(
    oos_dir_wr: dict[str, dict],
    live_dir_wr: dict[str, dict],
) -> str:
    """Generate the monitoring report table.

    Columns:
        Asset, sell_only, live_n, BUY_WR, baseline_BUY_WR, SELL_WR,
        baseline_SELL_WR, SELL_DRIFT, OOS_BUY_WR, OOS_BUY_TREND
    """
    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("PER-DIRECTION WIN RATE MONITORING")
    lines.append("=" * 90)
    lines.append("")

    alerts: list[str] = []

    # Header
    header = (
        f"{'Asset':>10s}  {'SO':>3s}  {'LiveN':>6s}  "
        f"{'BUY_WR':>7s}  {'OOS_B_WR':>8s}  {'SELL_WR':>7s}  "
        f"{'OOS_S_WR':>8s}  {'SELL_drift':>10s}  {'OOS_BUY_t':>9s}"
    )
    lines.append(header)
    lines.append("-" * 90)

    all_assets = sorted(set(list(oos_dir_wr.keys()) | set(live_dir_wr.keys())))

    for asset in all_assets:
        is_so = asset in SELL_ONLY_ASSETS
        so_mark = "Y" if is_so else "N"

        oos = oos_dir_wr.get(asset, {})
        live = live_dir_wr.get(asset, {})

        live_buy_wr = live.get("buy_wr", 0.0)
        live_sell_wr = live.get("sell_wr", 0.0)
        live_n_buy = live.get("n_buy", 0)
        live_n_sell = live.get("n_sell", 0)
        live_n = live_n_buy + live_n_sell

        oos_buy_wr = oos.get("buy_wr", 0.0)
        oos_sell_wr = oos.get("sell_wr", 0.0)

        # SELL drift: live vs OOS baseline
        if live_n_sell >= 5:
            sell_drift = (live_sell_wr - oos_sell_wr) * 100  # percentage points
            sell_drift_str = f"{sell_drift:+.1f}pp"
            if sell_drift < -ALERT_SELL_DRIFT_PP:
                alerts.append(
                    f"ALERT: {asset} SELL WR dropped {sell_drift:.1f}pp "
                    f"(live={live_sell_wr:.1%}, baseline={oos_sell_wr:.1%}) — model degrading"
                )
        else:
            sell_drift_str = "N/A (<5)"
            sell_drift = 0.0

        # OOS BUY WR trend (slow signal)
        if is_so:
            if oos_buy_wr > ALERT_BUY_OOS_WR:
                oos_buy_trend = "HEALING"
                alerts.append(
                    f"NOTE: {asset} OOS BUY WR={oos_buy_wr:.1%} > 30% — "
                    f"asymmetry may be healing, reopen investigation"
                )
            elif oos_buy_wr > 0.20:
                oos_buy_trend = "WATCH"
            else:
                oos_buy_trend = "stable"
        else:
            oos_buy_trend = "-"

        # Format live WR (or N/A if no live data)
        live_buy_str = f"{live_buy_wr:.1%}" if live_n_buy >= 5 else "N/A"
        live_sell_str = f"{live_sell_wr:.1%}" if live_n_sell >= 5 else "N/A"

        lines.append(
            f"{asset:>10s}  {so_mark:>3s}  {live_n:>6d}  "
            f"{live_buy_str:>7s}  {oos_buy_wr:>7.1%}  "
            f"{live_sell_str:>7s}  {oos_sell_wr:>7.1%}  "
            f"{sell_drift_str:>10s}  {oos_buy_trend:>9s}"
        )

    lines.append("")
    lines.append("-" * 90)

    if alerts:
        lines.append("")
        lines.append("ALERTS:")
        for a in alerts:
            lines.append(f"  {a}")
    else:
        lines.append("No alerts.")

    lines.append("")
    lines.append("=" * 90)
    lines.append("  SELL_DRIFT: live SELL WR minus OOS baseline SELL WR (pp)")
    lines.append("  OOS_BUY_t:  trend in OOS BUY WR (healing if >30% on SELL_ONLY assets)")
    lines.append("  Live data requires N≥5 per direction to display WR")
    lines.append("=" * 90)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Per-direction win rate monitoring"
    )
    parser.add_argument(
        "--live-db",
        default=str(Path(__file__).resolve().parent.parent / "data/live/state.db"),
        help="Path to live state.db (default: data/live/state.db)",
    )
    args = parser.parse_args()

    logger.info("Computing OOS per-direction win rates from signal parquets...")
    oos_wr = compute_dir_wr_from_parquets()
    logger.info("Loaded OOS data for %d assets", len(oos_wr))

    logger.info("Loading live trades from %s...", args.live_db)
    live_wr = load_live_trades(args.live_db)
    if live_wr:
        logger.info("Loaded live trades for %d assets", len(live_wr))
    else:
        logger.info("No live trades available — reporting OOS-only analysis")

    report = format_report(oos_wr, live_wr)
    print(report)

    # Return non-zero exit code if any alert fires (for CI/CD gates)
    if any("ALERT" in line for line in report.split("\n")):
        logger.warning("Alerts detected — see report above")
        sys.exit(1)


if __name__ == "__main__":
    main()
