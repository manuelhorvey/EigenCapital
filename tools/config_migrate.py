"""
config_migrate.py — derive the new domain tree from legacy paper_trading.yaml.

Phase 0 scaffolding. Pure read of the legacy file; no destructive output.
In Phase 4 this will graduate from preview-only to committed output.

Usage:
    python tools/config_migrate.py --dry-run           # show plan, no write
    python tools/config_migrate.py --output configs/domains/   # write chosen tree
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_CONFIG = REPO_ROOT / "configs" / "paper_trading.yaml"


@dataclass
class MigrationPlan:
    """Structured description of which legacy keys land in which domain file."""

    risk_capital: dict = field(default_factory=dict)
    risk_halt: dict = field(default_factory=dict)
    risk_sizing: dict = field(default_factory=dict)
    risk_exits: dict = field(default_factory=dict)
    portfolio_weights: dict = field(default_factory=dict)
    ml_ensemble: dict = field(default_factory=dict)
    ml_calibration: dict = field(default_factory=dict)
    ml_meta_labeling: dict = field(default_factory=dict)
    broker_mt5: dict = field(default_factory=dict)
    execution_spreads: dict = field(default_factory=dict)
    execution_sessions: dict = field(default_factory=dict)
    execution_simulation: dict = field(default_factory=dict)
    governance_regime: dict = field(default_factory=dict)
    governance_liquidity: dict = field(default_factory=dict)
    governance_narrative: dict = field(default_factory=dict)
    infrastructure_alerts: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)
    assets_index: list[str] = field(default_factory=list)
    unclassified: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "risk": {
                "capital": bool(self.risk_capital),
                "halt": bool(self.risk_halt),
                "sizing": bool(self.risk_sizing),
                "exits": bool(self.risk_exits),
            },
            "portfolio": {"weights": bool(self.portfolio_weights)},
            "ml": {
                "ensemble": bool(self.ml_ensemble),
                "calibration": bool(self.ml_calibration),
                "meta_labeling": bool(self.ml_meta_labeling),
            },
            "broker": {"mt5": bool(self.broker_mt5)},
            "execution": {
                "spreads": bool(self.execution_spreads),
                "sessions": bool(self.execution_sessions),
                "simulation": bool(self.execution_simulation),
            },
            "governance": {
                "regime": bool(self.governance_regime),
                "liquidity": bool(self.governance_liquidity),
                "narrative": bool(self.governance_narrative),
            },
            "infrastructure": {"alerts": bool(self.infrastructure_alerts)},
            "modes": list(self.modes.keys()),
            "assets_indexed": len(self.assets_index),
            "unclassified_keys": list(self.unclassified.keys()),
        }


def _pick(d: dict, *keys: str) -> dict:
    out: dict = {}
    for k in keys:
        if k in d and d[k] is not None:
            out[k] = d[k]
    return out


def plan_from_legacy(data: dict) -> MigrationPlan:
    plan = MigrationPlan()
    plan.risk_capital = _pick(data, "capital", "portfolio_drawdown_limit", "position_size")
    defaults = data.get("defaults", {}) or {}

    sizing_keys = (
        "rolling_window_bars",
        "churn_ratio_threshold",
        "cooldown_half_life_hours",
        "cooldown_max_penalty_pct",
        "entry_defer_max_bars",
        "min_flip_interval_bars",
        "max_entry_slippage_pct",
        "profit_lock_threshold_pct",
        "max_position_pct_of_equity",
        "max_risk_per_trade_pct",
        "min_viable_position_pct",
        "size_taper_start_dd",
        "size_taper_end_dd",
        "size_taper_min",
        "max_positions_per_asset",
        "portfolio_max_leverage",
        "portfolio_leverage_tolerance",
        "mt5_leverage_budget_enabled",
        "mt5_leverage_budget_soft",
        "net_short_concentration_threshold",
        "mt5_enable_max_risk_per_trade_pct",
        "mt5_max_risk_per_trade_pct",
        "mt5_bypass_risk_cap_at_min_lot",
        "min_confidence",
    )
    plan.risk_sizing = _pick(defaults, *sizing_keys)

    if "adaptive_exit" in defaults:
        plan.risk_exits = {"default": defaults["adaptive_exit"]}

    plan.portfolio_weights = _pick(data, "portfolio") or {
        "weight_method": (data.get("portfolio", {}).get("weight_method", "factor_constrained_v2"))
    }
    if data.get("modes"):
        first_mode = next(iter(data["modes"].values()), {})
        if "factor_exposure_limits" in first_mode:
            plan.portfolio_weights.setdefault("factor_exposure_limits", first_mode["factor_exposure_limits"])

    plan.ml_ensemble = _pick(data, "ensemble")
    plan.ml_calibration = _pick(data, "calibration")
    plan.ml_meta_labeling = _pick(data, "meta_labeling")

    plan.broker_mt5 = _pick(data, "mt5")

    if "spread_gate" in defaults:
        plan.execution_spreads = defaults["spread_gate"]
    if "session_gate" in defaults:
        plan.execution_sessions = defaults["session_gate"]

    exec_block = data.get("execution") or {}
    gov = exec_block.get("governance") or {}
    if "regime_geometry" in gov:
        plan.governance_regime = gov["regime_geometry"]
    if "liquidity_config" in gov:
        plan.governance_liquidity = gov["liquidity_config"]
    if "narrative_config" in gov:
        plan.governance_narrative = gov["narrative_config"]

    plan.infrastructure_alerts = _pick(data, "alerting")

    plan.modes = data.get("modes") or {}

    assets = data.get("assets") or {}
    plan.assets_index = list(assets.keys())

    plan.unclassified = _pick(
        data,
        "optimizations",
        "rebalance",
        "retrain_freq",
        "retrain_window",
        "data_source",
        "api_token",
    )

    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy config to domain tree")
    parser.add_argument("--dry-run", action="store_true", help="Plan only - no writes")
    parser.add_argument("--config", type=Path, default=LEGACY_CONFIG, help="Legacy config path")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for new tree (e.g. configs/domains)",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"config_migrate: legacy file not found: {args.config}", file=sys.stderr)
        return 1

    data = yaml.safe_load(args.config.read_text()) or {}
    plan = plan_from_legacy(data)
    summary = plan.summary()

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    if args.output is None:
        print("--output is required when --dry-run is not set", file=sys.stderr)
        return 2

    args.output.mkdir(parents=True, exist_ok=True)
    for section in (
        "risk",
        "portfolio",
        "ml",
        "broker",
        "execution",
        "governance",
        "infrastructure",
    ):
        (args.output / section).mkdir(exist_ok=True)

    out_map = {
        "risk/capital.yaml": plan.risk_capital,
        "risk/sizing.yaml": plan.risk_sizing,
        "risk/exits.yaml": plan.risk_exits,
        "portfolio/weights.yaml": plan.portfolio_weights,
        "ml/ensemble.yaml": plan.ml_ensemble,
        "ml/calibration.yaml": plan.ml_calibration,
        "ml/meta_labeling.yaml": plan.ml_meta_labeling,
        "broker/mt5.yaml": plan.broker_mt5,
        "execution/spreads.yaml": plan.execution_spreads,
        "execution/sessions.yaml": plan.execution_sessions,
        "governance/regime_geometry.yaml": plan.governance_regime,
        "governance/liquidity.yaml": plan.governance_liquidity,
        "governance/narrative.yaml": plan.governance_narrative,
        "infrastructure/alerts.yaml": plan.infrastructure_alerts,
    }
    for rel, payload in out_map.items():
        target = args.output / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(payload, sort_keys=False))

    if plan.modes:
        (args.output / "modes").mkdir(exist_ok=True)
        for mode_name, mode_payload in plan.modes.items():
            (args.output / "modes" / f"{mode_name}.yaml").write_text(yaml.safe_dump(mode_payload, sort_keys=False))

    if plan.assets_index:
        (args.output / "assets").mkdir(exist_ok=True)
        (args.output / "assets" / "_index.yaml").write_text(
            yaml.safe_dump({"assets": plan.assets_index}, sort_keys=False)
        )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
