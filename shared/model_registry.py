"""ModelRegistry — versioned model storage with metadata tracking.

Each asset's model is stored as:

    models/{asset}/
        {hash}_{train_date}_{feature_hash}.json   # versioned model file
        manifest.json                              # version manifest
    models/{asset}_model.json                      # current-production pointer

The manifest tracks: version id, training date, feature set hash, OOS metrics,
calibration ECE, deployment status, and rollback availability.

``deploy_version_gated()`` runs validation gates before promoting.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("eigencapital.model_registry")

MODELS_DIR = Path(__file__).resolve().parent.parent / "paper_trading" / "models"


@dataclass
class ModelVersion:
    """Metadata for a single model version."""

    version_id: str
    asset: str
    train_date: str
    train_end: str
    feature_hash: str
    model_hash: str
    n_features: int
    oos_sharpe: float | None = None
    oos_total_r: float | None = None
    oos_accuracy: float | None = None
    ece: float | None = None
    deployment_status: str = "staging"  # staging, production, archived, rolled_back
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _ensure_asset_dir(asset: str) -> Path:
    d = MODELS_DIR / asset
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(asset: str) -> Path:
    return _ensure_asset_dir(asset) / "manifest.json"


def _current_link_path(asset: str) -> Path:
    return MODELS_DIR / f"{asset}_model.json"


def _versioned_path(asset: str, version_id: str) -> Path:
    return _ensure_asset_dir(asset) / f"{version_id}.json"


def _load_manifest(asset: str) -> dict[str, Any]:
    path = _manifest_path(asset)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Corrupt manifest for %s: %s", asset, e)
    return {"versions": [], "current": None}


def _save_manifest(asset: str, manifest: dict[str, Any]) -> None:
    with open(_manifest_path(asset), "w") as f:
        json.dump(manifest, f, indent=2, default=str)


def save_model(
    asset: str,
    model_bytes: bytes,
    train_date: str,
    train_end: str,
    feature_hash: str,
    model_hash: str,
    n_features: int,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Save a versioned model file and update the manifest.

    Returns the version_id.
    """
    version_id = f"{model_hash}_{train_date}_{feature_hash[:8]}"
    vpath = _versioned_path(asset, version_id)

    with open(vpath, "wb") as f:
        f.write(model_bytes)

    manifest = _load_manifest(asset)
    version_entry = {
        "version_id": version_id,
        "asset": asset,
        "train_date": train_date,
        "train_end": train_end,
        "feature_hash": feature_hash,
        "model_hash": model_hash,
        "n_features": n_features,
        "deployment_status": "staging",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        version_entry.update(metadata)

    manifest["versions"].append(version_entry)
    _save_manifest(asset, manifest)

    deploy_version(asset, version_id)

    logger.info(
        "%s: saved model version %s (%d features)",
        asset,
        version_id,
        n_features,
    )
    return version_id


def deploy_version(asset: str, version_id: str) -> bool:
    """Set a specific version as the production model (update pointer).

    Creates a copy at ``models/{asset}_model.json`` (the path expected by
    the existing inference pipeline) so existing loading code works without
    changes.
    """
    vpath = _versioned_path(asset, version_id)
    if not vpath.exists():
        logger.warning("Version %s for %s not found — cannot deploy", version_id, asset)
        return False

    link_path = _current_link_path(asset)
    shutil.copy2(vpath, link_path)

    manifest = _load_manifest(asset)
    for v in manifest.get("versions", []):
        if v["version_id"] == version_id:
            v["deployment_status"] = "production"
        elif v["deployment_status"] == "production":
            v["deployment_status"] = "archived"
    manifest["current"] = version_id

    # Write via the version entry not the full dict
    with open(_manifest_path(asset), "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    logger.info(
        "%s: deployed version %s → %s",
        asset,
        version_id,
        link_path.name,
    )
    return True


def rollback(asset: str) -> str | None:
    """Rollback to the previous production version.

    Returns the rolled-back version_id, or None if no previous version exists.
    """
    manifest = _load_manifest(asset)
    versions = manifest.get("versions", [])
    current = manifest.get("current")

    if not versions or not current:
        logger.warning("No versions to rollback to for %s", asset)
        return None

    # Find the previous production version
    prev = None
    found_current = False
    for v in reversed(versions):
        vid = v.get("version_id", "")
        if vid == current:
            found_current = True
        elif found_current and v.get("deployment_status") in ("production", "archived", "staging"):
            prev = v
            break

    if prev is None:
        logger.warning("No previous version found for %s", asset)
        return None

    prev_id = prev["version_id"]
    if deploy_version(asset, prev_id):
        # Reload manifest (deploy_version may have updated it)
        updated = _load_manifest(asset)
        for v in updated.get("versions", []):
            if v["version_id"] == current:
                v["deployment_status"] = "rolled_back"
        _save_manifest(asset, updated)
        logger.info("%s: rolled back from %s → %s", asset, current, prev_id)
        return prev_id

    return None


def list_versions(asset: str) -> list[dict[str, Any]]:
    """List all available versions for an asset."""
    manifest = _load_manifest(asset)
    return manifest.get("versions", [])


def get_current_version(asset: str) -> dict[str, Any] | None:
    """Get the current production version metadata."""
    manifest = _load_manifest(asset)
    current = manifest.get("current")
    if not current:
        return None
    for v in manifest.get("versions", []):
        if v.get("version_id") == current:
            return v
    return None


def get_version(asset: str, version_id: str) -> dict[str, Any] | None:
    """Get metadata for a specific version."""
    for v in list_versions(asset):
        if v.get("version_id") == version_id:
            return v
    return None


def deploy_version_gated(
    asset: str,
    version_id: str,
    incumbent_returns: np.ndarray | None = None,
    candidate_returns: np.ndarray | None = None,
    force: bool = False,
) -> tuple[bool, list[dict[str, Any]]]:
    """Deploy a version only if validation gates pass.

    Args:
        asset: Asset name.
        version_id: Version to deploy.
        incumbent_returns: Per-trade R-multiples for current production model.
        candidate_returns: Per-trade R-multiples for candidate model.
        force: Skip gates and deploy directly.

    Returns:
        (deployed, gate_results) where each gate result is a dict.
    """
    from shared.validation_gates import run_validation_gates

    if force:
        ok = deploy_version(asset, version_id)
        return ok, [{"name": "force_override", "passed": True}]

    incumbent = get_current_version(asset)
    candidate = get_version(asset, version_id)

    if incumbent is None:
        logger.info("%s: no incumbent to compare against — deploying directly", asset)
        ok = deploy_version(asset, version_id)
        return ok, [{"name": "no_incumbent", "passed": True}]

    results = run_validation_gates(
        asset=asset,
        incumbent=incumbent,
        candidate=candidate,
        incumbent_returns=incumbent_returns,
        candidate_returns=candidate_returns,
    )

    all_passed = all(r.passed for r in results)
    if all_passed:
        ok = deploy_version(asset, version_id)
    else:
        logger.warning(
            "%s: validation gates blocked deployment of version %s (%d/%d passed)",
            asset,
            version_id,
            sum(1 for r in results if r.passed),
            len(results),
        )
        for r in results:
            if not r.passed:
                logger.warning("  FAIL [%s]: %s", r.name, r.message)
        ok = False

    return ok, [vars(r) for r in results]
