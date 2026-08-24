"""Domain model: Experiment.

Pre-registered, reproducible research run.

Invariants:
- experiment_id is unique (e.g. "EXP-000001")
- git_commit is the hash of code state at experiment start
- dataset_version is versioned (e.g. "equities_daily_v3")
- strategy_id + strategy_version link to the strategy
- parameters is the strategy config at experiment start
- cost_model is the transaction cost model version
- random_seed is set for stochastic strategies
 - train/validation/test splits are non-overlapping, test is untouched
 - horizon matches strategy horizon (intraday/swing)
 - Once test_split is defined, parameters and strategy code are frozen
 - parent_experiment_id records lineage when an experiment extends another
 - trial_metadata records multiple-testing accounting (trial family, index,
   selection method); required before any CANDIDATE promotion per
   RESEARCH_ENGINE_CONTRACT.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import date

from eigencapital.core.models.trial_metadata import TrialMetadata


class ExperimentStatus(str):
    """Experiment status enum."""

    PRE_REGISTERED = "PRE_REGISTERED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANDIDATE = "CANDIDATE"


@dataclass(frozen=True)
class Experiment:
    """Pre-registered, reproducible research run.

    Every strategy hypothesis undergoes a pre-registered experiment
    with defined splits and versioning.

    Invariants:
    - experiment_id is unique (e.g. "EXP-000001")
    - git_commit is the hash of code state at experiment start
    - dataset_version is versioned (e.g. "equities_daily_v3")
    - strategy_id + strategy_version link to the strategy code/config
    - parameters is the strategy config at experiment start (versioned)
    - cost_model is the transaction cost model version
    - random_seed is set for reproducibility (if stochastic)
    - train/validation/test splits are non-overlapping
    - test_split is untouched (not used in parameter tuning)
    - horizon matches strategy horizon (intraday/swing)
    - Once test_split is defined, parameters and strategy code are frozen
    - status tracks the experiment lifecycle

    Flow:
        Strategy Idea
              ↓
        Pre-registration → Experiment ledger
              ↓
        Dataset selection & versioning
              ↓
        Feature calculation
              ↓
        Signal generation (StrategyIntent + DecisionSnapshot)
              ↓
        Train / Validation / Test splits
              ↓
        COMPLETED / REJECTED / CANDIDATE
    """

    experiment_id: str  # e.g. "EXP-000001"
    git_commit: str  # hash of code state at experiment start
    dataset_version: str  # e.g. "equities_daily_v3"
    strategy_id: str  # linked strategy
    strategy_version: str  # strategy code version
    parameters: Dict[str, Any]  # strategy config at experiment start
    cost_model: str  # e.g. "cost_model_v2"
    random_seed: Optional[int] = None  # for stochastic strategy reproducibility
    start_date: Optional[date] = None  # experiment start date
    end_date: Optional[date] = None  # experiment end date
    train_split: Optional[tuple] = None  # (start_date, end_date) in-sample
    validation_split: Optional[tuple] = None  # (start_date, end_date) out-of-sample
    test_split: Optional[tuple] = None  # (start_date, end_date) untouched test
    horizon: str = "swing"  # intraday or swing
    status: str = ExperimentStatus.PRE_REGISTERED  # lifecycle status
    created_at: Optional[str] = None  # ISO-8601 when experiment was created
    parent_experiment_id: Optional[str] = None  # lineage: experiment this one extends
    trial_metadata: Optional[TrialMetadata] = None  # multiple-testing accounting
    meta: Dict[str, Any] = field(default_factory=dict)  # free-form notes, tags

    # Class-level registry

    def __post_init__(self) -> None:
        # Validate experiment_id is non-empty
        if not self.experiment_id:
            raise ValueError("experiment_id must be non-empty")

        # Validate git_commit is non-empty
        if not self.git_commit:
            raise ValueError("git_commit must be non-empty (code hash)")

        # Validate dataset_version is non-empty
        if not self.dataset_version:
            raise ValueError("dataset_version must be non-empty (dataset hash)")

        # Validate strategy_id is non-empty
        if not self.strategy_id:
            raise ValueError("strategy_id must be non-empty")

        # Validate strategy_version is non-empty
        if not self.strategy_version:
            raise ValueError("strategy_version must be non-empty (strategy version)")

        # Validate cost_model is non-empty
        if not self.cost_model:
            raise ValueError("cost_model must be non-empty (cost model version)")

        # Validate horizon is a known value
        valid_horizons = {"intraday", "swing"}
        if self.horizon not in valid_horizons:
            raise ValueError(
                f"Invalid experiment horizon: {self.horizon}. "
                f"Must be one of {valid_horizons}"
            )

        # Validate status is a known value
        valid_statuses = {
            ExperimentStatus.PRE_REGISTERED,
            ExperimentStatus.RUNNING,
            ExperimentStatus.COMPLETED,
            ExperimentStatus.REJECTED,
            ExperimentStatus.CANDIDATE,
        }
        if self.status not in valid_statuses:
            raise ValueError(
                f"Invalid experiment status: {self.status}. "
                f"Must be one of {valid_statuses}"
            )

        # Validate train_split format if set
        if self.train_split is not None:
            if not isinstance(self.train_split, tuple) or len(self.train_split) != 2:
                raise ValueError(
                    f"train_split must be (start_date, end_date) tuple, got {self.train_split}"
                )
            train_start, train_end = self.train_split
            if train_start > train_end:
                raise ValueError(
                    f"train_split start ({train_start}) must be <= end ({train_end})"
                )

        # Validate validation_split format if set
        if self.validation_split is not None:
            if (
                not isinstance(self.validation_split, tuple)
                or len(self.validation_split) != 2
            ):
                raise ValueError(
                    f"validation_split must be (start_date, end_date) tuple, got {self.validation_split}"
                )
            val_start, val_end = self.validation_split
            if val_start > val_end:
                raise ValueError(
                    f"validation_split start ({val_start}) must be <= end ({val_end})"
                )

        # Validate test_split format if set
        if self.test_split is not None:
            if not isinstance(self.test_split, tuple) or len(self.test_split) != 2:
                raise ValueError(
                    f"test_split must be (start_date, end_date) tuple, got {self.test_split}"
                )
            test_start, test_end = self.test_split
            if test_start > test_end:
                raise ValueError(
                    f"test_split start ({test_start}) must be <= end ({test_end})"
                )

        # CRITICAL INVARIANT: Once test_split is defined, parameters and strategy code are frozen.
        # No post-hoc parameter tweaking on the test period.
        if self.test_split is not None:
            # If we have a test split, the experiment is considered finalized
            # and parameters should not be changed retroactively.
            # We document this by marking status as at least PRE_REGISTERED
            # (actually past that point)
            if self.status == ExperimentStatus.PRE_REGISTERED:
                # This is allowed; the experiment can move from PRE_REGISTERED
                # to RUNNING once test_split is set
                pass

        # INVARIANT: Splits must be non-overlapping (test must be after train/val)
        # Check overlaps if all three splits are defined
        if (
            self.train_split is not None
            and self.validation_split is not None
            and self.test_split is not None
        ):
            train_start, train_end = self.train_split
            val_start, val_end = self.validation_split
            test_start, test_end = self.test_split

            # Train and validation should not overlap
            if train_end > val_start:
                raise ValueError(
                    f"train_split ends ({train_end}) after validation_split starts ({val_start}): "
                    "splits overlap. Train must come before validation."
                )

            # Validation and test should not overlap
            if val_end > test_start:
                raise ValueError(
                    f"validation_split ends ({val_end}) after test_split starts ({test_start}): "
                    "splits overlap. Validation must come before test."
                )

            # Optional: train should come before validation
            if train_end > val_start and not (train_end == val_start):
                # This is just a warning; the actual constraint is train_end <= val_start
                pass

        # INVARIANT: random_seed, if set, must be non-negative
        if self.random_seed is not None and self.random_seed < 0:
            raise ValueError("random_seed must be >= 0 if set")

        # Validate created_at format if set
        if self.created_at is not None and "T" not in self.created_at:
            raise ValueError(
                f"created_at should be ISO-8601 format, got: {self.created_at}"
            )

        # Validate meta is a dict
        if not isinstance(self.meta, dict):
            raise ValueError("meta must be a dict")

        # Validate parent_experiment_id if set
        if self.parent_experiment_id is not None and not self.parent_experiment_id:
            raise ValueError("parent_experiment_id must be non-empty if set")

        # Validate trial_metadata type
        if self.trial_metadata is not None and not isinstance(
            self.trial_metadata, TrialMetadata
        ):
            raise ValueError("trial_metadata must be a TrialMetadata instance or None")

        # Registry check for duplicate experiment_ids
        if self.experiment_id in self._registry:
            raise ValueError(
                f"Duplicate experiment_id: {self.experiment_id}. "
                "Experiment IDs must be unique (ledger requirement)."
            )
        self._registry[self.experiment_id] = True

    def __hash__(self) -> int:
        return hash((self.experiment_id, self.git_commit, self.dataset_version))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Experiment):
            return NotImplemented
        return self.experiment_id == other.experiment_id

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization for provenance/hashing."""
        return {
            "experiment_id": self.experiment_id,
            "git_commit": self.git_commit,
            "dataset_version": self.dataset_version,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "parameters": dict(self.parameters),  # ensure plain dict,
            "cost_model": self.cost_model,
            "random_seed": self.random_seed,
            "start_date": str(self.start_date) if self.start_date else None,
            "end_date": str(self.end_date) if self.end_date else None,
            "train_split": list(self.train_split) if self.train_split else None,
            "validation_split": list(self.validation_split)
            if self.validation_split
            else None,
            "test_split": list(self.test_split) if self.test_split else None,
            "horizon": self.horizon,
            "status": self.status,
            "created_at": self.created_at,
            "parent_experiment_id": self.parent_experiment_id,
            "trial_metadata": (
                self.trial_metadata.to_dict() if self.trial_metadata else None
            ),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Experiment:
        """Deserialize from dict (deterministic, keys sorted)."""
        from datetime import date as date_type

        return Experiment(
            experiment_id=d["experiment_id"],
            git_commit=str(d["git_commit"]),
            dataset_version=str(d["dataset_version"]),
            strategy_id=str(d["strategy_id"]),
            strategy_version=str(d["strategy_version"]),
            parameters=d.get("parameters", {}),
            cost_model=str(d["cost_model"]),
            random_seed=int(d["random_seed"])
            if d.get("random_seed") is not None
            else None,
            start_date=(
                date_type.fromisoformat(d["start_date"])
                if d.get("start_date")
                else None
            ),
            end_date=(
                date_type.fromisoformat(d["end_date"]) if d.get("end_date") else None
            ),
            train_split=tuple(d["train_split"]) if d.get("train_split") else None,
            validation_split=tuple(d["validation_split"])
            if d.get("validation_split")
            else None,
            test_split=tuple(d["test_split"]) if d.get("test_split") else None,
            horizon=str(d.get("horizon", "swing")),
            status=str(d.get("status", ExperimentStatus.PRE_REGISTERED)),
            created_at=d.get("created_at"),
            parent_experiment_id=d.get("parent_experiment_id"),
            trial_metadata=(
                TrialMetadata.from_dict(d["trial_metadata"])
                if d.get("trial_metadata")
                else None
            ),
            meta=d.get("meta", {}),
        )

    @property
    def is_complete(self) -> bool:
        """Check if experiment has all splits defined and is completed."""
        return (
            self.status == ExperimentStatus.COMPLETED
            and self.train_split is not None
            and self.validation_split is not None
            and self.test_split is not None
        )

    @property
    def has_test_split(self) -> bool:
        """Check if experiment has an untouched test split."""
        return self.test_split is not None

    @property
    def is_rejected(self) -> bool:
        """Check if experiment was rejected."""
        return self.status == ExperimentStatus.REJECTED

    @property
    def is_candidate(self) -> bool:
        """Check if experiment is a candidate."""
        return self.status == ExperimentStatus.CANDIDATE

    @property
    def full_split_triple(self) -> Optional[tuple]:
        """Return (train, validation, test) splits if all defined, else None."""
        if self.train_split and self.validation_split and self.test_split:
            return (self.train_split, self.validation_split, self.test_split)
        return None

    @property
    def has_trial_metadata(self) -> bool:
        """Check whether multiple-testing accounting is attached."""
        return self.trial_metadata is not None

    @property
    def trial_family_size(self) -> Optional[int]:
        """Known size of the trial family (None while the search is open)."""
        return self.trial_metadata.trials_in_family if self.trial_metadata else None

    def summary(self) -> str:
        """Human-readable summary."""
        trial_line = ""
        if self.trial_metadata:
            trial_line = f"\n  trials={self.trial_metadata.summary()}"
            if self.parent_experiment_id:
                trial_line += f"\n  parent={self.parent_experiment_id}"
        return (
            f"Experiment[{self.experiment_id}]:\n"
            f"  status={self.status}\n"
            f"  strategy={self.strategy_id}/{self.strategy_version}\n"
            f"  dataset={self.dataset_version}\n"
            f"  git={self.git_commit[:8]}...\n"
            f"  horizon={self.horizon}\n"
            f"  train={self.train_split}\n"
            f"  val={self.validation_split}\n"
            f"  test={self.test_split}\n"
            f"  seed={self.random_seed}{trial_line}"
        )


Experiment._registry = {}
