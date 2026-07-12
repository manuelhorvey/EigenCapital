"""State persistence — facade delegating to focused sub-stores in paper_trading.state.

Kept as a re-export layer for backward compatibility.  New code should import
directly from ``paper_trading.state`` (the sub-package) or one of its modules.
"""

import logging
import os

import pandas as pd

from paper_trading.state import (
    CONTRACT_VERSION,  # noqa: F401 — re-export for api/routes.py
    EngineSnapshot,
    _AnalyticsStore,
    _DatabaseStore,
    _DataCache,
    _SnapshotManager,
    sanitize,  # noqa: F401 — re-export for engine.py, tests
)

logger = logging.getLogger("eigencapital.state_store")

_SKIP_JOURNAL = object()


class StateStore:
    """Facade that delegates to DatabaseStore, SnapshotManager, AnalyticsStore, and DataCache."""

    def __init__(self, base_dir: str, snapshot_cache_ttl: float = 1.0):
        self.base_dir = base_dir
        self.live_dir = os.path.join(base_dir, "data", "live")
        self.state_path = os.path.join(self.live_dir, "state.json")
        self.equity_history_path = os.path.join(self.live_dir, "equity_history.json")
        self.review_log_path = os.path.join(self.live_dir, "review_log.json")
        self.trade_outcomes_path = os.path.join(self.live_dir, "trade_outcomes.json")
        self.cache_dir = os.path.join(self.live_dir, "cache")

        db_path = os.path.join(self.live_dir, "state.db")
        os.makedirs(self.live_dir, exist_ok=True)

        self.db = _DatabaseStore(db_path)
        self.snapshot = _SnapshotManager(self.state_path, cache_ttl=snapshot_cache_ttl)
        self.analytics = _AnalyticsStore(
            self.db,
            os.path.join(self.live_dir, "analytics_snapshot.json"),
            self.trade_outcomes_path,
        )
        self.cache = _DataCache(self.cache_dir)

    # ── Snapshot ───────────────────────────────────────────────────

    def save_snapshot(self, snapshot: EngineSnapshot) -> None:
        self.snapshot.save(snapshot)
        self.db.checkpoint_wal()

    def load_snapshot(self) -> EngineSnapshot | None:
        return self.snapshot.load()

    # ── Trades ─────────────────────────────────────────────────────

    def append_trade(self, trade: dict) -> None:
        self.db.append_trade(trade)

    def read_trades(self, limit: int = 10) -> list:
        return self.db.read_trades(limit)

    def read_trades_since(self, date: str) -> pd.DataFrame:
        return self.db.read_trades_since(date)

    def write_trade_outcomes_cache(self) -> None:
        self.analytics.write_trade_outcomes_cache()

    def read_trade_outcomes(self) -> dict | None:
        return self.analytics.read_trade_outcomes()

    # ── Attribution ────────────────────────────────────────────────

    def append_attribution(self, record_dict: dict) -> None:
        self.db.append_attribution(record_dict)

    def read_attribution(
        self,
        limit: int = 100,
        offset: int = 0,
        archetype: str | None = None,
        regime: str | None = None,
        asset: str | None = None,
    ) -> list:
        return self.db.read_attribution(limit, offset, archetype, regime, asset)

    # ── Shadow trades ──────────────────────────────────────────────

    def append_shadow_trade(self, record_dict: dict) -> None:
        self.db.append_shadow_trade(record_dict)

    def read_shadow_trades(self, limit: int = 100, offset: int = 0, alt_label: str | None = None) -> list:
        return self.db.read_shadow_trades(limit, offset, alt_label)

    # ── Analytics ──────────────────────────────────────────────────

    def write_analytics_snapshot(self) -> None:
        self.analytics.write_snapshot()

    def read_analytics_snapshot(self) -> dict | None:
        return self.analytics.read_snapshot()

    # ── Confidence buckets ─────────────────────────────────────────

    def append_confidence_bucket(self, bucket: dict) -> None:
        self.db.append_confidence_bucket(bucket)

    # ── Equity history ─────────────────────────────────────────────

    def append_equity_history(self, record: dict) -> None:
        self.db.append_equity_history(record)

    def read_equity_history(self) -> list:
        return self.db.read_equity_history()

    # ── Raw DB access (for tests / direct queries) ────────────────

    def connect(self):
        """Open a direct SQLite connection. Used by tests."""
        return self.db._create_connection()

    # ── Data cache ─────────────────────────────────────────────────

    def cache_path(self, ticker: str) -> str:
        return self.cache.path_for(ticker)

    def save_cache(self, ticker: str, df: pd.DataFrame) -> None:
        self.cache.save(ticker, df)

    def load_cache(self, ticker: str) -> pd.DataFrame | None:
        return self.cache.load(ticker)
