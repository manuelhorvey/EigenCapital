import json
import logging
import os
import threading
from datetime import datetime, timezone

TRACE_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "live", "trace.jsonl"
)

_lock = threading.Lock()
_logger = logging.getLogger("quantforge.tracer")


def _append(line: dict) -> None:
    try:
        os.makedirs(os.path.dirname(TRACE_LOG_PATH), exist_ok=True)
        with _lock, open(TRACE_LOG_PATH, "a") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except OSError as e:
        _logger.error("Trace append failed: %s", e)
    except TypeError as e:
        _logger.warning("Non-serializable trace entry: %s", e)


def trace_decision(
    asset: str,
    features: dict,
    proba: list,
    threshold: float,
    signal: str,
    confidence: float,
    pos_size: float,
    close_price: float,
    current_side: str | None,
    halt_flags: dict,
) -> None:
    _append(
        {
            "event": "decision",
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
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
        }
    )


def trace_diagnostic_report(report: dict) -> None:
    _append({"event": "shadow_diagnostic", **report})


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
        _append(
            {
                "event": "shadow_mismatch",
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "asset": asset,
                "proba": proba_produced,
                "wrapper": {"signal": wrapper_signal, "confidence": wrapper_confidence},
                "original": {"signal": original_signal, "confidence": original_confidence},
            }
        )


def shadow_compare_pnl(
    asset: str,
    wrapper_pnl: float,
    original_pnl: float,
) -> None:
    if abs(wrapper_pnl - original_pnl) > 1e-10:
        _append(
            {
                "event": "shadow_pnl_mismatch",
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "asset": asset,
                "wrapper_pnl": wrapper_pnl,
                "original_pnl": original_pnl,
            }
        )


def shadow_compare_sizing(
    asset: str,
    wrapper_size: float,
    original_size: float,
) -> None:
    if abs(wrapper_size - original_size) > 1e-10:
        _append(
            {
                "event": "shadow_sizing_mismatch",
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "asset": asset,
                "wrapper_size": wrapper_size,
                "original_size": original_size,
            }
        )


def shadow_compare_sltp(
    asset: str,
    label_sl: float,
    label_tp: float,
    runtime_sl: float,
    runtime_tp: float,
    entry_price: float,
    reason: str = "adjustment",
) -> None:
    """Track when runtime SL/TP deviates from the original label barriers."""
    sl_diff_pct = abs(runtime_sl - label_sl) / (entry_price + 1e-9) * 100
    tp_diff_pct = abs(runtime_tp - label_tp) / (entry_price + 1e-9) * 100
    threshold = 0.01  # 1 bp
    if sl_diff_pct > threshold or tp_diff_pct > threshold:
        _append(
            {
                "event": "shadow_sltp_change",
                "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                "asset": asset,
                "entry_price": entry_price,
                "label_sl": label_sl,
                "label_tp": label_tp,
                "runtime_sl": runtime_sl,
                "runtime_tp": runtime_tp,
                "sl_delta_pct": round(sl_diff_pct, 4),
                "tp_delta_pct": round(tp_diff_pct, 4),
                "reason": reason,
            }
        )
