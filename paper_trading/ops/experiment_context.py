"""Experiment Context — Pipeline freeze, version hashing, experiment ID.

Phase 7 prelude: locks the execution stack during observation windows
so attribution data is interpretable months later.

Flow:
    ExperimentContext.freeze()  at engine startup
        → hashes all pipeline component sources
        → generates composite experiment_id
        → stamps every TradeAttributionRecord

    ExperimentContext.validate()  on each cycle
        → rehashes and compares
        → warns if any component changed mid-cycle
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("eigencapital.experiment_context")

BASE = Path(__file__).resolve().parent.parent.parent


def _hash_file(path: str | Path) -> str:
    full = BASE / path if not Path(path).is_absolute() else Path(path)
    try:
        raw = full.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:16]
    except FileNotFoundError:
        logger.warning("experiment_context: file not found for hashing: %s", path)
        return "missing"


def _hash_config(obj: object) -> str:
    raw = repr(obj)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


SOURCE_REGISTRY: list[tuple[str, str]] = [
    ("label_kernel", "labels/triple_barrier.py"),
    ("label_generator", "labels/generator.py"),
    ("archetype_classifier", "features/archetypes.py"),
    ("feature_registry", "features/registry.py"),
    ("entry_optimizer", "paper_trading/entry/optimizer.py"),
    ("decision_models", "paper_trading/entry/decision.py"),
    ("execution_policy", "paper_trading/entry/policy.py"),
    ("tp_compiler", "paper_trading/entry/tp_compiler.py"),
    ("scale_out", "paper_trading/position/scale_out.py"),
    ("deferred_entry", "paper_trading/entry/deferred_entry.py"),
    ("execution_simulator", "paper_trading/execution/simulator.py"),
    ("slippage_model", "paper_trading/execution/slippage.py"),
    ("fill_model", "paper_trading/execution/fill.py"),
    ("latency_model", "paper_trading/execution/latency.py"),
    ("trade_attribution", "paper_trading/attribution/collector.py"),
    ("dynamic_sltp", "paper_trading/position/dynamic_sltp.py"),
    ("execution_bridge", "paper_trading/execution/bridge.py"),
    ("execution_config", "shared/execution_config.py"),
]


@dataclass(frozen=True)
class PipelineFreeze:
    """Immutable snapshot of every pipeline component's source hash.

    One instance per experiment — created at startup, never mutated.
    """

    component_hashes: dict[str, str] = field(default_factory=dict)
    experiment_id: str = ""
    created_at: str = ""
    asset_universe: tuple[str, ...] = ()
    execution_config_hash: str = ""

    @classmethod
    def freeze(cls, asset_universe: tuple[str, ...] = (), execution_config: object = None) -> PipelineFreeze:
        """Compute and freeze the current pipeline state.

        Hashes every registered source file + config, then
        generates a composite experiment_id.
        """
        hashes: dict[str, str] = {}
        raw_parts: list[str] = []

        for name, path in SOURCE_REGISTRY:
            h = _hash_file(path)
            hashes[name] = h
            raw_parts.append(f"{name}:{h}")

        config_hash = _hash_config(execution_config) if execution_config is not None else "none"
        hashes["execution_config_instance"] = config_hash
        raw_parts.append(f"exec_config:{config_hash}")

        universe_str = ",".join(sorted(asset_universe))
        raw_parts.append(f"universe:{universe_str}")

        composite = hashlib.sha256("|".join(raw_parts).encode()).hexdigest()[:16]

        return cls(
            component_hashes=hashes,
            experiment_id=composite,
            created_at=datetime.now(timezone.utc).isoformat(),
            asset_universe=tuple(sorted(asset_universe)),
            execution_config_hash=config_hash,
        )

    def validate(self) -> list[str]:
        """Rehash all sources and compare. Returns list of changed components."""
        changes: list[str] = []
        for name, path in SOURCE_REGISTRY:
            current = _hash_file(path)
            if current != self.component_hashes.get(name):
                changes.append(name)
        return changes

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "asset_universe": list(self.asset_universe),
            "execution_config_hash": self.execution_config_hash,
            "component_hashes": dict(self.component_hashes),
        }


class ExperimentContext:
    """Singleton experiment context for the running engine instance.

    Created once at engine startup. Stamps every attribution record
    with the experiment_id. Validates pipeline integrity each cycle.
    """

    _instance: ExperimentContext | None = None

    def __init__(self, freeze: PipelineFreeze):
        self.freeze = freeze
        self._warned_components: set[str] = set()

    @classmethod
    def initialize(cls, asset_universe: tuple[str, ...] = (), execution_config: object = None) -> ExperimentContext:
        """Create or return the singleton experiment context."""
        if cls._instance is not None:
            logger.warning("experiment_context: already initialized, returning existing")
            return cls._instance
        freeze = PipelineFreeze.freeze(
            asset_universe=asset_universe,
            execution_config=execution_config,
        )
        logger.info(
            "experiment_context: initialized experiment_id=%s (%d components frozen)",
            freeze.experiment_id,
            len(freeze.component_hashes),
        )
        cls._instance = cls(freeze)
        return cls._instance

    @classmethod
    def get(cls) -> ExperimentContext | None:
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def check_integrity(self) -> list[str]:
        """Check pipeline integrity. Logs warnings for any drift."""
        changes = self.freeze.validate()
        for component in changes:
            if component not in self._warned_components:
                logger.warning(
                    "experiment_context: PIPELINE DRIFT detected in %s "
                    "(experiment_id=%s) — attribution data may be inconsistent",
                    component,
                    self.freeze.experiment_id,
                )
                self._warned_components.add(component)
        return changes
