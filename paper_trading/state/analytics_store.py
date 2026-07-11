import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime

import pandas as pd
import pytz

from paper_trading.state import atomic_write_json

logger = logging.getLogger("eigencapital.state_store")

ET = pytz.timezone("US/Eastern")


class _AnalyticsStore:
    """Precomputed trade outcomes and aggregated analytics snapshots."""

    def __init__(self, db_store, analytics_path: str, trade_outcomes_path: str):
        self._db = db_store
        self._analytics_path = analytics_path
        self._trade_outcomes_path = trade_outcomes_path
        self._analytics_snapshot_counter = 0
        self._analytics_snapshot_frequency = 5
        self._analytics_lock = threading.Lock()
        self._trade_outcomes_cache: tuple[dict, float] | None = None

    def write_trade_outcomes_cache(self) -> None:
        self.read_trade_outcomes()

    def read_trade_outcomes(self) -> dict | None:
        now = time.monotonic()
        if self._trade_outcomes_cache is not None and now - self._trade_outcomes_cache[1] < 30.0:
            return self._trade_outcomes_cache[0]
        result = self._compute_trade_outcomes()
        if result is not None:
            self._trade_outcomes_cache = (result, now)
        return result

    def _compute_trade_outcomes(self) -> dict | None:
        try:
            with sqlite3.connect(self._db._db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM trades WHERE exit_date >= date('now', '-1 year') LIMIT 100000"
                ).fetchall()
                if not rows:
                    return None
                df = pd.DataFrame([dict(r) for r in rows])

            reason_col = "reason" if "reason" in df.columns else "exit_reason"
            ret_col = "return" if "return" in df.columns else "pnl"
            r_col = "realized_r" if "realized_r" in df.columns else None

            if reason_col in df.columns:
                df[reason_col] = (
                    df[reason_col]
                    .fillna("")
                    .astype(str)
                    .str.upper()
                    .replace({"SL_HIT": "SL", "TP_HIT": "TP", "GATE_CLOSED": "FLIP"})
                )
            # Normalize TRAILING_SL to a canonical form for upstream consumers
            if reason_col in df.columns:
                df[reason_col] = df[reason_col].str.replace("TRAILING_STOP", "TRAILING_SL", regex=False)
            if ret_col in df.columns:
                df[ret_col] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)

            by_asset = []
            for asset_name, group in df.groupby("asset"):
                n = len(group)
                tp = int((group[reason_col] == "TP").sum())
                sl = int((group[reason_col] == "SL").sum())
                flip = int((group[reason_col] == "FLIP").sum())
                wins = int((group[ret_col] > 0).sum())
                total_profit = float(group[ret_col].clip(lower=0).sum())
                total_loss = float((-group[ret_col].clip(upper=0)).sum())
                avg_r = float(group[r_col].mean()) if r_col and r_col in group else 0.0
                by_asset.append(
                    {
                        "asset": asset_name,
                        "n_trades": n,
                        "tp_rate": round(tp / n, 4) if n > 0 else 0.0,
                        "sl_rate": round(sl / n, 4) if n > 0 else 0.0,
                        "signal_flip_rate": round(flip / n, 4) if n > 0 else 0.0,
                        "avg_r": round(avg_r, 4),
                        "win_rate": round(wins / n, 4) if n > 0 else 0.0,
                        "profit_factor": (
                            round(total_profit / total_loss, 4)
                            if total_loss > 0
                            else (float("inf") if total_profit > 0 else None)
                        ),
                    }
                )

            n_total = len(df)
            tp_total = int((df[reason_col] == "TP").sum())
            sl_total = int((df[reason_col] == "SL").sum())
            flip_total = int((df[reason_col] == "FLIP").sum())
            wins_total = int((df[ret_col] > 0).sum())
            profit_total = float(df[ret_col].clip(lower=0).sum())
            loss_total = float((-df[ret_col].clip(upper=0)).sum())
            avg_r_total = float(df[r_col].mean()) if r_col and r_col in df.columns else 0.0

            payload = {
                "overall": {
                    "tp_rate": round(tp_total / n_total, 4) if n_total > 0 else 0.0,
                    "sl_rate": round(sl_total / n_total, 4) if n_total > 0 else 0.0,
                    "signal_flip_rate": round(flip_total / n_total, 4) if n_total > 0 else 0.0,
                    "avg_r": round(avg_r_total, 4),
                    "win_rate": round(wins_total / n_total, 4) if n_total > 0 else 0.0,
                    "profit_factor": (
                        round(profit_total / loss_total, 4)
                        if loss_total > 0
                        else (float("inf") if profit_total > 0 else None)
                    ),
                },
                "by_asset": by_asset,
                "updated_at": datetime.now(tz=ET).isoformat(),
            }
            atomic_write_json(self._trade_outcomes_path, payload)
            return payload
        except Exception:
            logger.exception("Failed to compute trade outcomes")
            return None

    def write_snapshot(self) -> None:
        self._analytics_snapshot_counter += 1
        if self._analytics_snapshot_counter < self._analytics_snapshot_frequency:
            return
        self._analytics_snapshot_counter = 0

        attrs = self._db.read_attribution(limit=2000)
        shadows = self._db.read_shadow_trades(limit=2000)
        snapshot: dict = {}

        if attrs:
            df = pd.DataFrame(attrs)
            arch_col = "pred_archetype_at_entry"
            regime_col = "pred_regime_at_entry"
            reason_col = "exit_reason"

            if "exit_realized_r" in df.columns:
                r_values = df["exit_realized_r"]
            elif "realized_r" in df.columns:
                r_values = df["realized_r"]
            else:
                r_values = pd.Series([0.0] * len(df))

            reason_series = df.get(reason_col) if reason_col in df.columns else pd.Series(dtype=object)
            has_reason = len(reason_series) > 0
            snapshot["overall"] = {
                "n_trades": len(df),
                "avg_r": float(r_values.mean()),
                "win_rate": float((r_values > 0).mean()),
                "tp_rate": float((reason_series == "tp").mean()) if has_reason else 0.0,
                "sl_rate": float((reason_series == "sl").mean()) if has_reason else 0.0,
            }
            by_arch = {}
            if arch_col in df.columns:
                for arch, grp in df.groupby(arch_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    grp_reason = grp.get(reason_col) if reason_col in grp.columns else pd.Series(dtype=object)
                    grp_has_reason = len(grp_reason) > 0
                    by_arch[arch] = {
                        "n": len(grp),
                        "avg_r": float(grp_r.mean()),
                        "win_rate": float((grp_r > 0).mean()),
                        "tp_rate": float((grp_reason == "tp").mean()) if grp_has_reason else 0.0,
                        "sl_rate": float((grp_reason == "sl").mean()) if grp_has_reason else 0.0,
                        "avg_entry_slippage": float(grp.get("friction_entry_slippage_bps", 0).mean()),
                        "avg_mae": float(grp.get("exit_mae", 0).mean()),
                        "avg_mfe": float(grp.get("exit_mfe", 0).mean()),
                    }
            snapshot["by_archetype"] = by_arch
            by_reg = {}
            if regime_col in df.columns:
                for reg, grp in df.groupby(regime_col):
                    grp_r = grp.get("exit_realized_r", 0)
                    by_reg[reg] = {"n": len(grp), "avg_r": float(grp_r.mean()), "win_rate": float((grp_r > 0).mean())}
            snapshot["by_regime"] = by_reg

        if shadows:
            sdf = pd.DataFrame(shadows)
            n = len(sdf)
            same = (sdf.get("exit_reason", "") == sdf.get("live_exit_reason", "")).sum()
            shadow_divergence_rate = 1 - (same / n) if n > 0 else 0
            r_delta = sdf.get("realized_r", 0) - sdf.get("live_realized_r", 0)
            snapshot["shadow"] = {
                "n": n,
                "divergence_rate": round(shadow_divergence_rate, 4),
                "avg_r_delta": round(float(r_delta.mean()), 4),
            }

        snapshot["updated_at"] = datetime.now(tz=ET).isoformat()
        try:
            atomic_write_json(self._analytics_path, snapshot)
        except OSError as e:
            logger.error("Failed to write analytics snapshot: %s", e)

    def read_snapshot(self) -> dict | None:
        if not os.path.exists(self._analytics_path):
            return None
        try:
            with open(self._analytics_path) as f:
                return json.load(f)
        except Exception:
            return None
