"""Phase 0 — Data augmentation: session, hour, day-of-week, month tagging.

Augments every trade record with temporal metadata derived from entry_date/exit_date.
All subsequent phases import from here rather than re-deriving.
"""

from __future__ import annotations

# Portfolio config (shared across phases)
PORTFOLIO_ASSETS: dict[str, str] = {
    "GC": "GC=F",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "GBPCAD": "GBPCAD=X",
    "NZDCAD": "NZDCAD=X",
    "NZDUSD": "NZDUSD=X",
    "GBPAUD": "GBPAUD=X",
    "NZDCHF": "NZDCHF=X",
    "CADCHF": "CADCHF=X",
    "AUDUSD": "AUDUSD=X",
    "EURCHF": "EURCHF=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPCHF": "GBPCHF=X",
    "GBPUSD": "GBPUSD=X",
    "EURAUD": "EURAUD=X",
}

TP_SL: dict[str, tuple[float, float]] = {
    "GC": (4.0, 1.0), "USDCHF": (3.0, 0.85), "USDCAD": (3.9, 1.30),
    "GBPCAD": (4.34, 1.45), "NZDCAD": (5.48, 1.83), "NZDUSD": (3.87, 1.29),
    "GBPAUD": (3.0, 1.0), "NZDCHF": (4.0, 1.0), "CADCHF": (4.0, 1.0),
    "AUDUSD": (4.24, 1.41), "EURCHF": (3.0, 1.0), "EURCAD": (2.12, 0.71),
    "EURNZD": (3.36, 1.12), "GBPCHF": (2.45, 0.82), "GBPUSD": (2.22, 0.50),
    "EURAUD": (3.28, 1.0),
}

SELL_ONLY_ASSETS: frozenset[str] = frozenset({"CADCHF", "NZDCHF", "EURAUD"})

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.audit.phase_data")

# FX market session boundaries (UTC hours)
# Sydney: 21:00-06:00 UTC (winter: 22:00-07:00)
# Tokyo: 00:00-09:00 UTC
# London: 07:00-16:00 UTC
# New York: 12:00-21:00 UTC
SESSION_DEFS: dict[str, tuple[list[int], str]] = {
    "sydney": ([21, 22, 23, 0, 1, 2, 3, 4, 5], "21:00-06:00 UTC"),
    "tokyo": ([0, 1, 2, 3, 4, 5, 6, 7, 8], "00:00-09:00 UTC"),
    "london": ([7, 8, 9, 10, 11, 12, 13, 14, 15], "07:00-16:00 UTC"),
    "new_york": ([12, 13, 14, 15, 16, 17, 18, 19, 20], "12:00-21:00 UTC"),
}

SESSION_OVERLAP_DEFS: dict[str, tuple[list[int], str]] = {
    "sydney_tokyo": ([0, 1, 2, 3, 4, 5], "00:00-06:00 UTC"),
    "london_ny": ([12, 13, 14, 15], "12:00-16:00 UTC"),
    "tokyo_london": ([7, 8], "07:00-09:00 UTC"),
    "ny_close": ([20, 21, 22, 23], "20:00-24:00 UTC"),
}

SESSION_ORDER = [
    "sydney", "tokyo", "london", "new_york",
    "sydney_tokyo", "tokyo_london", "london_ny", "ny_close",
]


def get_session(hour: int) -> str:
    """Classify a UTC hour into the dominant trading session.

    Priority: overlap > single session. Closest closed market wins.
    """
    for s, (hours, _) in SESSION_DEFS.items():
        if hour in hours:
            return s
    return "off_hours"


def get_session_overlap(hour: int) -> str:
    """Return the overlap session name if hour falls in one, else base session."""
    for s, (hours, _) in SESSION_OVERLAP_DEFS.items():
        if hour in hours:
            return s
    return get_session(hour)


def get_day_of_week(dt: datetime) -> str:
    return dt.strftime("%A")


def get_week_of_month(dt: datetime) -> int:
    return (dt.day - 1) // 7 + 1


def get_month(dt: datetime) -> str:
    return dt.strftime("%B")


def get_month_num(dt: datetime) -> int:
    return dt.month


