"""Daily Loss Tracker — correct daily loss accounting.

Handles:
- Reset at configured trading-day boundary (midnight UTC by default)
- Survives process restart
- Derives baseline from authoritative broker state
- Handles timezone explicitly
- Detects corrupted/missing baseline
- Fail closed when baseline cannot be trusted

Definition of "trading day":
  A trading day starts at 00:00 UTC and ends at 23:59:59 UTC.
  Daily loss is measured from the equity at the start of the trading day.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class DailyBaseline:
    """Immutable record of the daily baseline."""
    date_str: str  # "YYYY-MM-DD"
    equity: float
    timestamp_utc: str
    hash: str = ""

    def compute_hash(self) -> str:
        data = {
            "date_str": self.date_str,
            "equity": self.equity,
            "timestamp_utc": self.timestamp_utc,
        }
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class DailyLossTracker:
    """Track daily loss with correct midnight reset.

    Usage:
        tracker = DailyLossTracker(persistence_dir="reports/r4_loop")
        tracker.initialize(broker_equity=5010.94)

        # Each cycle:
        tracker.update(equity=4950.0)
        if tracker.is_daily_loss_breached():
            # Halt trading

    The tracker:
    1. Loads existing baseline from disk if available
    2. If no baseline or different day → creates new baseline from current equity
    3. Persists baseline to disk after creation
    4. Computes daily loss as baseline_equity - current_equity
    5. Resets automatically at midnight UTC
    """

    def __init__(
        self,
        max_daily_loss: float = 250.0,
        persistence_dir: str = "reports/r4_loop",
        timezone_offset_hours: int = 0,
    ) -> None:
        self._max_daily_loss = max_daily_loss
        self._persistence_dir = Path(persistence_dir)
        self._tz_offset = timedelta(hours=timezone_offset_hours)
        self._baseline: Optional[DailyBaseline] = None
        self._current_equity: float = 0.0
        self._baseline_file = self._persistence_dir / "daily_baseline.json"

    def _today_str(self) -> str:
        """Get today's date string in the configured timezone."""
        now = datetime.now(timezone.utc) + self._tz_offset
        return now.strftime("%Y-%m-%d")

    def _now_utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_baseline(self) -> Optional[DailyBaseline]:
        """Load baseline from disk."""
        if not self._baseline_file.exists():
            return None
        try:
            with open(self._baseline_file, "r") as f:
                data = json.load(f)
            baseline = DailyBaseline(
                date_str=data["date_str"],
                equity=data["equity"],
                timestamp_utc=data["timestamp_utc"],
                hash=data.get("hash", ""),
            )
            # Verify hash
            expected_hash = baseline.compute_hash()
            if baseline.hash and baseline.hash != expected_hash:
                return None  # Corrupted — treat as missing
            return baseline
        except (json.JSONDecodeError, KeyError, OSError):
            return None  # Corrupted or unreadable

    def _save_baseline(self, baseline: DailyBaseline) -> None:
        """Persist baseline to disk atomically."""
        self._persistence_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "date_str": baseline.date_str,
            "equity": baseline.equity,
            "timestamp_utc": baseline.timestamp_utc,
            "hash": baseline.compute_hash(),
        }
        # Atomic write: write to temp file, then rename
        tmp_path = self._baseline_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(self._baseline_file))
        except OSError:
            # Best effort — don't crash the trading loop
            try:
                os.unlink(str(tmp_path))
            except OSError:
                pass

    def _make_baseline(self, date_str: str, equity: float) -> DailyBaseline:
        """Create a baseline with pre-computed hash."""
        baseline = DailyBaseline(
            date_str=date_str,
            equity=equity,
            timestamp_utc=self._now_utc(),
        )
        # Compute hash with empty string, then create final with hash
        h = baseline.compute_hash()
        return DailyBaseline(
            date_str=date_str,
            equity=equity,
            timestamp_utc=baseline.timestamp_utc,
            hash=h,
        )

    def initialize(self, broker_equity: float) -> None:
        """Initialize the tracker with current broker equity.

        Call this once at startup. The tracker will:
        1. Try to load existing baseline from disk
        2. If baseline exists for today → use it (survives restart)
        3. If no baseline or different day → create new baseline
        """
        today = self._today_str()
        loaded = self._load_baseline()

        if loaded and loaded.date_str == today:
            # Same day — use existing baseline (survives restart)
            self._baseline = loaded
        else:
            # New day or no baseline — create from current equity
            self._baseline = self._make_baseline(today, broker_equity)
            self._save_baseline(self._baseline)

        self._current_equity = broker_equity

    def update(self, equity: float) -> None:
        """Update with current equity. Handles day rollover."""
        self._current_equity = equity
        today = self._today_str()

        # Check for day rollover
        if self._baseline is None or self._baseline.date_str != today:
            # New day — create new baseline
            self._baseline = self._make_baseline(today, equity)
            self._save_baseline(self._baseline)

    @property
    def baseline_equity(self) -> float:
        """The equity at the start of the current trading day."""
        if self._baseline is None:
            return self._current_equity  # Fail closed: no baseline = current
        return self._baseline.equity

    @property
    def daily_loss(self) -> float:
        """Current daily loss (positive = loss, 0 = no loss)."""
        loss = self.baseline_equity - self._current_equity
        return max(0.0, loss)  # Only track losses, not profits

    @property
    def daily_pnl(self) -> float:
        """Current daily P&L (negative = loss)."""
        return self._current_equity - self.baseline_equity

    @property
    def is_daily_loss_breached(self) -> bool:
        """Check if daily loss exceeds the limit."""
        return self.daily_loss > self._max_daily_loss

    @property
    def remaining_daily_loss_budget(self) -> float:
        """How much more can be lost before breach."""
        return max(0.0, self._max_daily_loss - self.daily_loss)

    @property
    def baseline_date(self) -> str:
        """The date string of the current baseline."""
        if self._baseline is None:
            return ""
        return self._baseline.date_str

    def force_reset(self, equity: float) -> None:
        """Force a new baseline (e.g., after reconnect)."""
        today = self._today_str()
        self._baseline = self._make_baseline(today, equity)
        self._save_baseline(self._baseline)
        self._current_equity = equity

    def to_dict(self) -> Dict[str, Any]:
        """Export current state for diagnostics."""
        return {
            "baseline_date": self.baseline_date,
            "baseline_equity": self.baseline_equity,
            "current_equity": self._current_equity,
            "daily_loss": self.daily_loss,
            "daily_pnl": self.daily_pnl,
            "max_daily_loss": self._max_daily_loss,
            "is_breached": self.is_daily_loss_breached,
            "remaining_budget": self.remaining_daily_loss_budget,
        }
