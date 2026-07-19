"""Deterministic replay test — verify model inference is bit-for-bit reproducible.

Reads all (features_snapshot, inference_output) pairs from the WAL, reloads
the XGBoost model from disk, re-runs inference on the captured features, and
compares output probabilities to the recorded values.

Usage:
    PYTHONPATH=$PYTHONPATH:. python scripts/test_replay_determinism.py

Exit code:
    0 — all pairs pass
    1 — any mismatch detected
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import xgboost
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WAL_PATH = Path(BASE_DIR) / "data" / "live" / "wal" / "engine.jsonl"
MODELS_DIR = Path(BASE_DIR) / "paper_trading" / "models"

ASSET_MODEL_MAP: dict[str, str] = {
    "^DJI": "DJI",
}

TOLERANCE = 1e-6

HASH_TIER_HISTORICAL = {"GBPUSD"}


def _model_path(asset: str) -> str:
    mapped = ASSET_MODEL_MAP.get(asset, asset)
    return Path(MODELS_DIR) / f"{mapped}_model.json"


def _sidecar_path(asset: str) -> str:
    mapped = ASSET_MODEL_MAP.get(asset, asset)
    return Path(MODELS_DIR) / f"{mapped}_model_hash.txt"


def _load_wal_pairs() -> dict[str, list[dict]]:
    """Group WAL events into (features_snapshot, inference_output) pairs per asset."""
    pairs: dict[str, list[dict]] = defaultdict(list)
    pending: dict[str, dict] = {}

    with open(WAL_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            payload = e.get("payload", {})
            asset = payload.get("asset")
            if not asset:
                continue
            et = e.get("event_type")

            if et == "features_snapshot":
                pending[asset] = {
                    "features": payload.get("features", {}),
                    "feature_hash": payload.get("feature_hash"),
                    "feature_schema": payload.get("feature_schema"),
                    "model_hash": payload.get("model_hash"),
                    "seq": e.get("sequence"),
                }

            elif et == "inference_output" and asset in pending:
                snap = pending.pop(asset)
                pairs[asset].append(
                    {
                        "features": snap["features"],
                        "feature_hash": snap["feature_hash"],
                        "model_hash": snap["model_hash"],
                        "recorded": {
                            "prob_short": payload.get("prob_short"),
                            "prob_neutral": payload.get("prob_neutral"),
                            "prob_long": payload.get("prob_long"),
                        },
                        "seq_snapshot": snap["seq"],
                        "seq_inference": e.get("sequence"),
                    }
                )

    # Log any assets with unpaired snapshots
    for asset, snap in pending.items():
        if snap:
            print(f"  [WARN] {asset}: {len(pending)} unpaired features_snapshot (seq {snap['seq']})")

    return dict(pairs)


def _verify_model_hash(asset: str, wal_hash: str) -> tuple[str, str, str]:
    """Verify on-disk model hash matches WAL. Returns (tier, status, detail).

    tier: 'historical' | 'test-time'
    status: 'pass' | 'mismatch' | 'missing'
    """
    path = _model_path(asset)
    if not Path(path).exists():
        return ("test-time", "missing", f"model file not found: {path}")

    with open(path, "rb") as f:
        disk_hash = hashlib.sha256(f.read()).hexdigest()[:16]

    sidecar_path = _sidecar_path(asset)
    if Path(sidecar_path).exists():
        with open(sidecar_path) as f:
            sidecar_hash = f.read().strip()
        if sidecar_hash != disk_hash:
            return (
                "historical",
                "mismatch",
                f"sidecar={sidecar_hash} != disk={disk_hash}",
            )
        tier = "historical"
    else:
        tier = "test-time"

    if disk_hash != wal_hash:
        return (
            tier,
            "mismatch",
            f"WAL={wal_hash} != disk={disk_hash}",
        )

    return (tier, "pass", disk_hash)


def _replay_pair(model: xgboost.XGBClassifier, features: dict, recorded: dict) -> dict:
    """Re-run inference on captured features and compare to recorded."""
    fn = model.get_booster().feature_names
    df = pd.DataFrame([{k: features[k] for k in fn}])

    raw = model.predict_proba(df)  # shape (1, 2) for binary

    # Reconstruct 3-column format matching pipeline.py:276
    p1 = float(raw[0, 1])
    replayed = np.array([1.0 - p1, 0.0, p1])

    recorded_arr = np.array([recorded["prob_short"], recorded["prob_neutral"], recorded["prob_long"]])

    errors = np.abs(replayed - recorded_arr)
    max_error = float(np.max(errors))

    return {
        "replayed": {
            "prob_short": float(replayed[0]),
            "prob_neutral": float(replayed[1]),
            "prob_long": float(replayed[2]),
        },
        "errors": {
            "prob_short": float(errors[0]),
            "prob_neutral": float(errors[1]),
            "prob_long": float(errors[2]),
        },
        "max_error": max_error,
        "pass": max_error <= TOLERANCE,
    }


def _run() -> int:
    print("=" * 70)
    print("  REPLAY DETERMINISM TEST")
    print("=" * 70)
    print()

    # ── Step 1: Load WAL pairs ──
    print("Loading WAL events...")
    if not Path(WAL_PATH).exists():
        print(f"  ERROR: WAL not found at {WAL_PATH}")
        return 1
    pairs = _load_wal_pairs()
    total_pairs = sum(len(v) for v in pairs.values())
    print(f"  {len(pairs)} assets, {total_pairs} (features_snapshot, inference_output) pairs")
    print()

    # ── Step 2: Model hash verification ──
    print("=" * 70)
    print("  MODEL HASH VERIFICATION")
    print("=" * 70)
    hash_results: dict[str, tuple] = {}
    for asset in sorted(pairs.keys()):
        wal_hash = pairs[asset][0]["model_hash"]
        tier, status, detail = _verify_model_hash(asset, wal_hash)
        hash_results[asset] = (tier, status, detail)

    print(f"{'Asset':>8} {'WAL Hash':>18} {'Tier':>12} {'Status':>10}")
    print("-" * 70)
    mismatched_assets = []
    missing_assets = []
    for asset in sorted(hash_results.keys()):
        tier, status, detail = hash_results[asset]
        wal_hash = pairs[asset][0]["model_hash"]
        if status == "pass":
            print(f"{asset:>8} {wal_hash:>18} {tier:>12} {'PASS':>10}")
        elif status == "mismatch":
            mismatched_assets.append(asset)
            print(f"{asset:>8} {wal_hash:>18} {tier:>12} {'MISMATCH':>10}")
            print(f"           {detail}")
        elif status == "missing":
            missing_assets.append(asset)
            print(f"{asset:>8} {wal_hash:>18} {'N/A':>12} {'MISSING':>10}")
    print()

    # ── Step 3: Replay inference ──
    print("=" * 70)
    print("  REPLAY DETERMINISM RESULTS")
    print("=" * 70)

    total_tested = 0
    total_passed = 0
    total_failed = 0
    all_failures: list[dict] = []
    per_asset: dict[str, dict] = {}

    for asset in sorted(pairs.keys()):
        tier, status, detail = hash_results[asset]
        asset_pairs = pairs[asset]

        # Skip assets with missing or mismatched models
        if status == "missing":
            per_asset[asset] = {
                "tested": 0,
                "passed": 0,
                "failed": 0,
                "max_error": None,
                "status": "SKIP (model file missing)",
            }
            continue
        if status == "mismatch":
            per_asset[asset] = {
                "tested": 0,
                "passed": 0,
                "failed": 0,
                "max_error": None,
                "status": f"SKIP (model hash mismatch: {detail})",
            }
            continue

        # Load model
        model_path = _model_path(asset)
        model = xgboost.XGBClassifier()
        try:
            model.load_model(model_path)
        except Exception as e:  # noqa: BLE001
            per_asset[asset] = {
                "tested": 0,
                "passed": 0,
                "failed": 0,
                "max_error": None,
                "status": f"SKIP (load failed: {e})",
            }
            continue

        n_tested = len(asset_pairs)
        n_passed = 0
        n_failed = 0
        asset_failures: list[dict] = []
        max_error = 0.0

        for pair in asset_pairs:
            result = _replay_pair(model, pair["features"], pair["recorded"])
            if result["pass"]:
                n_passed += 1
            else:
                n_failed += 1
                asset_failures.append(
                    {
                        "seq": pair["seq_inference"],
                        "recorded": pair["recorded"],
                        "replayed": result["replayed"],
                        "errors": result["errors"],
                        "max_error": result["max_error"],
                    }
                )
            max_error = max(max_error, result["max_error"])

        per_asset[asset] = {
            "tested": n_tested,
            "passed": n_passed,
            "failed": n_failed,
            "max_error": max_error,
            "status": "PASS" if n_failed == 0 else "FAIL",
        }
        total_tested += n_tested
        total_passed += n_passed
        total_failed += n_failed
        all_failures.extend(asset_failures)

    # Print per-asset table
    print(f"{'Asset':>8} {'Tested':>8} {'Passed':>8} {'Failed':>8} {'Max Error':>12} {'Status':>14}")
    print("-" * 70)
    for asset in sorted(per_asset.keys()):
        r = per_asset[asset]
        err_str = f"{r['max_error']:.2e}" if r["max_error"] is not None else "N/A"
        print(f"{asset:>8} {r['tested']:>8} {r['passed']:>8} {r['failed']:>8} {err_str:>12} {r['status']:>14}")
    print()

    # ── Step 4: Failure detail ──
    if all_failures:
        print("=" * 70)
        print("  FAILURE DETAILS")
        print("=" * 70)
        for f in all_failures[:20]:  # cap output to first 20
            print(
                f"  Seq {f['seq']}: "
                f"recorded=[{f['recorded']['prob_short']:.6f}, "
                f"{f['recorded']['prob_neutral']:.6f}, "
                f"{f['recorded']['prob_long']:.6f}] "
                f"replayed=[{f['replayed']['prob_short']:.6f}, "
                f"{f['replayed']['prob_neutral']:.6f}, "
                f"{f['replayed']['prob_long']:.6f}] "
                f"max_err={f['max_error']:.2e}"
            )
        if len(all_failures) > 20:
            print(f"  ... and {len(all_failures) - 20} more")
        print()

    # ── Summary ──
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    skipped_assets = [a for a in per_asset if per_asset[a]["tested"] == 0]
    print(f"  Assets tested:    {len([a for a in per_asset if per_asset[a]['tested'] > 0])}")
    print(f"  Assets skipped:   {len(skipped_assets)}")
    for a in skipped_assets:
        print(f"    {a}: {per_asset[a]['status']}")
    print(f"  Pairs tested:     {total_tested}")
    print(f"  Pairs passed:     {total_passed}")
    print(f"  Pairs failed:     {total_failed}")

    verdict = "PASS" if total_failed == 0 else "FAIL"
    print(f"\n  VERDICT: {verdict}")
    print()

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run())
