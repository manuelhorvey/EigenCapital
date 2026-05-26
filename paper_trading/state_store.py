import fcntl
import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger("quantforge.state_store")

SCHEMA_VERSION = "1.0.0"


@dataclass
class EngineSnapshot:
    schema_version: str = SCHEMA_VERSION
    timestamp: str = ""
    portfolio: dict | None = None
    assets: dict | None = None
    open_positions: dict | None = None
    engine_status: dict | None = None
    halt_conditions: dict | None = None
    risk_signals: dict | None = None
    shadow_actions: dict | None = None
    risk_parity: dict | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSnapshot":
        return cls(
            schema_version=d.get("schema_version", "0.0.0"),
            timestamp=d.get("timestamp", ""),
            portfolio=d.get("portfolio"),
            assets=d.get("assets"),
            open_positions=d.get("open_positions"),
            engine_status=d.get("engine_status"),
            halt_conditions=d.get("halt_conditions"),
            risk_signals=d.get("risk_signals"),
            shadow_actions=d.get("shadow_actions"),
            risk_parity=d.get("risk_parity"),
        )


_SKIP_JOURNAL = object()


def sanitize(obj):
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(v) for v in obj]
    elif isinstance(obj, (float, np.floating)) and (math.isinf(obj) or math.isnan(obj)):
        return None
    return obj


class StateStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.live_dir = os.path.join(base_dir, "data", "live")
        self.state_path = os.path.join(self.live_dir, "state.json")
        self.trade_journal_path = os.path.join(self.live_dir, "trade_journal.parquet")
        self.confidence_bucket_path = os.path.join(self.live_dir, "confidence_buckets.parquet")
        self.equity_history_path = os.path.join(self.live_dir, "equity_history.json")
        self.review_log_path = os.path.join(self.live_dir, "review_log.json")
        self.trade_outcomes_path = os.path.join(self.live_dir, "trade_outcomes.json")
        self.cache_dir = os.path.join(self.live_dir, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.live_dir, exist_ok=True)

    def save_snapshot(self, snapshot: EngineSnapshot) -> None:
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        tmp_path = self.state_path + ".tmp"
        data = sanitize(asdict(snapshot))
        with open(tmp_path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2, default=str)
            fcntl.flock(f, fcntl.LOCK_UN)
        os.replace(tmp_path, self.state_path)

    def load_snapshot(self) -> EngineSnapshot | None:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path) as f:
                data = json.load(f)
            return EngineSnapshot.from_dict(data)
        except Exception as e:
            logger.warning("Failed to load state snapshot: %s", e)
            return None

    def append_trade(self, trade: dict) -> None:
        df = pd.DataFrame([trade])
        if os.path.exists(self.trade_journal_path):
            existing = pd.read_parquet(self.trade_journal_path)
            for col in ("entry_date", "exit_date"):
                if col in existing.columns:
                    existing[col] = existing[col].astype(str)
                if col in df.columns:
                    df[col] = df[col].astype(str)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_parquet(self.trade_journal_path)

    def read_trades(self, limit: int = 10) -> list:
        try:
            if os.path.exists(self.trade_journal_path):
                df = pd.read_parquet(self.trade_journal_path)
                if len(df) > 0:
                    df = df.sort_values("exit_date", ascending=False).head(limit)
                    return json.loads(df.to_json(orient="records", default_handler=str))
        except Exception:
            pass
        return []

    def read_trades_since(self, date: str) -> pd.DataFrame:
        columns = ["asset", "side", "entry", "exit", "return", "bars", "reason", "entry_date", "exit_date"]
        if not os.path.exists(self.trade_journal_path):
            return pd.DataFrame(columns=columns)
        try:
            df = pd.read_parquet(self.trade_journal_path)
            if df.empty:
                return pd.DataFrame(columns=columns)
            missing = [c for c in columns if c not in df.columns]
            if missing:
                for c in missing:
                    df[c] = None
            return df[df["exit_date"] >= date].copy()
        except Exception:
            return pd.DataFrame(columns=columns)

    def read_trade_outcomes(self) -> dict | None:
        if not os.path.exists(self.trade_outcomes_path):
            return None
        try:
            with open(self.trade_outcomes_path) as f:
                return json.load(f)
        except Exception:
            return None

    def write_trade_outcomes_cache(self) -> None:
        if not os.path.exists(self.trade_journal_path):
            return
        try:
            df = pd.read_parquet(self.trade_journal_path)
            if df.empty:
                return

            reason_col = "reason" if "reason" in df.columns else "exit_reason"
            ret_col = "return" if "return" in df.columns else "pnl"
            r_col = "realized_r" if "realized_r" in df.columns else None

            df[reason_col] = (
                df[reason_col]
                .astype(str)
                .str.lower()
                .replace(
                    {
                        "sl_hit": "sl",
                        "tp_hit": "tp",
                        "gate_closed": "signal_flip",
                    }
                )
            )
            df[ret_col] = pd.to_numeric(df[ret_col], errors="coerce").fillna(0.0)

            by_asset = []
            for asset_name, group in df.groupby("asset"):
                n = len(group)
                tp = (group[reason_col] == "tp").sum()
                sl = (group[reason_col] == "sl").sum()
                flip = (group[reason_col] == "signal_flip").sum()
                wins = (group[ret_col] > 0).sum()
                total_profit = group[ret_col].clip(lower=0).sum()
                total_loss = (-group[ret_col].clip(upper=0)).sum()
                avg_r = float(group[r_col].mean()) if r_col and r_col in group else 0.0

                by_asset.append(
                    {
                        "asset": asset_name,
                        "n_trades": int(n),
                        "tp_rate": round(float(tp) / n, 4) if n > 0 else 0.0,
                        "sl_rate": round(float(sl) / n, 4) if n > 0 else 0.0,
                        "signal_flip_rate": round(float(flip) / n, 4) if n > 0 else 0.0,
                        "avg_r": round(avg_r, 4),
                        "win_rate": round(float(wins) / n, 4) if n > 0 else 0.0,
                        "profit_factor": round(float(total_profit / total_loss), 4) if total_loss > 0 else None,
                    }
                )

            n_total = len(df)
            tp_total = int((df[reason_col] == "tp").sum())
            sl_total = int((df[reason_col] == "sl").sum())
            flip_total = int((df[reason_col] == "signal_flip").sum())
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
                    "profit_factor": round(profit_total / loss_total, 4) if loss_total > 0 else None,
                },
                "by_asset": by_asset,
                "updated_at": datetime.now().isoformat(),
            }

            with open(self.trade_outcomes_path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.warning("Failed to write trade outcomes cache: %s", e)

    def append_confidence_bucket(self, bucket: dict) -> None:
        df = pd.DataFrame([bucket])
        if os.path.exists(self.confidence_bucket_path) and os.path.getsize(self.confidence_bucket_path) > 0:
            try:
                existing = pd.read_parquet(self.confidence_bucket_path)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                pass
        df.to_parquet(self.confidence_bucket_path)

    def append_equity_history(self, record: dict) -> None:
        os.makedirs(os.path.dirname(self.equity_history_path), exist_ok=True)
        history = []
        if os.path.exists(self.equity_history_path):
            try:
                with open(self.equity_history_path) as f:
                    history = json.load(f)
            except (json.JSONDecodeError, ValueError):
                history = []
        history.append(record)
        history = sanitize(history[-2000:])
        with open(self.equity_history_path, "w") as f:
            json.dump(history, f, indent=2, allow_nan=False)

    def read_equity_history(self) -> list:
        if not os.path.exists(self.equity_history_path):
            return []
        try:
            with open(self.equity_history_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            return []

    def cache_path(self, ticker: str) -> str:
        safe_name = ticker.replace("=", "_").replace("-", "_")
        return os.path.join(self.cache_dir, f"{safe_name}.parquet")

    def save_cache(self, ticker: str, df: pd.DataFrame) -> None:
        path = self.cache_path(ticker)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path)

    def load_cache(self, ticker: str) -> pd.DataFrame | None:
        path = self.cache_path(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning("Cache read error for %s: %s", ticker, e)
        return None
