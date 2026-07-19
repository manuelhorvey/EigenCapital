#!/usr/bin/env python3
"""Clear a stale emergency halt from state.json.

Permanent halts survive process restarts (they are persisted to
data/live/state.json).  This script lets an operator inspect and
clear that state so the engine resumes normal operation.

Safe to run against a live engine (atomically replaces state.json,
no process interaction).  The change takes effect on the next
engine cycle (monitor.py reads state.json at engine init but the
running engine re-writes orchestrator state on every save_state).

Usage::

    PYTHONPATH=$PYTHONPATH:. python tools/reset_halt.py
    PYTHONPATH=$PYTHONPATH:. python tools/reset_halt.py --apply
    PYTHONPATH=$PYTHONPATH:. python tools/reset_halt.py --apply --peak 75000

Without --apply the script prints the current halt state and exits.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("tools.reset_halt")

BASE = str(Path(__file__).resolve().parent.parent)
STATE_PATH = str(Path(BASE) / "data" / "live" / "state.json")


def read_halt_state() -> dict | None:
    """Return the halt-related fields from state.json, or None."""
    if not Path(STATE_PATH).exists():
        logger.error("state.json not found at %s", STATE_PATH)
        return None
    with open(STATE_PATH) as f:
        data = json.load(f)
    return {
        "emergency_halt": data.get("emergency_halt", False),
        "halt_reason": data.get("halt_reason", ""),
        "halt_detail": data.get("halt_detail", ""),
        "peak_portfolio_value": data.get("peak_portfolio_value"),
        "breaker_daily_pnl": data.get("breaker_daily_pnl"),
    }


def clear_halt_in_state(state: dict) -> dict:
    """Return state.json body with halt fields cleared."""
    state["emergency_halt"] = False
    state["halt_reason"] = ""
    state["halt_detail"] = ""
    return state


def update_peak(state: dict, new_peak: float | None) -> dict:
    """Optionally re-anchor the peak portfolio value."""
    if new_peak is not None and new_peak > 0:
        state["peak_portfolio_value"] = new_peak
    return state


def do_apply(state: dict) -> None:
    """Atomically write the modified state back to state.json."""
    from paper_trading.state import atomic_write_json

    atomic_write_json(STATE_PATH, state)
    logger.info("state.json written — halt cleared; next engine cycle will read the new state")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and clear a stale emergency halt from state.json")
    parser.add_argument("--apply", action="store_true", help="Apply the reset (default is dry-run)")
    parser.add_argument("--peak", type=float, default=None, help="Optional new peak_portfolio_value")
    args = parser.parse_args()

    halt = read_halt_state()
    if halt is None:
        sys.exit(1)

    logger.info(
        "Current halt state: emergency_halt=%s reason=%s detail=%s peak=%s",
        halt["emergency_halt"],
        halt["halt_reason"] or "(empty)",
        halt["halt_detail"] or "(empty)",
        f"{halt['peak_portfolio_value']:.2f}" if halt["peak_portfolio_value"] is not None else "None",
    )

    if not halt["emergency_halt"]:
        logger.info("No emergency halt active — nothing to clear.")
        return

    if not args.apply:
        logger.info(
            "Dry-run mode. Use --apply to clear the halt%s.",
            " and re-anchor peak" if args.peak is not None else "",
        )
        return

    with open(STATE_PATH) as f:
        state = json.load(f)

    state = clear_halt_in_state(state)
    state = update_peak(state, args.peak)
    do_apply(state)

    logger.info(
        "Emergency halt cleared. Check engine.log after the next monitor.py cycle "
        "to confirm the engine resumes normal operation."
    )


if __name__ == "__main__":
    main()
