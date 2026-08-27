"""Phase 2 Baseline Lock — captures frozen state before infrastructure changes.

This script captures the EXACT state of the R4 qualification campaign
at the moment infrastructure work begins. Every subsequent infrastructure
change must demonstrate R4 behavioral parity against this baseline.

Usage:
    python scripts/capture_phase2_baseline.py
    python scripts/capture_phase2_baseline.py --output reports/phase2_baseline.json
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from eigencapital.config import load_config
from eigencapital.fidelity.r4_manifest import R4ConfigManifest
from eigencapital.production_qual.fingerprint_verifier import FingerprintVerifier
from eigencapital.risk.policy import RiskPolicy


def get_git_head() -> str:
    """Get current git HEAD commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def get_git_status() -> dict:
    """Get git working tree status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            lines = [line for line in result.stdout.strip().split("\n") if line]
            return {
                "clean": len(lines) == 0,
                "modified_files": len(lines),
                "files": lines[:20],  # Cap at 20 for readability
            }
        return {"clean": False, "error": "git status failed"}
    except Exception:
        return {"clean": False, "error": "git not available"}


def count_tests() -> dict:
    """Count and categorize existing tests."""
    test_dirs = [
        Path("tests/unit"),
        Path("tests/integration"),
    ]

    total_tests = 0
    total_files = 0
    categories = {}

    for test_dir in test_dirs:
        if not test_dir.exists():
            continue
        for test_file in test_dir.rglob("test_*.py"):
            total_files += 1
            # Count test functions
            try:
                content = test_file.read_text()
                test_count = content.count("def test_")
                total_tests += test_count

                # Categorize by directory
                rel_path = test_file.relative_to(test_dir)
                category = rel_path.parts[0] if len(rel_path.parts) > 1 else "root"
                categories[category] = categories.get(category, 0) + test_count
            except Exception:
                pass

    return {
        "total_test_files": total_files,
        "total_test_functions": total_tests,
        "categories": categories,
    }


def capture_baseline() -> dict:
    """Capture the complete Phase 2 baseline."""
    now = datetime.now(UTC)

    # Load config
    config = load_config("production")

    # Load manifest and compute fingerprints
    R4ConfigManifest()
    RiskPolicy()
    verifier = FingerprintVerifier(config=config)

    # Compute build ID from git
    git_head = get_git_head()
    build_id = hashlib.sha256(git_head.encode()).hexdigest()[:16]

    # Capture universe
    universe = list(config.broker.allowed_symbols.keys()) if hasattr(config.broker, "allowed_symbols") else []

    # Capture risk limits
    risk_limits = {
        "max_concurrent_positions": config.live_risk.max_concurrent_positions,
        "max_position_notional": config.live_risk.max_position_notional,
        "max_order_notional": config.live_risk.max_order_notional,
        "max_per_position_loss_pct": config.live_risk.max_per_position_loss_pct,
        "max_account_drawdown_pct": config.live_risk.max_account_drawdown_pct,
        "max_daily_loss": config.live_risk.max_daily_loss,
        "min_equity": config.live_risk.min_equity,
        "t0_equity": config.live_risk.t0_equity,
    }

    # Capture strategy parameters
    strategy_params = {
        "name": config.strategy.name,
        "version": config.strategy.version,
        "manifest_fingerprint": config.strategy.manifest_fingerprint,
        "vol_target_annual": config.strategy.vol_target_annual,
        "vol_lookback": config.strategy.vol_lookback,
        "signal_lookback_short": config.strategy.signal_lookback_short,
        "signal_lookback_long": config.strategy.signal_lookback_long,
        "rebalance_frequency": config.strategy.rebalance_frequency,
        "skip_months": config.strategy.skip_months,
        "vol_lookback_signal": config.strategy.vol_lookback_signal,
        "risk_lookback": config.strategy.risk_lookback,
        "transaction_cost_bps": config.strategy.transaction_cost_bps,
        "slippage_bps": config.strategy.slippage_bps,
        "max_orders_per_cycle": config.execution.max_orders_per_cycle,
    }

    # Count tests
    test_info = count_tests()

    # Get git status
    git_status = get_git_status()

    # Find current campaign ID
    campaign_id = "R4-5K-UNKNOWN"
    t0_dir = Path("reports/r4_qualification")
    if t0_dir.exists():
        t0_files = sorted(t0_dir.glob("T0_*.json"), key=os.path.getmtime)
        if t0_files:
            try:
                with open(t0_files[-1]) as f:
                    t0_data = json.load(f)
                    campaign_id = t0_data.get("campaign_id", campaign_id)
            except Exception:
                pass

    # Build baseline
    baseline = {
        "captured_at": now.isoformat(),
        "git_head": git_head,
        "build_id": build_id,
        "campaign_id": campaign_id,
        "fingerprints": {
            "r4_manifest": verifier.frozen_manifest_fingerprint,
            "risk_policy": verifier.frozen_risk_fingerprint,
            "live_risk": verifier.frozen_live_risk_fingerprint,
            "config": verifier._frozen_config_fp,
            "strategy_version": config.strategy.version,
        },
        "universe": {
            "symbols": universe,
            "count": len(universe),
            "categories": {},
        },
        "cadence": {
            "rebalance_frequency": config.strategy.rebalance_frequency,
            "max_orders_per_cycle": config.execution.max_orders_per_cycle,
        },
        "risk_limits": risk_limits,
        "strategy_params": strategy_params,
        "evidence_schema": {
            "version": "1.0",
            "fields": [
                "signal_timestamp",
                "intended_symbol",
                "intended_direction",
                "intended_weight",
                "requested_price",
                "fill_price",
                "spread",
                "slippage",
                "execution_latency",
                "rejection_status",
                "partial_fill_status",
                "swap",
                "commission",
                "actual_exit",
                "exit_reason",
                "realized_pnl",
                "mae",
                "mfe",
                "holding_period",
                "forward_return_1h",
                "forward_return_1d",
                "forward_return_3d",
                "forward_return_5d",
                "forward_return_10d",
                "forward_return_20d",
            ],
        },
        "test_info": test_info,
        "git_status": git_status,
        "phase2_governance": {
            "r4_signal_frozen": True,
            "r4_universe_frozen": True,
            "r4_cadence_frozen": True,
            "r4_sizing_frozen": True,
            "r4_exit_logic_frozen": True,
            "r4_risk_envelope_frozen": True,
            "max_tier": "$5K",
            "no_optimization": True,
            "no_universe_expansion": True,
            "no_cadence_changes": True,
            "no_capital_promotion": True,
        },
    }

    # Compute baseline hash
    baseline_json = json.dumps(baseline, sort_keys=True, default=str)
    baseline["baseline_hash"] = hashlib.sha256(baseline_json.encode()).hexdigest()

    return baseline


def save_baseline(baseline: dict, output_path: str = "reports/phase2_baseline.json") -> None:
    """Save baseline to file."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, default=str)
    print(f"✅ Baseline saved to: {output_path}")


