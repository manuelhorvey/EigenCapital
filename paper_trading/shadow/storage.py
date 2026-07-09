"""Shadow storage — buffered persistence of shadow model predictions.

Shadow predictions are batched in memory and flushed to parquet every N cycles
to reduce I/O overhead. Each shadow+asset+date combination is written to its
own parquet file for easy backtest-style analysis.

File layout:

    data/live/shadow/{shadow_id}/{asset}_{date}.parquet
    data/live/shadow/shadow_comparison.db (SQLite, comparison-level)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("eigencapital.shadow_storage")


class ShadowStorage:
    """Buffered, thread-safe shadow prediction storage.

    Accumulates predictions in memory and flushes to parquet + SQLite at a
    configurable interval. Flush is no-op if no predictions have accumulated.
    """

    def __init__(
        self,
        base_dir: str | Path = "data/live/shadow",
        flush_interval: int = 100,
    ):
        self._base = Path(base_dir)
        self._flush_interval = flush_interval
        self._lock = threading.Lock()
        # buffer[shadow_id][asset] = list[dict]
        self._buffer: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        self._cycle_count: dict[str, int] = defaultdict(int)

    def record(
        self,
        shadow_id: str,
        asset: str,
        prod_signal: str,
        prod_confidence: float,
        prod_p_long: float,
        shadow_signal: str,
        shadow_confidence: float,
        shadow_p_long: float,
        feature_hash: str = "",
        model_hash: str = "",
        inference_time_ms: float = 0.0,
    ) -> None:
        """Record a single shadow comparison cycle."""
        with self._lock:
            self._buffer[shadow_id][asset].append(
                {
                    "timestamp": time.time(),
                    "feature_hash": feature_hash,
                    "model_hash": model_hash,
                    "prod_signal": prod_signal,
                    "prod_confidence": prod_confidence,
                    "prod_p_long": prod_p_long,
                    "shadow_signal": shadow_signal,
                    "shadow_confidence": shadow_confidence,
                    "shadow_p_long": shadow_p_long,
                    "inference_time_ms": inference_time_ms,
                    "signal_agreement": prod_signal == shadow_signal,
                    "confidence_delta": round(abs(prod_confidence - shadow_confidence), 6),
                    "p_long_delta": round(abs(prod_p_long - shadow_p_long), 6),
                }
            )
            self._cycle_count[shadow_id] += 1

    def flush(self, shadow_id: str | None = None) -> int:
        """Flush buffered predictions to disk.

        Args:
            shadow_id: If provided, only flush this shadow's buffer. Otherwise flush all.

        Returns:
            Number of records flushed.
        """
        with self._lock:
            shadow_ids = [shadow_id] if shadow_id is not None else list(self._buffer.keys())

            total = 0
            for sid in shadow_ids:
                if sid not in self._buffer:
                    continue
                for asset, records in list(self._buffer[sid].items()):
                    if not records:
                        continue
                    df = pd.DataFrame(records)
                    self._write_parquet(sid, asset, df)
                    total += len(records)
                    self._buffer[sid][asset].clear()

                if sid in self._buffer:
                    self._cycle_count[sid] = 0

            if total > 0:
                logger.debug("Flushed %d shadow comparison records", total)

            return total

    def _write_parquet(self, shadow_id: str, asset: str, df: pd.DataFrame) -> None:
        """Write a DataFrame to parquet, partitioned by shadow_id/asset/date."""
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        out_dir = self._base / shadow_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{asset}_{today}.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            df = pd.concat([existing, df], ignore_index=True)

        df.to_parquet(path, index=False)

    def should_flush(self, shadow_id: str) -> bool:
        """Check if a shadow has accumulated enough cycles to flush."""
        return self._cycle_count.get(shadow_id, 0) >= self._flush_interval

    def aggregate_comparison(self, shadow_id: str, lookback_days: int = 60) -> dict[str, Any]:
        """Compute aggregate comparison metrics for a shadow model.

        Returns a dict with signal_agreement_pct, mean_confidence_delta, etc.
        """
        shadow_dir = self._base / shadow_id
        if not shadow_dir.exists():
            return {"status": "no_data", "n_cycles": 0}

        all_records = []
        for pq in sorted(shadow_dir.glob("*.parquet")):
            try:
                all_records.append(pd.read_parquet(pq))
            except (OSError, ValueError):
                continue

        if not all_records:
            return {"status": "no_data", "n_cycles": 0}

        df = pd.concat(all_records, ignore_index=True)
        cutoff = time.time() - lookback_days * 86400
        df = df[df["timestamp"] >= cutoff]

        if df.empty:
            return {"status": "stale", "n_cycles": 0}

        return {
            "status": "ok",
            "shadow_id": shadow_id,
            "n_cycles": len(df),
            "n_assets": df["prod_signal"].nunique() if "prod_signal" in df.columns else 0,
            "signal_agreement_pct": round(float(df["signal_agreement"].mean()) * 100, 2),
            "mean_confidence_delta": round(float(df["confidence_delta"].mean()), 6),
            "mean_p_long_delta": round(float(df["p_long_delta"].mean()), 6),
            "prod_sharpe": None,  # populated by backtest_pnl from stored parquets
            "shadow_sharpe": None,
        }
