"""Experiment Repository — JSON persistence for experiments.

Provides save/load/delete/list operations for experiment records.

Usage:
    repo = ExperimentRepository(path="research/experiments/registry")
    repo.save(experiment)
    loaded = repo.load("EXP-000001")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from eigencapital.core.provenance import compute_provenance_hash, verify_provenance
from eigencapital.research.experiments.registry import ExperimentError, ExperimentRecord


class ExperimentRepository:
    """JSON-based experiment persistence.

    Storage layout:
        base_path/
            EXP-000001.json
            EXP-000002.json
            ...
    """

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _experiment_path(self, experiment_id: str) -> Path:
        return self.base_path / f"{experiment_id}.json"

    def _read_raw_json(self, path: Path) -> dict | None:
        """Read a JSON experiment file without verifying its provenance hash.

        Used only for internal status-field checks (immutability in save/delete),
        never for returning a record to a caller. Public :meth:`load` verifies
        the hash before returning anything.
        """
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            raise ExperimentError(
                f"Experiment file {path} is malformed and cannot be read: {exc}",
            ) from exc
        if not isinstance(data, dict):
            raise ExperimentError(
                f"Experiment file {path} does not contain a JSON object",
            )
        return data

    def _verify_provenance_on_load(self, data: dict, experiment_id: str) -> None:
        """Verify the record's provenance hash on load. Fail closed.

        Raises ExperimentError if the hash is missing, malformed, or does not
        match a recomputation over the record's remaining fields. A hash check
        cannot recreate absent historical evidence — it only proves that the
        stored content matches the hash that was recorded when the experiment
        was saved.
        """
        stored_hash = data.get("provenance_hash")
        if not isinstance(stored_hash, str) or not stored_hash:
            raise ExperimentError(
                f"Experiment {experiment_id} has no provenance hash; "
                f"refusing to load unverified record",
                experiment_id=experiment_id,
            )

        # Recompute the hash over every field except provenance_hash itself,
        # mirroring how registry.create() and registry transitions compute it.
        try:
            trial = ExperimentRecord(**{**data, "provenance_hash": ""})
        except (TypeError, ValueError) as exc:
            raise ExperimentError(
                f"Experiment {experiment_id} has incomplete fields; "
                f"cannot verify provenance: {exc}",
                experiment_id=experiment_id,
            ) from exc

        if not verify_provenance(trial.to_dict(), stored_hash):
            raise ExperimentError(
                f"Experiment {experiment_id} provenance hash mismatch; "
                f"record may be tampered or corrupt",
                experiment_id=experiment_id,
            )

    def save(self, experiment: ExperimentRecord) -> None:
        """Save experiment to disk.

        Raises:
            ExperimentError: if an immutable (frozen or finalized) record
                already exists for this experiment_id — finalized experiments
                are append-only and may not be overwritten.
        """
        path = self._experiment_path(experiment.experiment_id)
        existing_data = self._read_raw_json(path)
        if existing_data is not None:
            existing = ExperimentRecord.from_dict(existing_data)
            if self._is_immutable(existing):
                raise ExperimentError(
                    f"Experiment {experiment.experiment_id} is immutable "
                    f"(status={existing.status}, frozen={existing.test_frozen}); "
                    f"refusing to overwrite",
                    experiment_id=experiment.experiment_id,
                )
        # Always write a valid provenance hash so the record can be verified
        # on load. Recomputing is deterministic and idempotent if one already
        # exists.
        fields = experiment.to_dict()
        fields.pop("provenance_hash", None)
        fields["provenance_hash"] = compute_provenance_hash(
            ExperimentRecord(**{**fields, "provenance_hash": ""}).to_dict()
        )
        experiment = ExperimentRecord(**fields)
        data = experiment.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2, ensure_ascii=False)

    def load(self, experiment_id: str) -> ExperimentRecord:
        """Load experiment from disk.

        The stored provenance hash is verified before the record is returned;
        a missing, malformed, or mismatched hash fails closed and the record is
        not loaded.

        Raises:
            ExperimentError: if file does not exist, is malformed, or its
                provenance hash is missing or does not match.
        """
        path = self._experiment_path(experiment_id)
        data = self._read_raw_json(path)
        if data is None:
            raise ExperimentError(f"Experiment not found on disk: {experiment_id}", experiment_id)
        self._verify_provenance_on_load(data, experiment_id)
        return ExperimentRecord.from_dict(data)

    def exists(self, experiment_id: str) -> bool:
        """Check if experiment file exists on disk."""
        return self._experiment_path(experiment_id).exists()

    def list_ids(self) -> List[str]:
        """List all experiment IDs stored on disk."""
        return sorted(p.stem for p in self.base_path.glob("*.json"))

    def delete(self, experiment_id: str) -> bool:
        """Delete an experiment file.

        Raises:
            ExperimentError: if the experiment is immutable (frozen or
                finalized) — finalized experiments are append-only.
        """
        path = self._experiment_path(experiment_id)
        existing_data = self._read_raw_json(path)
        if existing_data is None:
            return False
        existing = ExperimentRecord.from_dict(existing_data)
        if self._is_immutable(existing):
            raise ExperimentError(
                f"Experiment {experiment_id} is immutable; refusing to delete",
                experiment_id=experiment_id,
            )
        path.unlink()
        return True

    def _is_immutable(self, experiment: ExperimentRecord) -> bool:
        """An experiment is immutable once frozen or finalized."""
        return experiment.test_frozen or experiment.status in {
            "COMPLETED",
            "CANDIDATE",
            "REJECTED",
        }
