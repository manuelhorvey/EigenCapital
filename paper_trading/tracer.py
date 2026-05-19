import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

TRACE_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "live", "trace.jsonl"
)

_lock = threading.Lock()
_logger = logging.getLogger("quantforge.tracer")


def _append(line: dict) -> None:
    try:
        os.makedirs(os.path.dirname(TRACE_LOG_PATH), exist_ok=True)
        with _lock:
            with open(TRACE_LOG_PATH, "a") as f:
                f.write(json.dumps(line, default=str) + "\n")
    except Exception:
        pass


def trace_decision(
    asset: str,
    features: dict,
    proba: list,
    threshold: float,
    signal: str,
    confidence: float,
    pos_size: float,
    close_price: float,
    current_side: Optional[str],
    halt_flags: dict,
) -> None:
    _append({
        "event": "decision",
        "timestamp": datetime.utcnow().isoformat(),
        "asset": asset,
        "features_sample": features,
        "proba_short": round(proba[0], 6),
        "proba_neutral": round(proba[1], 6),
        "proba_long": round(proba[2], 6),
        "threshold": threshold,
        "signal": signal,
        "confidence_pct": confidence,
        "position_size": pos_size,
        "close_price": close_price,
        "current_position_side": current_side,
        "halted": halt_flags.get("halted", False),
        "halt_reasons": halt_flags.get("reasons", []),
    })


def shadow_compare_signal(
    asset: str,
    proba_produced: list,
    wrapper_signal: str,
    wrapper_confidence: float,
    original_signal: str,
    original_confidence: float,
) -> None:
    signal_match = wrapper_signal == original_signal
    conf_tol = abs(wrapper_confidence - original_confidence) < 0.001
    if not signal_match or not conf_tol:
        _append({
            "event": "shadow_mismatch",
            "timestamp": datetime.utcnow().isoformat(),
            "asset": asset,
            "proba": proba_produced,
            "wrapper": {"signal": wrapper_signal, "confidence": wrapper_confidence},
            "original": {"signal": original_signal, "confidence": original_confidence},
        })


def shadow_compare_pnl(
    asset: str,
    wrapper_pnl: float,
    original_pnl: float,
) -> None:
    if abs(wrapper_pnl - original_pnl) > 1e-10:
        _append({
            "event": "shadow_pnl_mismatch",
            "timestamp": datetime.utcnow().isoformat(),
            "asset": asset,
            "wrapper_pnl": wrapper_pnl,
            "original_pnl": original_pnl,
        })


def shadow_compare_sizing(
    asset: str,
    wrapper_size: float,
    original_size: float,
) -> None:
    if abs(wrapper_size - original_size) > 1e-10:
        _append({
            "event": "shadow_sizing_mismatch",
            "timestamp": datetime.utcnow().isoformat(),
            "asset": asset,
            "wrapper_size": wrapper_size,
            "original_size": original_size,
        })
