#!/usr/bin/env python3
"""Live validation suite — cross-reference state.json, SQLite, and config.

Reads the live engine state, trade history, and configuration to surface
actionable operator warnings. Designed to run from cron or an operator
console.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/live_validation.py
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/live_validation.py --json  # machine-readable
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/live_validation.py --path /custom/state.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("eigencapital.live_validation")

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = BASE_DIR / "data" / "live" / "state.json"

# ── Check result types ────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS" | "WARN" | "ERROR"
    message: str
    details: dict = field(default_factory=dict)


# ── Validator registry ────────────────────────────────────────────────────

_VALIDATORS: list[Callable] = []


def validator(fn: Callable) -> Callable:
    """Decorator to register a validation check."""
    _VALIDATORS.append(fn)
    return fn


# ── Individual checks ─────────────────────────────────────────────────────


@validator
def check_engine_status(state: dict) -> CheckResult:
    """Verify the engine is alive and recent."""
    eng = state.get("engine_status", {})
    last_update = eng.get("last_update")
    market_closed = eng.get("market_closed", False)

    if not eng.get("initialized"):
        return CheckResult("engine_initialized", "ERROR", "Engine reports not initialized")

    if not last_update:
        return CheckResult("engine_last_update", "ERROR", "No last_update timestamp in engine_status")

    # Check staleness (ignore if market is closed)
    try:
        last_dt = datetime.fromisoformat(last_update)
        # Make naive datetimes timezone-aware (assume UTC)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc).astimezone() - last_dt).total_seconds()
        if age_seconds > 300 and not market_closed:  # 5 minutes
            return CheckResult("engine_staleness", "WARN", f"Last update {age_seconds:.0f}s ago (threshold: 300s)")
    except (ValueError, TypeError):
        return CheckResult("engine_staleness", "WARN", f"Cannot parse last_update: {last_update!r}")

    return CheckResult("engine_status", "PASS", "Engine is alive")


@validator
def check_emergency_halt(state: dict) -> CheckResult:
    """Check if the engine is in an emergency halt."""
    eng = state.get("engine_status", {})
    halt = eng.get("emergency_halt", False)
    reason = eng.get("halt_reason", "")
    if halt:
        return CheckResult(
            "emergency_halt",
            "ERROR",
            f"Engine is halted: {reason}",
            {"halt_reason": reason, "halt_detail": eng.get("halt_detail", "")},
        )
    return CheckResult("emergency_halt", "PASS", "No emergency halt")


@validator
def check_portfolio_drawdown(state: dict) -> CheckResult:
    """Check portfolio drawdown against config thresholds."""
    portfolio = state.get("portfolio", {})
    dd = portfolio.get("portfolio_drawdown", 0.0)
    dd_pct = dd * 100  # Convert from fraction to percent
    halt_conditions = state.get("halt_conditions", {})
    max_dd = halt_conditions.get("max_drawdown_pct", 0.15) * 100

    if dd_pct < -max_dd:
        return CheckResult(
            "drawdown",
            "ERROR",
            f"Drawdown {dd_pct:.2f}% exceeds limit {max_dd:.2f}%",
            {"drawdown_pct": round(dd_pct, 2), "max_drawdown_pct": max_dd},
        )
    if dd_pct < -max_dd * 0.7:
        return CheckResult(
            "drawdown",
            "WARN",
            f"Drawdown {dd_pct:.2f}% approaching limit (-{max_dd:.1f}%)",
            {"drawdown_pct": round(dd_pct, 2), "max_drawdown_pct": max_dd},
        )
    return CheckResult("drawdown", "PASS", f"Drawdown {dd_pct:.2f}% within limits")


@validator
def check_position_concentration(state: dict) -> CheckResult:
    """Check net-short skew against concentration threshold."""
    portfolio = state.get("portfolio", {})
    pc = portfolio.get("position_concentration", {})
    skew = pc.get("skew", 0.0)
    threshold = pc.get("threshold", 0.75)
    alert = pc.get("alert", False)

    if alert:
        dominant = pc.get("dominant_side", "unknown")
        return CheckResult(
            "position_concentration",
            "WARN",
            f"Skew {skew:.1%} ({dominant}-heavy) exceeds threshold {threshold:.0%}",
            {"skew": skew, "threshold": threshold, "dominant_side": dominant},
        )
    return CheckResult("position_concentration", "PASS", f"Skew {skew:.1%} within threshold {threshold:.0%}")


@validator
def check_sell_tripwires(state: dict) -> CheckResult:
    """Check for tripped SELL tripwires on sell-only assets."""
    assets = state.get("assets", {})
    tripped: list[str] = []
    for name, adata in assets.items():
        if adata.get("sell_only") and adata.get("tripwire_active"):
            tripped.append(name)
    if tripped:
        return CheckResult(
            "sell_tripwire",
            "WARN",
            f"Tripwire active on: {', '.join(tripped)}",
            {"tripped_assets": tripped},
        )
    return CheckResult("sell_tripwire", "PASS", "No SELL tripwires tripped")


@validator
def check_mt5_connectivity(state: dict) -> CheckResult:
    """Check MT5 bridge connection status."""
    eng = state.get("engine_status", {})
    mt5 = eng.get("mt5_status", {})
    is_connected = mt5.get("connected", False)
    status_str = mt5.get("status", "UNKNOWN")

    if is_connected:
        return CheckResult("mt5_connectivity", "PASS", f"MT5 connected (status: {status_str})")
    return CheckResult("mt5_connectivity", "WARN", f"MT5 disconnected (status: {status_str})")


@validator
def check_calibration(state: dict) -> CheckResult:
    """Check confidence calibration confidence vs win rate for watch assets."""
    assets = state.get("assets", {})
    watch_assets = {"NZDCAD", "NZDUSD"}
    calibration_issues: list[str] = []

    for name in watch_assets:
        adata = assets.get(name, {})
        metrics = adata.get("metrics", {})
        n_trades = metrics.get("n_trades", 0)
        if n_trades >= 20:
            mean_conf = metrics.get("mean_confidence", 0) or 0
            win_rate = metrics.get("win_rate", 0) or 0
            gap = mean_conf - win_rate
            if gap >= 15:
                calibration_issues.append(
                    f"{name}: conf={mean_conf:.0f}% vs wr={win_rate:.0f}% (gap={gap:.0f}pp, N={n_trades})"
                )

    if calibration_issues:
        return CheckResult(
            "calibration",
            "WARN",
            f"Calibration overconfidence detected: {'; '.join(calibration_issues)}",
            {"issues": calibration_issues},
        )
    return CheckResult("calibration", "PASS", "Calibration within expected bounds")


@validator
def check_concurrent_position_limit(state: dict) -> CheckResult:
    """Check open positions against max_concurrent setting."""
    portfolio = state.get("portfolio", {})
    open_positions = portfolio.get("open_positions", 0)
    halt_conditions = state.get("halt_conditions", {})
    max_pos = halt_conditions.get("max_concurrent_positions", 13)
    if open_positions >= max_pos:
        return CheckResult(
            "concurrent_positions",
            "WARN",
            f"{open_positions}/{max_pos} positions open (at capacity)",
            {"open_positions": open_positions, "max_positions": max_pos},
        )
    pct = open_positions / max_pos * 100 if max_pos > 0 else 0
    if pct > 80:
        return CheckResult(
            "concurrent_positions",
            "INFO",
            f"{open_positions}/{max_pos} positions open ({pct:.0f}%)",
            {"open_positions": open_positions, "max_positions": max_pos},
        )
    return CheckResult("concurrent_positions", "PASS", f"{open_positions}/{max_pos} positions open")


@validator
def check_asset_gate_overrides(state: dict) -> CheckResult:
    """Check for assets with high gate override rates."""
    assets = state.get("assets", {})
    overridden: list[str] = []
    for name, adata in assets.items():
        if adata.get("gate_override"):
            overridden.append(name)

    if len(overridden) > len(assets) * 0.4:
        return CheckResult(
            "gate_overrides",
            "WARN",
            f"{len(overridden)}/{len(assets)} assets gate-overridden (>{40:.0f}%)",
            {"overridden_assets": overridden, "count": len(overridden), "total": len(assets)},
        )
    if overridden:
        return CheckResult(
            "gate_overrides",
            "INFO",
            f"{len(overridden)} asset(s) gate-overridden: {', '.join(overridden)}",
        )
    return CheckResult("gate_overrides", "PASS", "No gate overrides")


@validator
def check_signal_flips(state: dict) -> CheckResult:
    """Check for frequent signal flips."""
    assets = state.get("assets", {})
    flips = sum(1 for adata in assets.values() if adata.get("signal_flip"))
    if flips > 3:
        return CheckResult(
            "signal_flips",
            "WARN",
            f"{flips} assets with signal flip (threshold: 3)",
            {"flip_count": flips},
        )
    return CheckResult("signal_flips", "PASS", f"{flips} signal flips within limit")


@validator
def check_live_sharpe(state: dict) -> CheckResult:
    """Check live Sharpe ratio if available."""
    portfolio = state.get("portfolio", {})
    sharpe = portfolio.get("live_sharpe", {})
    if not sharpe.get("available"):
        return CheckResult("live_sharpe", "INFO", "Live Sharpe not yet available (insufficient data)")
    cycle_sharpe = sharpe.get("cycle_sharpe_adj")
    if cycle_sharpe is not None and cycle_sharpe < 0:
        return CheckResult("live_sharpe", "WARN", f"Live cycle-level Sharpe is negative: {cycle_sharpe:.2f}")
    return CheckResult("live_sharpe", "PASS", f"Live Sharpe: {cycle_sharpe:.2f}" if cycle_sharpe else "Tracking")


# ── Runner ────────────────────────────────────────────────────────────────


def load_state(path: str | Path) -> dict:
    """Load state.json from the given path."""
    path = Path(path)
    if not path.exists():
        logger.warning("State file not found: %s", path)
        return {}
    with open(path) as f:
        return json.load(f)


def run(state: dict) -> list[CheckResult]:
    """Run all registered validation checks against the state dict."""
    results: list[CheckResult] = []
    for fn in _VALIDATORS:
        try:
            result = fn(state)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 — validation runner must not fail on one bad check
            results.append(CheckResult(fn.__name__, "ERROR", f"Check raised exception: {exc}"))
    return results


def print_human(results: list[CheckResult]) -> None:
    """Print a human-readable validation summary."""
    status_counts = {"PASS": 0, "WARN": 0, "ERROR": 0, "INFO": 0}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    print(f"\n{'=' * 60}")
    print(f"  EigenCapital Live Validation   [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"{'=' * 60}")
    print(
        f"  {status_counts.get('PASS', 0):>3} passed  "
        f"{status_counts.get('WARN', 0):>3} warnings  "
        f"{status_counts.get('ERROR', 0):>3} errors  "
        f"{status_counts.get('INFO', 0):>3} info"
    )
    print(f"{'=' * 60}\n")

    for r in results:
        if r.status == "PASS":
            icon, color = "✓", "\033[32m"
            print(f"  {color}{icon} {r.name}\033[0m")
        elif r.status == "INFO":
            icon, color = "ℹ", "\033[36m"
            print(f"  {color}{icon} {r.name}: {r.message}\033[0m")
        elif r.status == "WARN":
            icon, color = "⚠", "\033[33m"
            print(f"  {color}{icon} {r.name}: {r.message}\033[0m")
        elif r.status == "ERROR":
            icon, color = "✗", "\033[31m"
            print(f"  {color}{icon} {r.name}: {r.message}\033[0m")

    print()


def print_json(results: list[CheckResult]) -> None:
    """Print machine-readable JSON output."""
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.status == "PASS"),
            "warnings": sum(1 for r in results if r.status == "WARN"),
            "errors": sum(1 for r in results if r.status == "ERROR"),
            "info": sum(1 for r in results if r.status == "INFO"),
        },
    }
    print(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(description="EigenCapital Live Validation Suite")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    default_path = str(DEFAULT_STATE_PATH)
    parser.add_argument(
        "--path",
        default=default_path,
        help=f"Path to state.json (default: {default_path})",
    )
    args = parser.parse_args()

    state = load_state(args.path)
    if not state:
        print(f"ERROR: Cannot load state from {args.path}. Is the engine running?", file=sys.stderr)
        sys.exit(1)

    results = run(state)
    exit_code = 1 if any(r.status == "ERROR" for r in results) else 0

    if args.json:
        print_json(results)
    else:
        print_human(results)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