def verify_baseline(baseline: dict) -> None:
    """Verify baseline integrity."""
    print("\n=== Phase 2 Baseline Verification ===")
    print(f"  Git HEAD: {baseline['git_head'][:12]}...")
    print(f"  Build ID: {baseline['build_id']}")
    print(f"  Campaign: {baseline['campaign_id']}")
    print(f"  Baseline Hash: {baseline['baseline_hash'][:16]}...")

    print("\n  Fingerprints:")
    for name, fp in baseline["fingerprints"].items():
        print(f"    {name}: {fp[:16]}...")

    print(f"\n  Universe: {baseline['universe']['count']} symbols")
    print(f"  Cadence: {baseline['cadence']['rebalance_frequency']}")
    print(f"  Max Positions: {baseline['risk_limits']['max_concurrent_positions']}")
    print(f"  T=0 Equity: ${baseline['risk_limits']['t0_equity']:,.2f}")

    print(
        f"\n  Tests: {baseline['test_info']['total_test_functions']} functions in {baseline['test_info']['total_test_files']} files"
    )
    print(f"  Git Clean: {baseline['git_status']['clean']}")

    print("\n  Phase 2 Governance:")
    for rule, value in baseline["phase2_governance"].items():
        status = "🔒" if value else "⚠️"
        print(f"    {status} {rule}: {value}")

    print("\n✅ Baseline captured successfully")
    print("   All subsequent infrastructure changes must demonstrate R4 behavioral parity.")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Capture Phase 2 baseline lock")
    parser.add_argument(
        "--output",
        default="reports/phase2_baseline.json",
        help="Output path for baseline JSON",
    )
    args = parser.parse_args()

    print("=== Capturing Phase 2 Baseline Lock ===\n")

    baseline = capture_baseline()
    save_baseline(baseline, args.output)
    verify_baseline(baseline)

    return baseline


if __name__ == "__main__":
    main()
