"""Lifecycle telemetry — profit protection observability.

Aggregates profit floor protection events into live metrics
available at ``/lifecycle.json``.

Usage::

    from paper_trading.lifecycle.telemetry import capture_trigger, capture_exit

    capture_trigger(...)  # called on profit_floor_triggered
    capture_exit(...)     # called on profit_floor_exit

Designed as monitoring-only — no feedback into the trading loop.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

logger = logging.getLogger("eigencapital.lifecycle.telemetry")

_LOCK = threading.Lock()
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LIFECYCLE_PATH = _PROJECT_ROOT / "data" / "live" / "lifecycle.json"


LIFECYCLE_VERSION = "v2_profit_floor"

@dataclass
class ProtectionRecord:
    trade_id: str
    asset: str
    trigger_mfe_r: float
    trigger_price: float
    entry_price: float
    trigger_timestamp: str
    exit_r: float | None = None
    exit_reason: str | None = None
    exit_timestamp: str | None = None
    lifecycle_version: str = LIFECYCLE_VERSION


_records: list[ProtectionRecord] = []
_next_seq = 0
_WRITE_QUEUED = False


def capture_trigger(
    trade_id: str,
    asset: str,
    trigger_mfe_r: float,
    trigger_price: float,
    entry_price: float,
    trigger_timestamp: str,
) -> None:
    global _next_seq
    with _LOCK:
        _next_seq += 1
        _records.append(ProtectionRecord(
            trade_id=trade_id,
            asset=asset,
            trigger_mfe_r=trigger_mfe_r,
            trigger_price=trigger_price,
            entry_price=entry_price,
            trigger_timestamp=trigger_timestamp,
        ))
        _queue_write()


def capture_exit(
    trade_id: str,
    exit_r: float,
    exit_reason: str,
    exit_timestamp: str,
) -> None:
    with _LOCK:
        for rec in _records:
            if rec.trade_id == trade_id and rec.exit_r is None:
                rec.exit_r = exit_r
                rec.exit_reason = exit_reason
                rec.exit_timestamp = exit_timestamp
                break
        _queue_write()


def _queue_write() -> None:
    global _WRITE_QUEUED
    if not _WRITE_QUEUED:
        _WRITE_QUEUED = True
        import threading as _t
        _t.Thread(target=_write_snapshot, daemon=True).start()


def _write_snapshot() -> None:
    global _WRITE_QUEUED
    try:
        snapshot = compute_snapshot()
        _LIFECYCLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LIFECYCLE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(snapshot, f, indent=2)
        tmp.replace(_LIFECYCLE_PATH)
    except (OSError, ValueError, TypeError) as e:
        logger.exception("Failed to write lifecycle snapshot: %s", e)
    finally:
        with _LOCK:
            _WRITE_QUEUED = False


def compute_snapshot() -> dict:
    with _LOCK:
        total = len(_records)
        if total == 0:
            return {"profit_protection": {"enabled": True, "records_available": 0}}

        exited = [r for r in _records if r.exit_r is not None]
        floor_exits = [r for r in exited if r.exit_reason == "PROFIT_LOCK"]
        continues = [r for r in exited if r.exit_reason != "PROFIT_LOCK"]

        act_mfes = [r.trigger_mfe_r for r in _records]
        exit_rs = [r.exit_r for r in exited]

        floor_exit_rs = [r.exit_r for r in floor_exits]
        continue_rs = [r.exit_r for r in continues]

        import statistics

        avg_activation_mfe = statistics.mean(act_mfes) if act_mfes else 0.0
        med_activation_mfe = statistics.median(act_mfes) if act_mfes else 0.0
        avg_exit_r = statistics.mean(exit_rs) if exit_rs else 0.0

        # PPCR per trade then aggregate
        pprs = []
        for r in exited:
            if r.trigger_mfe_r > 0:
                pprs.append(r.exit_r / r.trigger_mfe_r)
        avg_ppcr = statistics.mean(pprs) if pprs else 0.0
        med_ppcr = statistics.median(pprs) if pprs else 0.0

        # Profit saved: for floor exits, how much did we save vs baseline (which would have been lower)
        # For non-exited records, we can't compute saved yet
        profit_saved = []
        for r in floor_exits:
            saved = r.exit_r - 0.0  # placeholder — baseline unknown; use lower bound
            profit_saved.append(saved)
        avg_profit_saved = statistics.mean(profit_saved) if profit_saved else 0.0

        return {
            "profit_protection": {
                "enabled": True,
                "lifecycle_version": LIFECYCLE_VERSION,
                "records_available": total,
                "activation_count": total,
                "activation_rate": round(total / max(total, 1) * 100, 1),
                "floor_exit_count": len(floor_exits),
                "floor_exit_rate": round(len(floor_exits) / max(len(exited), 1) * 100, 1) if exited else 0.0,
                "continue_count": len(continues),
                "continue_rate": round(len(continues) / max(len(exited), 1) * 100, 1) if exited else 0.0,
                "avg_activation_mfe_r": round(avg_activation_mfe, 2),
                "median_activation_mfe_r": round(med_activation_mfe, 2),
                "avg_exit_r_after_protection": round(avg_exit_r, 2),
                "protected_profit_capture_ratio": round(avg_ppcr, 2),
                "median_protected_profit_capture_ratio": round(med_ppcr, 2),
                "avg_profit_saved_r": round(avg_profit_saved, 2),
                "tail_preservation": {
                    "status": "tracking",
                },
            }
        }
