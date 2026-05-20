import logging
import os
import json
import fcntl
import math
import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

logger = logging.getLogger("quantforge.state_store")

SCHEMA_VERSION = "1.0.0"


@dataclass
class EngineSnapshot:
    schema_version: str = SCHEMA_VERSION
    timestamp: str = ""
    portfolio: Optional[dict] = None
    assets: Optional[dict] = None
    open_positions: Optional[dict] = None
    engine_status: Optional[dict] = None
    halt_conditions: Optional[dict] = None
    risk_signals: Optional[dict] = None
    shadow_actions: Optional[dict] = None

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

    def load_snapshot(self) -> Optional[EngineSnapshot]:
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r") as f:
                data = json.load(f)
            return EngineSnapshot.from_dict(data)
        except Exception as e:
            logger.warning("Failed to load state snapshot: %s", e)
            return None

    def append_trade(self, trade: dict) -> None:
        df = pd.DataFrame([trade])
        if os.path.exists(self.trade_journal_path):
            existing = pd.read_parquet(self.trade_journal_path)
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
                with open(self.equity_history_path, "r") as f:
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
            with open(self.equity_history_path, "r") as f:
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

    def load_cache(self, ticker: str) -> Optional[pd.DataFrame]:
        path = self.cache_path(ticker)
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path)
                if not df.empty:
                    return df
            except Exception as e:
                logger.warning("Cache read error for %s: %s", ticker, e)
        return None