class TradeAugmenter:
    """Augments trade records with temporal metadata.

    Attaches session, hour, day-of-week, week-of-month, month to each trade.
    Works with both the walk-forward reconstructed trades and live trades.
    """

    def __init__(self, trades_map: dict[str, list[dict[str, Any]]]):
        self._trades_map = trades_map
        self._augmented: dict[str, list[dict[str, Any]]] | None = None

    def augment(self) -> dict[str, list[dict[str, Any]]]:
        """Return trades_map copy with temporal fields added to each trade dict."""
        result: dict[str, list[dict[str, Any]]] = {}
        for asset, trades in self._trades_map.items():
            result[asset] = [self._augment_single(t) for t in trades]
        self._augmented = result
        return result

    def _augment_single(self, t: dict[str, Any]) -> dict[str, Any]:
        t = dict(t)

        entry_raw = t.get("entry_date")
        if entry_raw is None:
            return self._add_null_temporal(t)

        try:
            if isinstance(entry_raw, pd.Timestamp):
                entry_dt = entry_raw.to_pydatetime()
            elif isinstance(entry_raw, str):
                entry_dt = datetime.fromisoformat(str(entry_raw).replace("Z", "+00:00").split("+")[0])
            else:
                entry_dt = entry_raw
        except (ValueError, TypeError):
            return self._add_null_temporal(t)

        try:
            t["entry_hour_utc"] = entry_dt.hour
            t["entry_session"] = get_session(entry_dt.hour)
            t["entry_session_overlap"] = get_session_overlap(entry_dt.hour)
            t["entry_dow"] = get_day_of_week(entry_dt)
            t["entry_dow_num"] = entry_dt.weekday()
            t["entry_week_of_month"] = get_week_of_month(entry_dt)
            t["entry_month"] = get_month(entry_dt)
            t["entry_month_num"] = get_month_num(entry_dt)
            t["entry_year"] = entry_dt.year
            t["entry_quarter"] = (entry_dt.month - 1) // 3 + 1
        except Exception:
            return self._add_null_temporal(t)

        exit_raw = t.get("exit_date")
        if exit_raw is not None:
            try:
                if isinstance(exit_raw, pd.Timestamp):
                    exit_dt = exit_raw.to_pydatetime()
                elif isinstance(exit_raw, str):
                    exit_dt = datetime.fromisoformat(str(exit_raw).replace("Z", "+00:00").split("+")[0])
                else:
                    exit_dt = exit_raw
                t["exit_hour_utc"] = exit_dt.hour
                t["exit_session"] = get_session(exit_dt.hour)
                t["exit_dow"] = get_day_of_week(exit_dt)
            except (ValueError, TypeError):
                pass

        return t

    def _add_null_temporal(self, t: dict[str, Any]) -> dict[str, Any]:
        nulls = {
            "entry_hour_utc": -1, "entry_session": "unknown",
            "entry_session_overlap": "unknown", "entry_dow": "unknown",
            "entry_dow_num": -1, "entry_week_of_month": 0,
            "entry_month": "unknown", "entry_month_num": 0,
            "entry_year": 0, "entry_quarter": 0,
        }
        t.update(nulls)
        return t

    def validate(self) -> dict[str, Any]:
        if self._augmented is None:
            return {"error": "not augmented yet"}
        total = 0
        unknown = 0
        for asset, trades in self._augmented.items():
            for t in trades:
                total += 1
                if t.get("entry_session") == "unknown":
                    unknown += 1
        return {"total_trades": total, "unknown_session": unknown, "ok": unknown == 0}


def load_and_augment(path: str = "data/processed/trade_lifecycle_results.json") -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """Load the trade lifecycle results and augment with temporal data.

    Returns (augmented_trades_map, phases_data).
    """
    import json
    with open(path) as f:
        data = json.load(f)

    trades_map = data.get("_trades", {})
    phases = data.get("phases", {})
    summary = data.get("summary", {})

    augmenter = TradeAugmenter(trades_map)
    aug = augmenter.augment()
    val = augmenter.validate()
    logger.info("Loaded %d trades across %d assets — validation: %s",
                len([t for ts in aug.values() for t in ts]),
                len(aug), "OK" if val.get("ok") else f"{val.get('unknown_session')} unknowns")
    return aug, phases
