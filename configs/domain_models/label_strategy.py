"""Label Strategy Registry — per-asset training label configuration.

Single source of truth for which labeling strategy each asset uses
during model training. Decouples the learning objective (strategy)
from the execution PT/SL geometry (triple_barrier.yaml).

Usage:
    registry = LabelStrategyRegistry()
    cfg = registry.get("GC")
    # cfg.strategy == "TB_sym", cfg.pt == 3.0, cfg.sl == 3.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = REPO_ROOT / "configs" / "domains" / "ml" / "label_strategy_registry.yaml"


@dataclass
class ValidationEvidence:
    experiment_id: str | None = None
    validation_date: str | None = None
    sharpe_delta: str | None = None
    sharpe_p: str | None = None
    ece_delta: str | None = None
    ece_p: str | None = None
    cal_inv_delta: str | None = None
    cal_inv_p: str | None = None
    confidence: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> ValidationEvidence:
        return cls(
            experiment_id=d.get("experiment_id"),
            validation_date=d.get("validation_date"),
            sharpe_delta=d.get("sharpe_delta"),
            sharpe_p=d.get("sharpe_p"),
            ece_delta=d.get("ece_delta"),
            ece_p=d.get("ece_p"),
            cal_inv_delta=d.get("cal_inv_delta"),
            cal_inv_p=d.get("cal_inv_p"),
            confidence=d.get("confidence"),
        )


@dataclass
class AssetLabelConfig:
    asset: str
    strategy: str
    pt: float | None = None
    sl: float | None = None
    status: str = "exploratory"
    validated: str | None = None
    validation: ValidationEvidence = field(default_factory=ValidationEvidence)
    notes: str | None = None

    @classmethod
    def from_dict(cls, asset: str, d: dict) -> AssetLabelConfig:
        v = d.get("validation")
        return cls(
            asset=asset,
            strategy=d["strategy"],
            pt=d.get("pt"),
            sl=d.get("sl"),
            status=d.get("status", "exploratory"),
            validated=d.get("validated"),
            validation=ValidationEvidence.from_dict(v) if v else ValidationEvidence(),
            notes=d.get("notes"),
        )


class LabelStrategyRegistry:
    """Loads and queries the label strategy registry YAML."""

    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH
        self._raw: dict[str, Any] = {}
        self._version: str = ""
        self._generated: str = ""
        self._default_strategy: str = "TB_v1"
        self._strategies: dict[str, dict] = {}
        self._assets: dict[str, AssetLabelConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        data = yaml.safe_load(self.path.read_text()) or {}
        self._version = data.get("version", "")
        self._generated = data.get("generated", "")
        self._default_strategy = (
            data.get("default_strategy", {}).get("strategy", "TB_v1")
        )
        self._strategies = data.get("strategies", {})

        for name, raw in data.get("assets", {}).items():
            self._assets[name] = AssetLabelConfig.from_dict(name, raw)

    @property
    def version(self) -> str:
        return self._version

    @property
    def generated(self) -> str:
        return self._generated

    @property
    def default_strategy(self) -> str:
        return self._default_strategy

    @property
    def strategies(self) -> dict[str, dict]:
        return dict(self._strategies)

    @property
    def assets(self) -> dict[str, AssetLabelConfig]:
        return dict(self._assets)

    def get(self, asset: str) -> AssetLabelConfig | None:
        return self._assets.get(asset)

    def get_strategy_params(self, asset: str) -> dict[str, Any]:
        """Resolve the effective labeling parameters for an asset.

        Returns a dict with keys: strategy, pt, sl, and optionally
        vol_method/atr_period (for TB_v1, these come from triple_barrier.yaml).
        Falls back to default_strategy when asset has no entry.
        """
        cfg = self.get(asset)
        if cfg is None:
            return {"strategy": self._default_strategy}

        result: dict[str, Any] = {"strategy": cfg.strategy}

        if cfg.pt is not None:
            result["pt"] = cfg.pt
        if cfg.sl is not None:
            result["sl"] = cfg.sl

        return result

    def assets_by_status(self, status: str) -> list[AssetLabelConfig]:
        return [a for a in self._assets.values() if a.status == status]

    def assets_by_strategy(self, strategy: str) -> list[AssetLabelConfig]:
        return [a for a in self._assets.values() if a.strategy == strategy]

    def validate_all(self) -> list[str]:
        """Check that all assets have required fields. Returns warnings."""
        warnings: list[str] = []
        for name, cfg in self._assets.items():
            if not cfg.strategy:
                warnings.append(f"{name}: missing strategy")
            if cfg.strategy == "TB_sym" and cfg.pt != cfg.sl:
                warnings.append(f"{name}: TB_sym requires pt == sl")
            if cfg.status not in (
                "exploratory", "validated", "production_candidate",
                "deployed", "deprecated", "retained",
            ):
                warnings.append(f"{name}: unknown status '{cfg.status}'")
        return warnings

    def __repr__(self) -> str:
        n = len(self._assets)
        return f"<LabelStrategyRegistry version={self._version} assets={n}>"
