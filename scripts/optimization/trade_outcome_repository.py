"""Trade outcome repository — flat DataFrame of all completed trades with config enrichment."""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any

import pandas as pd

logger = logging.getLogger("quorrin.optimization.trade_outcome_repository")

LIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "live")
DEFAULT_DB_PATH = os.path.join(LIVE_DIR, "state.db")


class TradeOutcomeRepository:
    """Reads trades + attribution from SQLite, enriches with config tp/sl, returns flat DataFrames."""

    def __init__(self, db_path: str | None = None, config_path: str | None = None):
        self._db_path = db_path or DEFAULT_DB_PATH
        self._config_path = config_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "configs",
            "paper_trading.yaml",
        )
        self._asset_config: dict[str, dict[str, float]] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Read tp_mult, sl_mult per asset from YAML config via config_manager singleton."""
        from paper_trading.config_manager import get_config

        cfg = get_config()
        if not cfg or not hasattr(cfg, "assets"):
            logger.warning("Config not available — tp_mult/sl_mult will not be enriched")
            return
        for name, spec in cfg.assets.items():
            self._asset_config[name] = {
                "tp_mult": float(spec.get("tp_mult", 2.5)),
                "sl_mult": float(spec.get("sl_mult", 1.0)),
            }

    def _connect(self) -> sqlite3.Connection:
        if not os.path.isfile(self._db_path):
            raise FileNotFoundError(f"Trade database not found: {self._db_path}")
        return sqlite3.connect(self._db_path, timeout=5.0)

    def get_outcomes(self, asset: str | None = None, min_trades: int = 0) -> pd.DataFrame:
        """Return flat DataFrame of all completed trades with enriched tp_mult/sl_mult.

        Parameters
        ----------
        asset : str, optional
            Filter to a single asset. If None, returns all assets.
        min_trades : int, optional
            Skip assets with fewer than this many trades.

        Returns
        -------
        pd.DataFrame with columns:
            asset, side, entry_price, exit_price, sl_mult, tp_mult,
            exit_reason, realized_r, mae, mfe, bars, conf_at_entry,
            archetype_at_entry, entry_date, exit_date
        """
        with self._connect() as conn:
            query = """
                SELECT
                    t.asset,
                    t.side,
                    t.entry AS entry_price,
                    t.exit AS exit_price,
                    t.reason AS exit_reason,
                    t.realized_r,
                    t.mae,
                    t.mfe,
                    t.bars,
                    t.conf_at_entry,
                    t.archetype_at_entry,
                    t.entry_date,
                    t.exit_date,
                    a.pred_regime_at_entry AS regime_at_entry,
                    a.exec_entry_slippage_bps,
                    a.friction_entry_slippage_bps,
                    a.friction_exit_slippage_bps
                FROM trades t
                LEFT JOIN attribution a ON t.attribution_trade_id = a.trade_id
                ORDER BY t.entry_date
            """
            df = pd.read_sql_query(query, conn)

        if df.empty:
            return df

        df["side"] = df["side"].str.lower()
        df["tp_mult"] = df["asset"].map({k: v["tp_mult"] for k, v in self._asset_config.items()})
        df["sl_mult"] = df["asset"].map({k: v["sl_mult"] for k, v in self._asset_config.items()})

        df["tp_distance_pct"] = df["tp_mult"] * df["sl_mult"]  # placeholder — will be refined with ATR
        df["breakeven_wr"] = df["sl_mult"] / (df["tp_mult"] + df["sl_mult"])
        df["r_to_breakeven"] = df["realized_r"] / df["breakeven_wr"]

        df["mfe_capture_ratio"] = df["mfe"] / (df["tp_mult"] * df["sl_mult"] * df["entry_price"].abs() + 1e-10)
        df["mae_tolerance_ratio"] = df["mae"] / (df["sl_mult"] * df["sl_mult"] * df["entry_price"].abs() + 1e-10)

        if asset:
            df = df[df["asset"] == asset].copy()

        if min_trades > 0 and asset is None:
            counts = df["asset"].value_counts()
            keep = counts[counts >= min_trades].index
            df = df[df["asset"].isin(keep)].copy()

        return df

    def get_directional_outcomes(self, asset: str | None = None, min_trades: int = 0) -> pd.DataFrame:
        """Same as get_outcomes but with buy/sell segmentation columns."""
        df = self.get_outcomes(asset=asset, min_trades=0)
        if df.empty:
            return df

        def _agg(grp: pd.DataFrame) -> dict[str, Any]:
            if grp.empty:
                return {}
            total = len(grp)
            wins = (grp["realized_r"] > 0).sum()
            return {
                "n_trades": total,
                "win_rate": wins / total if total > 0 else 0.0,
                "avg_r": grp["realized_r"].mean(),
                "total_r": grp["realized_r"].sum(),
                "avg_mae": grp["mae"].mean(),
                "avg_mfe": grp["mfe"].mean(),
                "avg_bars": grp["bars"].mean(),
                "tp_rate": (grp["exit_reason"] == "TP").mean(),
                "sl_rate": (grp["exit_reason"] == "SL").mean(),
            }

        by_asset = df.groupby("asset")
        summary_rows: list[dict[str, Any]] = []
        for name, group in by_asset:
            buy_grp = group[group["side"] == "long"]
            sell_grp = group[group["side"] == "short"]
            buy_stats = _agg(buy_grp)
            sell_stats = _agg(sell_grp)

            tp = self._asset_config.get(name, {})
            row = {
                "asset": name,
                "n_trades": len(group),
                "buy_n": buy_stats.get("n_trades", 0),
                "buy_wr": buy_stats.get("win_rate", 0.0),
                "buy_avg_r": buy_stats.get("avg_r", 0.0),
                "sell_n": sell_stats.get("n_trades", 0),
                "sell_wr": sell_stats.get("win_rate", 0.0),
                "sell_avg_r": sell_stats.get("avg_r", 0.0),
                "total_r": group["realized_r"].sum(),
                "avg_bars": group["bars"].mean(),
                "tp_mult": tp.get("tp_mult", 2.5),
                "sl_mult": tp.get("sl_mult", 1.0),
                "breakeven_wr": tp.get("sl_mult", 1.0) / (tp.get("tp_mult", 2.5) + tp.get("sl_mult", 1.0) + 1e-10),
                "buy_gap": 0.0,
                "sell_gap": 0.0,
            }
            be = row["breakeven_wr"]
            row["buy_gap"] = row["buy_wr"] - be
            row["sell_gap"] = row["sell_wr"] - be
            summary_rows.append(row)

        result = pd.DataFrame(summary_rows)
        if min_trades > 0:
            result = result[result["n_trades"] >= min_trades].copy()
        return result

    def close(self) -> None:
        pass
