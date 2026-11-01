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

    def save(self, experiment: ExperimentRecord) -> None:
        """Save experiment to disk.

        Raises:
            ExperimentError: if an immutable (frozen or finalized) record
                already exists for this experiment_id — finalized experiments
                are append-only and may not be overwritten.
        """
        path = self._experiment_path(experiment.experiment_id)
        if path.exists():
            existing = self.load(experiment.experiment_id)
            if self._is_immutable(existing):
                raise ExperimentError(
                    f"Experiment {experiment.experiment_id} is immutable "
                    f"(status={existing.status}, frozen={existing.test_frozen}); "
                    f"refusing to overwrite",
                    experiment_id=experiment.experiment_id,
                )
        data = experiment.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2, ensure_ascii=False)

    def load(self, experiment_id: str) -> ExperimentRecord:
        """Load experiment from disk.

        Raises:
            ExperimentError: if file does not exist
        """
        path = self._experiment_path(experiment_id)
        if not path.exists():
            raise ExperimentError(f"Experiment not found on disk: {experiment_id}", experiment_id)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
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
        if not path.exists():
            return False
        existing = self.load(experiment_id)
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
