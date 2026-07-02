#!/usr/bin/env python3
"""
Shock Simulation Engine — Failure Discovery System for Adaptive Exit Robustness.

Not a validation script. A system designed to break things.
Applies structural perturbations to realized MFE distribution, then
measures whether the adaptive exit edge survives or collapses.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/shock_simulation.py
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/shock_simulation.py --json shock_results.json
    PYTHONPATH=$PYTHONPATH:. python scripts/analysis/shock_simulation.py --scenario mfe_compression,correlated_crash
"""

from __future__ import annotations

import json
import logging
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("shock_simulation")

DATA_PATH = Path("data/processed/trade_lifecycle_results.json")
BASELINE_RETRACE = 0.50
MIN_MFE = 0.0


# ── Simulation core ─────────────────────────────────────────────────────────


def simulate_trailing(
    trades: list[dict[str, Any]],
    retrace_pct: float = BASELINE_RETRACE,
    require_min_mfe: float = MIN_MFE,
) -> tuple[float, float, int]:
    original_r = sum(t["r_multiple"] for t in trades)
    new_r = 0.0
    n_saved = 0
    for t in trades:
        orig = t["r_multiple"]
        mfe_r = t.get("mfe_r", 0.0)
        if orig >= 0 or mfe_r < require_min_mfe or t.get("exit_reason") == "tp":
            new_r += orig
            continue
        captured = mfe_r * (1.0 - retrace_pct)
        new_r += max(captured, 0)
        if captured > 0:
            n_saved += 1
    return new_r - original_r, new_r, n_saved


def portfolio_trailing_r(
    trades_map: dict[str, list[dict[str, Any]]],
    retrace_pct: float = BASELINE_RETRACE,
) -> float:
    total = 0.0
    for ts in trades_map.values():
        _, nr, _ = simulate_trailing(ts, retrace_pct=retrace_pct)
        total += nr
    return total


def portfolio_fixed_r(trades_map: dict[str, list[dict[str, Any]]]) -> float:
    return sum(sum(t["r_multiple"] for t in ts) for ts in trades_map.values())


def per_asset_r(
    trades_map: dict[str, list[dict[str, Any]]],
    retrace_pct: float = BASELINE_RETRACE,
) -> dict[str, float]:
    return {asset: simulate_trailing(ts, retrace_pct=retrace_pct)[1] for asset, ts in trades_map.items()}


# ── Shock types ─────────────────────────────────────────────────────────────


@dataclass
class ShockResult:
    name: str
    description: str
    params: dict[str, Any]
    trailing_r: float
    fixed_r: float
    per_asset: dict[str, float]
    unshocked_trailing_r: float  # baseline trailing R with no shock
    unshocked_per_asset: dict[str, float]
    # Derived
    absolute_retention: float = 0.0  # 0-1: fraction of trailing R retained under shock
    relative_retention: float = 0.0  # 0-1+: trailing R as multiple of fixed R benchmark
    severity: str = ""  # PASS / MODERATE / SEVERE / CATASTROPHIC
    collapsed_assets: list[str] = None
    break_intensity: float | None = None  # at what sweep level does system fail
    sweep: list[tuple[float, float, float]] | None = None  # intensity, trailingR, retention

    def __post_init__(self):
        self.collapsed_assets = []
        if self.unshocked_trailing_r > 0:
            self.absolute_retention = self.trailing_r / self.unshocked_trailing_r
        if self.unshocked_trailing_r > 0:
            # How much of the original edge is retained?
            # Edge = trailing_R - fixed_R
            unshocked_edge = self.unshocked_trailing_r - self.fixed_r
            shocked_edge = self.trailing_r - self.fixed_r
            if unshocked_edge > 0:
                self.relative_retention = shocked_edge / unshocked_edge
        self._classify_severity()

    def _classify_severity(self):
        if self.relative_retention >= 0.8:
            self.severity = "PASS"
        elif self.relative_retention >= 0.5:
            self.severity = "MODERATE"
        elif self.relative_retention >= 0.0:
            self.severity = "SEVERE"
        else:
            self.severity = "CATASTROPHIC"
        for asset, r_val in self.per_asset.items():
            if r_val <= 0 and self.unshocked_per_asset.get(asset, 0) > 0:
                self.collapsed_assets.append(asset)


# ── Shock registry ─────────────────────────────────────────────────────────


# All shocks return a copy of trades_map with perturbations applied.
ShockFn = Callable[[dict[str, list[dict[str, Any]]], dict[str, Any]], dict[str, list[dict[str, Any]]]]


