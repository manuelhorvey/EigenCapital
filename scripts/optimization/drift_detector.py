"""Live win-rate drift detector — compares live trade outcomes against breakeven WR.

Queries SQLite trade database for each asset, computes rolling win rate
(last N trades), and compares against breakeven win rate (from config).
Flags assets where WR margin (WR - BE_WR) is negative or declining.

Output: structured dict suitable for dashboard consumption as state.json
extensions under `assets[name].metrics.optimization` key.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from paper_trading.config_manager import get_config
from scripts.backtest.monte_carlo_drawdown import SELL_ONLY_ASSETS

logger = logging.getLogger("eigencapital.optimization.drift_detector")

DEFAULT_DB_PATH = "data/live/trades.db"
ROLLING_WINDOW = 20
MIN_TRADES = 5


@dataclass
class AssetDrift:
    asset: str
    n_trades: int
    breakeven_wr: float
    win_rate: float
    wr_margin: float
    rolling_wr: list[float]
    trend: str
    trend_slope: float
    flagged: bool
    flag_reason: str = ""


@dataclass
class DriftReport:
    generated_at: str
    n_assets: int
    flagged_assets: list[AssetDrift]
    healthy_assets: list[AssetDrift]
    all_assets: list[AssetDrift]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_trades_from_sqlite(db_path: str | Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """Load all trade exits from the SQLite trade database."""
    if not os.path.exists(db_path):
        logger.warning("Trade database not found at %s", db_path)
        return pd.DataFrame()

    conn = sqlite3.connect(db_path)
    try:
        trades = pd.read_sql_query(
            "SELECT asset, direction, entry_price, exit_price, exit_reason, "
            "entry_date, exit_date, pnl, tp_mult, sl_mult, volume, "
            "r_multiple FROM trades ORDER BY entry_date",
            conn,
        )
    except pd.io.sql.DatabaseError:
        # Table might not exist yet
        conn.close()
        return pd.DataFrame()

    conn.close()

    if trades.empty:
        return trades

    required = {"asset", "direction", "exit_price", "exit_reason", "pnl"}
    missing = required - set(trades.columns)
    if missing:
        logger.warning("Trade database missing columns: %s", missing)
        return pd.DataFrame()

    trades["entry_date"] = pd.to_datetime(trades["entry_date"], errors="coerce")
    trades["exit_date"] = pd.to_datetime(trades["exit_date"], errors="coerce")

    if tp_mult := trades.get("tp_mult"):
        trades["tp_mult"] = pd.to_numeric(tp_mult, errors="coerce").fillna(2.0)
    if sl_mult := trades.get("sl_mult"):
        trades["sl_mult"] = pd.to_numeric(sl_mult, errors="coerce").fillna(2.0)

    return trades


def compute_breakeven_wr(tp: float, sl: float) -> float:
    """Compute breakeven win rate from tp/sl config."""
    return sl / (tp + sl) if (tp + sl) > 0 else 0.5


def detect_drift_for_asset(
    asset: str,
    trades: pd.DataFrame,
    tp: float,
    sl: float,
    sell_only: bool = False,
) -> AssetDrift:
    """Compute drift metrics for a single asset."""
    if trades.empty:
        return AssetDrift(
            asset=asset,
            n_trades=0,
            breakeven_wr=compute_breakeven_wr(tp, sl),
            win_rate=0.0,
            wr_margin=0.0,
            rolling_wr=[],
            trend="flat",
            trend_slope=0.0,
            flagged=False,
        )
    asset_trades = trades[trades["asset"] == asset]
    if asset_trades.empty:
        return AssetDrift(
            asset=asset,
            n_trades=0,
            breakeven_wr=compute_breakeven_wr(tp, sl),
            win_rate=0.0,
            wr_margin=0.0,
            rolling_wr=[],
            trend="flat",
            trend_slope=0.0,
            flagged=False,
        )

    be_wr = compute_breakeven_wr(tp, sl)
    n = len(asset_trades)

    # Filter by direction for SELL_ONLY assets
    if sell_only:
        sell_trades = asset_trades[asset_trades["direction"] == "sell"]
        outcomes = sell_trades["pnl"].values
        all_outcomes = asset_trades["pnl"].values
    else:
        outcomes = asset_trades["pnl"].values
        all_outcomes = outcomes

    total_wr = float((all_outcomes > 0).sum() / len(all_outcomes)) if len(all_outcomes) > 0 else 0.0
    wr_margin = total_wr - be_wr

    # Rolling win rate (last N trades)
    n_rolling = min(ROLLING_WINDOW, len(outcomes))
    rolling_wr = []
    for i in range(1, n_rolling + 1):
        window = outcomes[-i:]
        rolling_wr.append(float((window > 0).sum() / len(window)))

    # Trend detection
    if len(rolling_wr) >= 3:
        x = list(range(len(rolling_wr)))
        y = rolling_wr
        n_pts = len(x)
        slope = (n_pts * sum(x[i] * y[i] for i in range(n_pts)) - sum(x) * sum(y)) / (
            n_pts * sum(x_i * x_i for x_i in x) - sum(x) ** 2 or 1
        )
    else:
        slope = 0.0

    if slope < -0.02:
        trend = "declining"
    elif slope > 0.02:
        trend = "improving"
    else:
        trend = "flat"

    # Flags
    flagged = False
    flag_reason = ""

    if n < MIN_TRADES:
        flagged = True
        flag_reason = f"insufficient_data ({n} trades, need {MIN_TRADES})"
    elif wr_margin < -0.10:
        flagged = True
        flag_reason = f"WR margin {wr_margin:.1%} < -10% (BE WR = {be_wr:.1%})"
    elif trend == "declining" and wr_margin < 0:
        flagged = True
        flag_reason = f"declining trend with negative margin ({wr_margin:.1%})"

    return AssetDrift(
        asset=asset,
        n_trades=n,
        breakeven_wr=round(be_wr, 4),
        win_rate=round(total_wr, 4),
        wr_margin=round(wr_margin, 4),
        rolling_wr=[round(w, 4) for w in rolling_wr],
        trend=trend,
        trend_slope=round(slope, 4),
        flagged=flagged,
        flag_reason=flag_reason,
    )


def run_drift_detection(
    trades_df: pd.DataFrame | None = None,
) -> DriftReport:
    """Run win-rate drift detection across all portfolio assets."""
    if trades_df is None:
        trades_df = load_trades_from_sqlite()

    cfg = get_config()
    assets_config = dict(cfg.assets)

    all_drifts: list[AssetDrift] = []
    for name, acfg in assets_config.items():
        tp = float(acfg.get("tp_mult", 2.0))
        sl = float(acfg.get("sl_mult", 2.0))
        sell_only = name in SELL_ONLY_ASSETS
        drift = detect_drift_for_asset(name, trades_df, tp, sl, sell_only)
        all_drifts.append(drift)

    flagged = [d for d in all_drifts if d.flagged]
    healthy = [d for d in all_drifts if not d.flagged]

    return DriftReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        n_assets=len(all_drifts),
        flagged_assets=flagged,
        healthy_assets=healthy,
        all_assets=all_drifts,
    )


def print_report(report: DriftReport) -> None:
    """Print the drift detection report."""
    print("=" * 85)
    print("  LIVE WIN-RATE DRIFT DETECTION REPORT")
    print(f"  Generated: {report.generated_at}")
    print("=" * 85)

    print(f"\n  {report.n_assets} assets checked")
    print(f"  {len(report.flagged_assets)} flagged, {len(report.healthy_assets)} healthy\n")

    if report.flagged_assets:
        print(f"  {'!' * 50}")
        print("  FLAGGED ASSETS")
        print(f"  {'!' * 50}")
        for d in sorted(report.flagged_assets, key=lambda x: x.asset):
            print(
                f"  ✗ {d.asset:12s}  WR={d.win_rate:.1%}  BE={d.breakeven_wr:.1%}  "
                f"margin={d.wr_margin:+.1%}  {d.trend:>10s}  — {d.flag_reason}"
            )

    print(f"\n  {'─' * 50}")
    print("  HEALTHY ASSETS")
    print(f"  {'─' * 50}")
    for d in sorted(report.healthy_assets, key=lambda x: x.asset):
        wr_str = f"WR={d.win_rate:.1%}" if d.n_trades >= MIN_TRADES else "(no trades)"
        print(f"  ✓ {d.asset:12s}  {wr_str}  BE={d.breakeven_wr:.1%}  margin={d.wr_margin:+.1%}  {d.trend:>10s}")

    print(f"\n{'=' * 85}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import argparse

    parser = argparse.ArgumentParser(description="Live win-rate drift detector")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Path to SQLite trade database")
    args = parser.parse_args()

    report = run_drift_detection()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
