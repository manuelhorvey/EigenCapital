#!/usr/bin/env python3
"""Model health monitor — checks model age, PSI drift, and inference volume.

Computes a composite retrain urgency score (0.0 = pristine, 1.0 = must retrain)
based on:
  - Model age vs max_age_days threshold
  - PSI drift from training baseline (where available)
  - Feature importance stability across retrain windows
  - Inference volume (cycles / predictions since last retrain)

Usage:
    # Check all assets, human-readable output
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/model_health_monitor.py

    # Machine-readable JSON output
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/model_health_monitor.py --json

    # Trigger retrain pipeline if any asset exceeds urgency threshold
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/model_health_monitor.py --trigger

    # Custom urgency thresholds
    PYTHONPATH=$PYTHONPATH:. python scripts/ops/model_health_monitor.py --max-age 45 --psi-threshold 0.20
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from monitoring.importance_tracker import ImportanceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eigencapital.model_health")

# ── Paths ────────────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = BASE / "paper_trading" / "models"
DATA_DIR = BASE / "data"
PROJECT_ROOT = BASE

# Default thresholds
DEFAULT_MAX_AGE_DAYS = 60  # days since model file was last modified
DEFAULT_PSI_THRESHOLD = 0.25  # PSI > this on any asset → flag
DEFAULT_URGENCY_THRESHOLD = 0.65  # retrain if any asset exceeds this
DEFAULT_INFERENCE_VOLUME_WARN = 50000  # cycles since retrain → flag

# Weights for composite urgency score
URGENCY_WEIGHTS = {
    "model_age": 0.30,
    "psi_drift": 0.30,
    "feature_stability": 0.20,
    "inference_volume": 0.20,
}


# ── Asset model age check ────────────────────────────────────────────────────


def check_model_ages(max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> list[dict]:
    """Check the age of each model file. Returns list of per-asset results."""
    results = []
    now = datetime.now(timezone.utc).timestamp()

    for model_path in sorted(MODEL_DIR.glob("*_model.json")):
        name = model_path.stem.replace("_model", "")
        mtime = model_path.stat().st_mtime
        age_days = (now - mtime) / 86400.0
        age_ratio = min(age_days / max_age_days, 1.0)

        results.append({
            "asset": name,
            "model_path": str(model_path),
            "age_days": round(age_days, 1),
            "is_stale": age_days > max_age_days,
            "stale_ratio": round(age_ratio, 3),
            "last_modified": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
        })

    return results


# ── PSI drift check ──────────────────────────────────────────────────────────


def check_psi_baseline_staleness(psi_threshold: float = DEFAULT_PSI_THRESHOLD) -> list[dict]:
    """Check whether PSI baselines are stale relative to their model files."""
    psi_dir = DATA_DIR / "live" / "psi_baseline"
    if not psi_dir.exists():
        logger.info("No PSI baselines found at %s — skipping PSI check", psi_dir)
        return []

    # Discover assets with PSI baselines
    baseline_assets = [p.stem for p in psi_dir.glob("*.parquet")]
    if not baseline_assets:
        return []

    # Try to compute PSI drift. This requires current features, which we
    # don't have offline — so we check for the PSI baseline existence and
    # record a warning if PSI data is stale.
    age_results = check_model_ages()
    asset_map = {a["asset"]: a for a in age_results}

    results = []
    for name in baseline_assets:
        psi_base_path = psi_dir / f"{name}.parquet"
        psi_mtime = psi_base_path.stat().st_mtime
        age_days = (datetime.now(timezone.utc).timestamp() - psi_mtime) / 86400.0

        age_info = asset_map.get(name, {})
        model_age_days = age_info.get("age_days", 0)

        # The PSI baseline should be updated during the same retrain that
        # produced the current model. If the baseline is more than 1 day
        # older than the model, it was not refreshed during the last retrain
        # and is stale (corresponds to a previous model version).
        baseline_stale = age_days > model_age_days + 1
        psi_vs_model_age = round(model_age_days - age_days, 1)

        results.append({
            "asset": name,
            "baseline_age_days": round(age_days, 1),
            "baseline_exists": True,
            "model_newer_than_baseline": model_age_days < age_days,
            "baseline_vs_model_age_gap_days": psi_vs_model_age,
            "status": "baseline_stale" if baseline_stale else "ok",
        })

    return results


# ── Feature importance stability ─────────────────────────────────────────────


def check_feature_stability() -> list[dict]:
    """Check feature importance stability from the ImportanceStore."""
    store = ImportanceStore(str(BASE))
    history = store.load_history()
    if history.empty:
        return []

    by_asset = history.groupby("asset")
    results = []
    for asset, group in by_asset:
        window_ids = group["window_id"].dropna().unique()
        if len(window_ids) < 2:
            results.append({
                "asset": asset,
                "n_windows": len(window_ids),
                "stability_score": 0.5,
                "status": "insufficient_data",
            })
            continue

        # Check if ImportanceStore can compute stability
        stability = store.compute_stability(asset)
        if stability is not None:
            # 0.0 = unstable, 1.0 = stable, normalize for urgency
            stability_norm = (stability.jaccard_top_10 + stability.spearman_rank_corr) / 2.0
            results.append({
                "asset": asset,
                "n_windows": len(window_ids),
                "jaccard_top_10": stability.jaccard_top_10,
                "spearman_rank_corr": stability.spearman_rank_corr,
                "stability_score": round(stability_norm, 3),
                "penalty": stability.penalty,
                "status": "ok",
            })
        else:
            results.append({
                "asset": asset,
                "n_windows": len(window_ids),
                "stability_score": 0.5,
                "status": "insufficient_data",
            })

    return results


# ── Inference volume check ───────────────────────────────────────────────────


def check_inference_volume(warn_threshold: int = DEFAULT_INFERENCE_VOLUME_WARN) -> list[dict]:
    """Check inference volume from engine state (cycles since retrain)."""
    state_path = PROJECT_ROOT / "data" / "live" / "state.json"
    if not state_path.exists():
        return []

    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load engine state: %s", e)
        return []

    engine = state.get("engine", {})
    assets = state.get("assets", {})

    # Try to get cycle count from engine state
    cycles_run = engine.get("cycles_run", 0)

    results = []
    for name, asset_data in assets.items():
        asset_cycles = asset_data.get("cycles_run", cycles_run)

        # Estimate inference volume from cycles
        # Each cycle = 1 inference per active asset
        # Check if we have model age to compare against
        by_cycle = asset_cycles
        volume_ratio = min(by_cycle / warn_threshold, 1.0) if warn_threshold > 0 else 0.0

        results.append({
            "asset": name,
            "estimated_inferences": by_cycle,
            "volume_ratio": round(volume_ratio, 3),
            "is_high_volume": by_cycle > warn_threshold,
            "status": "ok",
        })

    return results


# ── Composite urgency score ──────────────────────────────────────────────────


def compute_retrain_urgency(
    age_results: list[dict],
    psi_results: list[dict],
    stability_results: list[dict],
    volume_results: list[dict],
    urgency_threshold: float = DEFAULT_URGENCY_THRESHOLD,
) -> list[dict]:
    """Compute a composite retrain urgency score per asset."""
    all_assets = set()
    for r in (*age_results, *psi_results, *stability_results, *volume_results):
        all_assets.add(r["asset"])

    asset_map: dict[str, dict] = {}

    for a in all_assets:
        age = next((r for r in age_results if r["asset"] == a), None)
        psi = next((r for r in psi_results if r["asset"] == a), None)
        stab = next((r for r in stability_results if r["asset"] == a), None)
        vol = next((r for r in volume_results if r["asset"] == a), None)

        # Each check scores 0.0-1.0 for urgency
        age_score = age["stale_ratio"] if age else 0.0
        psi_score = 1.0 if (psi and psi.get("status") == "baseline_stale") else 0.0
        stab_score = (1.0 - stab["stability_score"]) if (stab and stab["status"] == "ok") else 0.5
        vol_score = vol["volume_ratio"] if vol else 0.0

        urgency = (
            age_score * URGENCY_WEIGHTS["model_age"]
            + psi_score * URGENCY_WEIGHTS["psi_drift"]
            + stab_score * URGENCY_WEIGHTS["feature_stability"]
            + vol_score * URGENCY_WEIGHTS["inference_volume"]
        )

        limiting = []
        if age_score > 0.7:
            limiting.append(f"age={age_score:.2f}")
        if psi_score > 0.5:
            limiting.append("psi_drift")
        if stab_score > 0.7:
            limiting.append(f"feat_stab={stab_score:.2f}")
        if vol_score > 0.7:
            limiting.append(f"volume={vol_score:.2f}")

        asset_map[a] = {
            "asset": a,
            "urgency_score": round(urgency, 3),
            "contributors": {
                "model_age": round(age_score, 3),
                "psi_drift": round(psi_score, 3),
                "feature_stability": round(stab_score, 3),
                "inference_volume": round(vol_score, 3),
            },
            "limiting_factors": limiting,
            "needs_retrain": urgency > urgency_threshold,
        }

    # Sort by urgency descending
    return sorted(asset_map.values(), key=lambda x: x["urgency_score"], reverse=True)


# ── Report ───────────────────────────────────────────────────────────────────


def print_report(urgency_results: list[dict]) -> None:
    """Print a human-readable health report."""
    n_assets = len(urgency_results)
    n_needs_retrain = sum(1 for r in urgency_results if r["needs_retrain"])
    mean_urgency = np.mean([r["urgency_score"] for r in urgency_results]) if urgency_results else 0.0
    max_urgency = urgency_results[0]["urgency_score"] if urgency_results else 0.0
    worst_asset = urgency_results[0]["asset"] if urgency_results else "N/A"

    print()
    print("=" * 72)
    print("  MODEL HEALTH MONITOR REPORT")
    print("=" * 72)
    print(f"  Assets checked:        {n_assets}")
    print(f"  Mean urgency:          {mean_urgency:.3f}")
    print(f"  Max urgency:           {max_urgency:.3f} ({worst_asset})")
    print(f"  Needs retrain:         {n_needs_retrain}/{n_assets}")
    print(f"  Urgency threshold:     {DEFAULT_URGENCY_THRESHOLD}")
    print()

    # Show assets that need retrain
    needing = [r for r in urgency_results if r["needs_retrain"]]
    if needing:
        print(f"  {'Asset':<12} {'Urgency':<10} {'Limiting':<40}")
        print(f"  {'-' * 62}")
        for r in needing:
            limits = ", ".join(r["limiting_factors"][:3]) if r["limiting_factors"] else "N/A"
            print(f"  {r['asset']:<12} {r['urgency_score']:<10.3f} {limits:<40}")
        print()
    else:
        print("  All assets healthy — no retrain needed.")
        print()

    # Show top 5 assets by urgency
    print("  Top assets by urgency:")
    print(f"  {'Asset':<12} {'Urgency':<10} {'Age':<8} {'PSI':<8} {'Stab':<8} {'Vol':<8}")
    print(f"  {'-' * 54}")
    for r in urgency_results[:5]:
        c = r["contributors"]
        print(
            f"  {r['asset']:<12} {r['urgency_score']:<10.3f} "
            f"{c['model_age']:<8.2f} {c['psi_drift']:<8.2f} "
            f"{c['feature_stability']:<8.2f} {c['inference_volume']:<8.2f}"
        )
    if len(urgency_results) > 5:
        print(f"  ... and {len(urgency_results) - 5} more")
    print()

    print("=" * 72)
    print()


# ── Trigger retrain ─────────────────────────────────────────────────────────


def trigger_retrain(urgency_results: list[dict]) -> bool:
    """Run the retrain scheduler if any asset exceeds the urgency threshold.

    Returns True if the pipeline was triggered.
    """
    needs_retrain = [r for r in urgency_results if r["needs_retrain"]]
    if not needs_retrain:
        logger.info("No assets need retrain — skipping pipeline trigger")
        return False

    assets_str = ", ".join(r["asset"] for r in needs_retrain[:5])
    logger.warning(
        "Retrain urgency threshold exceeded — triggering pipeline. "
        "Assets: %s (urgency: %.3f)",
        assets_str,
        max(r["urgency_score"] for r in needs_retrain),
    )

    scheduler = PROJECT_ROOT / "scripts" / "ops" / "retrain_scheduler.sh"
    if not scheduler.exists():
        logger.error("Retrain scheduler not found at %s", scheduler)
        return False

    try:
        result = subprocess.run(
            [str(scheduler)],
            capture_output=True,
            text=True,
            timeout=21600,  # 6 hours
            cwd=str(PROJECT_ROOT),
        )
        logger.info("Retrain scheduler exit code: %d", result.returncode)
        for line in result.stdout.splitlines():
            logger.info("[SCHEDULER] %s", line.strip())
        if result.stderr:
            for line in result.stderr.splitlines():
                logger.error("[SCHEDULER ERR] %s", line.strip())
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("Retrain scheduler timed out after 6 hours")
        return False
    except (OSError, ValueError) as e:
        logger.error("Failed to run retrain scheduler: %s", e)
        return False


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Model health monitor and retrain trigger")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--trigger", action="store_true", help="Trigger retrain pipeline if urgency exceeds threshold")
    parser.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE_DAYS, help="Max model age in days")
    parser.add_argument("--psi-threshold", type=float, default=DEFAULT_PSI_THRESHOLD, help="PSI drift threshold")
    parser.add_argument(
        "--urgency-threshold",
        type=float,
        default=DEFAULT_URGENCY_THRESHOLD,
        help="Urgency trigger threshold (default: %(default)s)",
    )
    parser.add_argument("--output", default=None, help="Path to save JSON results")
    args = parser.parse_args()

    t0 = time.perf_counter()

    # Run checks
    age_results = check_model_ages(max_age_days=args.max_age)
    psi_results = check_psi_baseline_staleness(psi_threshold=args.psi_threshold)
    stability_results = check_feature_stability()
    volume_results = check_inference_volume()

    # Compute composite urgency
    urgency = compute_retrain_urgency(
        age_results, psi_results, stability_results, volume_results,
        urgency_threshold=args.urgency_threshold,
    )

    elapsed = time.perf_counter() - t0

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(elapsed, 2),
        "config": {
            "max_age_days": args.max_age,
            "psi_threshold": args.psi_threshold,
            "urgency_threshold": args.urgency_threshold,
            "urgency_weights": URGENCY_WEIGHTS,
        },
        "checks": {
            "model_age": {"n_assets": len(age_results), "results": age_results},
            "psi_baseline": {"n_assets": len(psi_results), "results": psi_results},
            "feature_stability": {"n_assets": len(stability_results), "results": stability_results},
            "inference_volume": {"n_assets": len(volume_results), "results": volume_results},
        },
        "urgency": {
            "n_assets": len(urgency),
            "mean_urgency": round(float(np.mean([r["urgency_score"] for r in urgency])), 3) if urgency else 0.0,
            "max_urgency": round(urgency[0]["urgency_score"], 3) if urgency else 0.0,
            "worst_asset": urgency[0]["asset"] if urgency else "N/A",
            "n_needs_retrain": sum(1 for r in urgency if r["needs_retrain"]),
            "assets": urgency,
        },
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(urgency)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Report saved to %s", out_path)

    # Trigger retrain if requested
    triggered = False
    if args.trigger:
        triggered = trigger_retrain(urgency)
        if triggered:
            logger.info("Retrain pipeline triggered successfully")
        else:
            logger.info("Retrain pipeline was NOT triggered (no assets above threshold or scheduler failed)")
    elif report["urgency"]["n_needs_retrain"] > 0 and not args.trigger:
        worst = urgency[0]
        logger.warning(
            "%d assets exceed retrain urgency threshold (worst: %s at %.3f). "
            "Use --trigger to run the retrain pipeline.",
            report["urgency"]["n_needs_retrain"],
            worst["asset"],
            worst["urgency_score"],
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