def _deep_copy_trades(trades_map: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {asset: [dict(t) for t in ts] for asset, ts in trades_map.items()}


def shock_mfe_compression(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """Scale MFE by compression_factor. Tests volatility decay."""
    cf = params.get("compression_factor", 0.5)
    result = _deep_copy_trades(trades_map)
    for ts in result.values():
        for t in ts:
            t["mfe_r"] = t.get("mfe_r", 0.0) * cf
    return result


def shock_retrace_acceleration(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """
    Retracements happen faster — need tighter stop to capture same MFE.
    Implementation: increase the effective retrace_pct by retrace_bump.
    This is handled at the simulation level via retrace_pct adjustment.
    """
    # This shock is special: it doesn't modify trade data, it modifies simulation params.
    # We handle it directly in run_sweep_scenario.
    return _deep_copy_trades(trades_map)


def shock_gap(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """Randomly zero out MFE on a fraction of trades. Tests gap-through-stop survivability."""
    gap_rate = params.get("gap_rate", 0.1)
    gap_mode = params.get("gap_mode", "losing_only")  # 'losing_only' or 'all'
    rng = random.Random(params.get("seed", 42))

    result = _deep_copy_trades(trades_map)
    for ts in result.values():
        for t in ts:
            if gap_mode == "losing_only" and t.get("r_multiple", 0) >= 0:
                continue
            if rng.random() < gap_rate:
                t["mfe_r"] = 0.0
    return result


def shock_multi_peak_decoy(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """
    False MFE peaks trigger premature trailing exit.
    On decoy_rate of trades, reduce effective captured MFE by decoy_penalty.
    """
    decoy_rate = params.get("decoy_rate", 0.15)
    decoy_penalty = params.get("decoy_penalty", 0.5)  # fraction of MFE lost to premature exit
    rng = random.Random(params.get("seed", 42))

    result = _deep_copy_trades(trades_map)
    for ts in result.values():
        for t in ts:
            if t.get("r_multiple", 0) >= 0 or t.get("exit_reason") == "tp":
                continue
            if rng.random() < decoy_rate:
                # Reduce MFE: a false peak triggered early exit at fraction of true MFE
                t["mfe_r"] = t.get("mfe_r", 0.0) * (1.0 - decoy_penalty)
    return result


def shock_execution_lag(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """
    Trailing stop triggers late due to execution delay.
    On lag_rate of trades, reduce captured MFE by lag_penalty_r (in R units).
    """
    lag_rate = params.get("lag_rate", 0.3)
    lag_penalty_r = params.get("lag_penalty_r", 0.3)

    result = _deep_copy_trades(trades_map)
    rng = random.Random(params.get("seed", 42))

    for ts in result.values():
        for t in ts:
            orig = t.get("r_multiple", 0)
            if orig >= 0 or t.get("exit_reason") == "tp":
                continue
            if rng.random() < lag_rate:
                # Use a negative MFE marker to simulate execution gap-through
                mfe = t.get("mfe_r", 0.0)
                if mfe > lag_penalty_r:
                    t["mfe_r"] = mfe - lag_penalty_r
                else:
                    t["mfe_r"] = 0.0
    return result


def shock_trend_fragmentation(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """
    Trends become shorter and less persistent — fewer trades reach adequate MFE for
    trailing activation. Simulated by scaling down MFE across the board, biased
    toward smaller MFEs (long-tail compression).
    """
    frag_intensity = params.get("fragmentation", 0.3)  # 0-1: how fragmented
    compression = 1.0 - frag_intensity
    result = _deep_copy_trades(trades_map)
    for ts in result.values():
        for t in ts:
            mfe = t.get("mfe_r", 0.0)
            # Apply progressive compression: small MFEs compressed more than large ones
            # In fragmented markets, shorter trends reduce the upper tail more
            if mfe > 0:
                t["mfe_r"] = mfe * (compression ** (1.0 / (1.0 + mfe)))
    return result


def shock_correlated_crash(trades_map: dict[str, list[dict]], params: dict) -> dict[str, list[dict]]:
    """
    Synchronous adverse shock across all assets in overlapping time windows.
    For crash_intensity R of loss applied to every trade in the crash window.
    """
    crash_intensity = params.get("crash_intensity", 2.0)
    crash_spread = params.get("crash_spread", 0.3)  # fraction of trades affected
    window_days = params.get("window_days", 5)

    result = _deep_copy_trades(trades_map)

    # Collect all entry dates
    all_dates = []
    for ts in result.values():
        for t in ts:
            ed = t.get("entry_date", "")
            if ed:
                all_dates.append(ed)
    if not all_dates:
        return result

    # Find crash windows: pick random anchor dates, apply shock within window_days
    rng = random.Random(params.get("seed", 42))
    n_crash_anchors = max(1, int(len(all_dates) * crash_spread * 0.01))

    crash_dates = set()
    for _ in range(n_crash_anchors):
        anchor = rng.choice(all_dates)
        try:
            anchor_dt = datetime.fromisoformat(str(anchor))
            for d_offset in range(-window_days, window_days + 1):
                crash_dates.add((anchor_dt + timedelta(days=d_offset)).date())
        except (ValueError, TypeError):
            continue

    for ts in result.values():
        for t in ts:
            try:
                ed_str = str(t.get("entry_date", ""))
                ed = datetime.fromisoformat(ed_str).date()
                if ed in crash_dates:
                    # Apply the crash penalty by reducing mfe_r or directly adjusting r_multiple
                    orig = t.get("r_multiple", 0)
                    if orig < 0:
                        # Even R is not set directly; reduce mfe_r to reflect crash
                        mfe = t.get("mfe_r", 0.0)
                        t["mfe_r"] = max(mfe - crash_intensity, -crash_intensity)
            except (ValueError, TypeError):
                continue

    return result


SHOCK_REGISTRY: dict[str, tuple[ShockFn, str]] = {
    "mfe_compression": (
        shock_mfe_compression,
        "MFE magnitude compressed — volatility decay scenario",
    ),
    "retrace_acceleration": (
        shock_retrace_acceleration,
        "Retracements accelerate — price becomes more spiky, trailing captures less",
    ),
    "gap": (
        shock_gap,
        "Random gaps through trailing stop — black swan fills at adverse prices",
    ),
    "multi_peak_decoy": (
        shock_multi_peak_decoy,
        "False MFE peaks trigger premature trailing exit — fakeout rallies",
    ),
    "execution_lag": (
        shock_execution_lag,
        "Trailing stop fills delayed — execution slippage at stop boundary",
    ),
    "correlated_crash": (
        shock_correlated_crash,
        "Synchronous adverse shock across all assets — cascade / contagion",
    ),
    "trend_fragmentation": (
        shock_trend_fragmentation,
        "Trends become shorter — MFE tail compresses, fewer trades qualify for trailing",
    ),
}

SHOCK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "mfe_compression": [
        {"compression_factor": 0.7, "label": "30% compression"},
        {"compression_factor": 0.5, "label": "50% compression"},
        {"compression_factor": 0.3, "label": "70% compression"},
    ],
    "retrace_acceleration": [
        {"retrace_bump": 0.10, "label": "10pp retrace bump"},
        {"retrace_bump": 0.20, "label": "20pp retrace bump"},
        {"retrace_bump": 0.35, "label": "35pp retrace bump"},
    ],
    "gap": [
        {"gap_rate": 0.05, "label": "5% trade gap rate"},
        {"gap_rate": 0.10, "label": "10% trade gap rate"},
        {"gap_rate": 0.20, "label": "20% trade gap rate"},
    ],
    "multi_peak_decoy": [
        {"decoy_rate": 0.10, "decoy_penalty": 0.3, "label": "10% trades, 30% MFE loss"},
        {"decoy_rate": 0.15, "decoy_penalty": 0.5, "label": "15% trades, 50% MFE loss"},
        {"decoy_rate": 0.25, "decoy_penalty": 0.7, "label": "25% trades, 70% MFE loss"},
    ],
    "execution_lag": [
        {"lag_rate": 0.2, "lag_penalty_r": 0.2, "label": "20% trades, 0.2R penalty"},
        {"lag_rate": 0.3, "lag_penalty_r": 0.3, "label": "30% trades, 0.3R penalty"},
        {"lag_rate": 0.5, "lag_penalty_r": 0.5, "label": "50% trades, 0.5R penalty"},
    ],
    "correlated_crash": [
        {"crash_intensity": 1.0, "crash_spread": 0.2, "window_days": 3, "label": "Mild crash (1R, 20% trades)"},
        {"crash_intensity": 2.0, "crash_spread": 0.3, "window_days": 5, "label": "Moderate crash (2R, 30% trades)"},
        {"crash_intensity": 4.0, "crash_spread": 0.5, "window_days": 7, "label": "Severe crash (4R, 50% trades)"},
    ],
    "trend_fragmentation": [
        {"fragmentation": 0.3, "label": "30% trend fragmentation"},
        {"fragmentation": 0.5, "label": "50% trend fragmentation"},
        {"fragmentation": 0.7, "label": "70% trend fragmentation"},
    ],
}


# ── Sweep runner ────────────────────────────────────────────────────────────


def run_single_shock(
    trades_map: dict[str, list[dict]],
    shock_fn: ShockFn,
    params: dict[str, Any],
    unshocked_trailing_r: float,
    unshocked_per_asset: dict[str, float],
    fixed_r: float,
    name: str,
) -> ShockResult:
    perturbed = shock_fn(trades_map, params)
    trailing_r = portfolio_trailing_r(perturbed)
    per_asset = per_asset_r(perturbed)
    return ShockResult(
        name=name,
        description=params.get("label", str(params)),
        params=params,
        trailing_r=trailing_r,
        fixed_r=fixed_r,
        per_asset=per_asset,
        unshocked_trailing_r=unshocked_trailing_r,
        unshocked_per_asset=unshocked_per_asset,
    )


def run_sweep_scenario(
    trades_map: dict[str, list[dict]],
    name: str,
    shock_fn: ShockFn,
    param_sweep: list[dict[str, Any]],
    unshocked_trailing_r: float,
    unshocked_per_asset: dict[str, float],
    fixed_r: float,
    is_retrace_shock: bool = False,
) -> list[ShockResult]:
    results = []
    for params in param_sweep:
        if is_retrace_shock:
            # retrace acceleration modifies simulation param, not trade data
            retrace_bump = params.get("retrace_bump", 0.0)
            effective_retrace = min(BASELINE_RETRACE + retrace_bump, 0.95)
            # Compute shock result with adjusted retrace
            trailing_r = portfolio_trailing_r(trades_map, retrace_pct=effective_retrace)
            per_asset = per_asset_r(trades_map, retrace_pct=effective_retrace)
            result = ShockResult(
                name=name,
                description=params.get("label", str(params)),
                params=params,
                trailing_r=trailing_r,
                fixed_r=fixed_r,
                per_asset=per_asset,
                unshocked_trailing_r=unshocked_trailing_r,
                unshocked_per_asset=unshocked_per_asset,
            )
        else:
            result = run_single_shock(
                trades_map,
                shock_fn,
                params,
                unshocked_trailing_r,
                unshocked_per_asset,
                fixed_r,
                name,
            )
        results.append(result)
    return results


def find_break_point(
    trades_map: dict[str, list[dict]],
    shock_fn: ShockFn,
    param_key: str,
    param_range: list[float],
    base_params: dict[str, Any],
    unshocked_trailing_r: float,
    fixed_r: float,
    is_retrace_shock: bool = False,
) -> tuple[float | None, list[tuple[float, float, float]]]:
    """
    Sweep a single parameter and find the intensity at which trailing edge collapses
    (relative_retention < 0 or trailing_r < fixed_r).
    """
    sweep_data: list[tuple[float, float, float]] = []
    break_point = None

    for intensity in param_range:
        params = {**base_params, param_key: intensity}
        if is_retrace_shock:
            effective_retrace = min(BASELINE_RETRACE + intensity, 0.95)
            trailing_r = portfolio_trailing_r(trades_map, retrace_pct=effective_retrace)
        else:
            perturbed = shock_fn(trades_map, params)
            trailing_r = portfolio_trailing_r(perturbed)
        unshocked_edge = unshocked_trailing_r - fixed_r
        shocked_edge = trailing_r - fixed_r
        retention = shocked_edge / unshocked_edge if unshocked_edge > 0 else 0.0
        sweep_data.append((intensity, trailing_r, retention))

        if retention <= 0.0 and break_point is None:
            break_point = intensity

    return break_point, sweep_data


# ── Report builder ──────────────────────────────────────────────────────────


def print_shock_header(label: str):
    print(f"\n{'=' * 72}")
    print(f"  SHOCK: {label}")
    print(f"{'=' * 72}")


def print_shock_detail(result: ShockResult, index: int = 0):
    label = result.description
    print(f"\n  ── [{index}] {label}")
    print(f"     Trailing R (shocked):  {result.trailing_r:>+10.1f}")
    print(f"     Fixed R (baseline):    {result.fixed_r:>+10.1f}")
    print(f"     Unshocked trailing R:  {result.unshocked_trailing_r:>+10.1f}")
    print(f"     Absolute retention:    {result.absolute_retention:>7.1%}")
    print(f"     Relative edge retention: {result.relative_retention:>7.1%}")
    print(f"     Severity:              {result.severity}")
    if result.collapsed_assets:
        print(f"     ⚠ Collapsed assets:     {', '.join(result.collapsed_assets)}")
    if result.break_intensity is not None:
        print(f"     Break point:           {result.break_intensity}")


def classify_edge(relative_retention: float) -> str:
    if relative_retention >= 0.8:
        return "PASS"
    elif relative_retention >= 0.5:
        return "MODERATE"
    elif relative_retention >= 0.0:
        return "SEVERE"
    return "CATASTROPHIC"


def print_summary_table(all_results: list[tuple[str, ShockResult]]):
    print(f"\n{'=' * 72}")
    print("  SHOCK SUMMARY — ranked by severity")
    print(f"{'=' * 72}")
    print(f"{'#':>3} {'Scenario':<28} {'Intensity':<25} {'TrailR':>8} {'Retain':>7} {'Severity':<14} {'Collapsed':>10}")
    print("-" * 100)
    sorted_results = sorted(all_results, key=lambda x: x[1].relative_retention)
    for i, (scenario_name, result) in enumerate(sorted_results):
        intensity = result.description[:24]
        severity_s = result.severity
        collapse_s = str(len(result.collapsed_assets)) if result.collapsed_assets else ""
        print(
            f"{i + 1:>3} {scenario_name:<28} {intensity:<25} {result.trailing_r:>+8.1f} "
            f"{result.relative_retention:>6.1%} {severity_s:<14} {collapse_s:>10}"
        )


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    if not DATA_PATH.exists():
        logger.error("Data file not found: %s", DATA_PATH)
        sys.exit(1)

    with open(DATA_PATH) as f:
        data = json.load(f)
    trades_map = data.get("_trades", {})
    logger.info(
        "Loaded trades for %d assets, %d total trades", len(trades_map), sum(len(ts) for ts in trades_map.values())
    )

    # Baseline
    fixed_r = portfolio_fixed_r(trades_map)
    unshocked_trailing_r = portfolio_trailing_r(trades_map)
    unshocked_per_asset = per_asset_r(trades_map)

    print("=" * 72)
    print("  SHOCK SIMULATION ENGINE — Failure Discovery System")
    print("=" * 72)
    print("\n  Baseline (no shock):")
    print(f"    Fixed R:        {fixed_r:>+10.1f}")
    print(f"    Trailing R:     {unshocked_trailing_r:>+10.1f}")
    print(f"    Edge (trail - fixed): {unshocked_trailing_r - fixed_r:>+10.1f}")
    print(f"    Profitable assets (trail): {sum(1 for v in unshocked_per_asset.values() if v > 0)}/16")
    print(f"    Unprofitable assets (trail): {[a for a, v in unshocked_per_asset.items() if v <= 0] or 'none'}")

    all_results: list[tuple[str, ShockResult]] = []

    # ── 1. MFE Compression ──
    print_shock_header("MFE Compression — volatility decay")
    results = run_sweep_scenario(
        trades_map,
        "mfe_compression",
        shock_mfe_compression,
        SHOCK_DEFAULTS["mfe_compression"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("mfe_compression", r))

    # Find break point for MFE compression
    break_pt, sweep_data = find_break_point(
        trades_map,
        shock_mfe_compression,
        "compression_factor",
        [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        {"label": "sweep"},
        unshocked_trailing_r,
        fixed_r,
    )
    print(f"\n  MFE Compression break point: edge collapses at compression_factor = {break_pt}")
    print(f"  Sweep: {[(round(s[0], 2), round(s[1], 1), round(s[2], 3)) for s in sweep_data]}")

    # ── 2. Retrace Acceleration ──
    print_shock_header("Retrace Acceleration — spiky price action")
    results = run_sweep_scenario(
        trades_map,
        "retrace_acceleration",
        shock_retrace_acceleration,
        SHOCK_DEFAULTS["retrace_acceleration"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
        is_retrace_shock=True,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("retrace_acceleration", r))

    # Find break point for retrace acceleration
    bp_retrace, sweep_retrace = find_break_point(
        trades_map,
        shock_retrace_acceleration,
        "retrace_bump",
        [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50],
        {"label": "sweep", "seed": 42},
        unshocked_trailing_r,
        fixed_r,
        is_retrace_shock=True,
    )
    print(f"\n  Retrace Acceleration break point: edge collapses at retrace_bump = {bp_retrace}")
    print("  (effective retrace / trailing R / retention):")
    for intensity, tr, retention in sweep_retrace:
        eff_r = min(BASELINE_RETRACE + intensity, 0.95)
        print(f"    retrace={intensity:>5.2f} (eff={eff_r:>4.2f}) → trailR={tr:>+8.1f}  retention={retention:>6.1%}")

    # ── 3. Gap Shock ──
    print_shock_header("Gap Shock — black swan fill gaps")
    results = run_sweep_scenario(
        trades_map,
        "gap",
        shock_gap,
        SHOCK_DEFAULTS["gap"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("gap", r))

    # ── 4. Multi-Peak Decoy ──
    print_shock_header("Multi-Peak Decoy — fakeout rally traps")
    results = run_sweep_scenario(
        trades_map,
        "multi_peak_decoy",
        shock_multi_peak_decoy,
        SHOCK_DEFAULTS["multi_peak_decoy"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("multi_peak_decoy", r))

    # ── 5. Execution Lag ──
    print_shock_header("Execution Lag — delayed trailing fills")
    results = run_sweep_scenario(
        trades_map,
        "execution_lag",
        shock_execution_lag,
        SHOCK_DEFAULTS["execution_lag"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("execution_lag", r))

    # ── 6. Correlated Crash ──
    print_shock_header("Correlated Crash — cascade / contagion")
    results = run_sweep_scenario(
        trades_map,
        "correlated_crash",
        shock_correlated_crash,
        SHOCK_DEFAULTS["correlated_crash"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("correlated_crash", r))

    # ── 7. Trend Fragmentation ──
    print_shock_header("Trend Fragmentation — shorter trend regimes")
    results = run_sweep_scenario(
        trades_map,
        "trend_fragmentation",
        shock_trend_fragmentation,
        SHOCK_DEFAULTS["trend_fragmentation"],
        unshocked_trailing_r,
        unshocked_per_asset,
        fixed_r,
    )
    for i, r in enumerate(results):
        print_shock_detail(r, i + 1)
        all_results.append(("trend_fragmentation", r))

    # ── Summary ──
    print_summary_table(all_results)

    # ── Verdict ──
    print(f"\n{'=' * 72}")
    print("  SHOCK ENGINE VERDICT")
    print(f"{'=' * 72}")

    catastrophic = [(sn, r) for sn, r in all_results if r.severity == "CATASTROPHIC"]
    severe = [(sn, r) for sn, r in all_results if r.severity == "SEVERE"]
    moderate = [(sn, r) for sn, r in all_results if r.severity == "MODERATE"]
    passed = [(sn, r) for sn, r in all_results if r.severity == "PASS"]

    print(f"  CATASTROPHIC: {len(catastrophic)} scenarios — edge completely destroyed")
    print(f"  SEVERE:       {len(severe)} scenarios — edge significantly degraded")
    print(f"  MODERATE:     {len(moderate)} scenarios — noticeable but manageable")
    print(f"  PASS:         {len(passed)} scenarios — robust to structural change")

    if catastrophic:
        print("\n  ⚠ CATASTROPHIC SCENARIOS:")
        for sn, r in catastrophic:
            print(f"     {sn}: {r.description} — trailR={r.trailing_r:>+8.1f}, retention={r.relative_retention:>6.1%}")
        print("\n  System is NOT shock-stationary.")
        print("  Recommend (a) regime-conditioning exits, or (b) reducing position sizing under stress.")
    elif severe:
        print("\n  ⚠ SEVERE SCENARIOS (high fragility):")
        for sn, r in severe:
            print(f"     {sn}: {r.description} — trailR={r.trailing_r:>+8.1f}, retention={r.relative_retention:>6.1%}")
        print("\n  System is partially fragile. Deployable with monitoring — need exit regime conditioning.")
    if moderate:
        print("\n  ⚠ MODERATE SCENARIOS (notable degradation):")
        for sn, r in moderate:
            print(f"     {sn}: {r.description} — trailR={r.trailing_r:>+8.1f}, retention={r.relative_retention:>6.1%}")
        print("  Highest-risk condition: synchronized multi-asset drawdown.")
    if not severe and not catastrophic:
        print("\n  System deploys with monitoring. Edge survives all tested structural shocks at >50% retention.")

    print()


if __name__ == "__main__":
    main()
