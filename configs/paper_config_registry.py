"""PaperConfigRegistry — production-facing typed registry.

Phase 11.1 of the configuration architecture refactor. Acts as the
backbone for the write-mode split. Reads the new domain tree primarily
(configs/domains/**/*.yaml + configs/environments/*.yaml + configs/modes/*.yaml +
per-asset files). The legacy ``configs/paper_trading.yaml`` was deleted
in Phase 12.7 — all keys are now promoted to domain files.

The ``legacy_path`` parameter is retained for explicit test fixtures
and does not need to point to an existing file.

Differences from ConfigRegistry (Phase 4):
- Phase 4 used the legacy YAML as the bootstrap and domain files as
  template overrides. Phase 11 inverts the relationship: domain files
  are the bootstrap; legacy YAML is a deprecated argument that may not
  exist on disk.
- Adds per-asset file primary loading (Phase 7 introduced the files
  but did not wire production reads).
- Adds environment + mode resolution order (production → live →
  backtest, etc.).

The ``as_legacy_dict()`` method still emits the legacy YAML surface
shape (capital, position_size, defaults, assets, mt5, alerting, ...)
so EngineConfig.from_dict() and ~80 call sites stay valid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from configs.domain_models.assets import AssetConfig
from configs.domain_models.risk import RiskConfig

logger = logging.getLogger("eigencapital.config_registry")

REPO_ROOT = Path(__file__).resolve().parent.parent
DOMAINS_DIR = REPO_ROOT / "configs" / "domains"
# The Phase 12.7 deletion of paper_trading.yaml means there is no default
# legacy mirror on disk. ``load()`` treats a sentinel of ``None`` as
# "no legacy overlay" — the domain tree is read directly.
LEGACY_CONFIG: Path | None = None
ENVIRONMENTS_DIR = REPO_ROOT / "configs" / "environments"
MODES_DIR = DOMAINS_DIR / "modes"


@dataclass
class PaperConfigRegistry:
    """Production-facing typed configuration registry.

    Reads domain files first. The legacy ``paper_trading.yaml`` was
    deleted in Phase 12.7 — all keys are now promoted to domain files.
    The ``legacy_path`` argument is retained for explicit test fixtures
    and does not need to point to an existing file.
    """

    risk: RiskConfig
    assets: dict[str, AssetConfig] = field(default_factory=dict)
    # Promoted infrastructure scalars (data_source, rebalance, …).
    # Read from configs/domains/infrastructure/config.yaml.
    infra: dict[str, Any] = field(default_factory=dict)
    # Promoted MT5 broker config — read from configs/domains/broker/mt5.yaml.
    # The domain file has an "mt5:" wrapper key; stored unwrapped.
    mt5: dict[str, Any] = field(default_factory=dict)
    # Promoted execution/governance config — composed from governance/*.yaml
    # into the execution.governance.* structure EngineConfig.from_dict() expects.
    execution: dict[str, Any] = field(default_factory=dict)
    # Promoted optimizations — read from configs/domains/infrastructure/optimizations.yaml.
    optimizations: dict[str, Any] = field(default_factory=dict)
    # Promoted portfolio config — read from configs/domains/portfolio/weights.yaml.
    # The domain file has a "portfolio:" wrapper; stored unwrapped.
    portfolio: dict[str, Any] = field(default_factory=dict)
    # Promoted governance regime_geometry — read from configs/domains/governance/regime_geometry.yaml
    # as a standalone source. Also composed into execution.governance.regime_geometry for
    # EngineConfig.from_dict() consumption. Used as the default for per-asset regime_geometry
    # when a per-asset file doesn't specify its own.
    regime_geometry: dict[str, Any] = field(default_factory=dict)
    # Calibration config — read from configs/domains/ml/calibration.yaml.
    # Unwrapped from the "calibration:" wrapper key. Emitted in defaults block.
    calibration: dict[str, Any] = field(default_factory=dict)
    # Ensemble config — read from configs/domains/ml/ensemble.yaml.
    # Unwrapped from the "ensemble:" wrapper key. Emitted in defaults block.
    ensemble: dict[str, Any] = field(default_factory=dict)
    # Meta-labeling config — read from configs/domains/ml/meta_labeling.yaml.
    # Unwrapped from the "meta_labeling:" wrapper key. Emitted in defaults block.
    meta_labeling: dict[str, Any] = field(default_factory=dict)
    # Kelly sizing config — read from configs/domains/ml/kelly.yaml.
    # Unwrapped from the "kelly:" wrapper key. Emitted in defaults block.
    kelly: dict[str, Any] = field(default_factory=dict)
    # Triple-barrier label params — read from configs/domains/ml/triple_barrier.yaml.
    # Has a different structure from the other ML files (legacy: + assets: sections).
    # Not emitted in the defaults block — consumed directly by the labeling pipeline.
    label_params: dict[str, Any] = field(default_factory=dict)
    # Alerting channels config — read from configs/domains/infrastructure/alerts.yaml.
    # Unwrapped from the "alerting:" wrapper key. Emitted as top-level key for
    # consumption by the alerting manager.
    alerting: dict[str, Any] = field(default_factory=dict)
    # Stacking config — read from configs/domains/risk/sizing.yaml (stacking: key).
    # Defaults-shaped key. Emitted in the defaults block.
    stacking: dict[str, Any] = field(default_factory=dict)
    # Spread gate config — read from configs/domains/execution/spreads.yaml.
    # Defaults-shaped key. Emitted in the defaults block.
    spread_gate: dict[str, Any] = field(default_factory=dict)
    # Session gate config — read from configs/domains/execution/sessions.yaml.
    # Defaults-shaped key. Emitted in the defaults block.
    session_gate: dict[str, Any] = field(default_factory=dict)
    # Liquidity regime config — read from configs/domains/governance/liquidity.yaml.
    # Also composed into execution.governance.liquidity_config for EngineConfig.
    liquidity_config: dict[str, Any] = field(default_factory=dict)
    # Narrative / macro config — read from configs/domains/governance/narrative.yaml.
    # Also composed into execution.governance.narrative_config for EngineConfig.
    narrative_config: dict[str, Any] = field(default_factory=dict)
    # Mode overrides — read from configs/domains/modes/*.yaml.
    # Each file becomes a mode entry keyed by its stem. Top-level key.
    modes: dict[str, Any] = field(default_factory=dict)
    # Environment overlays — read from configs/environments/*.yaml.
    # Each file becomes an environment entry keyed by its stem.
    environments: dict[str, Any] = field(default_factory=dict)
    # Active environment name. Used by as_legacy_dict() to apply the
    # final overlay layer. Default is "paper".
    environment_name: str = "paper"
    # Carrier bag for keys still exclusive to the legacy YAML. Used by
    # as_legacy_dict() so operator-edits to the legacy file keep round-
    # tripping until they land in a domain file.
    legacy_extras: dict[str, Any] = field(default_factory=dict)
    # Asset source: either "domain" (preferred) or "legacy".
    asset_sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        legacy_path: Path | None = None,
        domains_dir: Path | None = None,
        environments_dir: Path | None = None,
        modes_dir: Path | None = None,
        environment: str = "paper",
    ) -> PaperConfigRegistry:
        legacy_path = legacy_path or LEGACY_CONFIG
        domains_dir = domains_dir or DOMAINS_DIR
        environments_dir = environments_dir or ENVIRONMENTS_DIR
        modes_dir = modes_dir or MODES_DIR

        legacy_raw: dict[str, Any] = {}
        if legacy_path is not None and legacy_path.exists():
            legacy_raw = yaml.safe_load(legacy_path.read_text()) or {}

        # Step 1: build a normalized base config dict from the domain
        # tree (Phase 11.1 inverts Phase 4 precedence — domain > legacy).
        base: dict[str, Any] = {}

        # Step 1a: capital
        if (domains_dir / "risk" / "capital.yaml").exists():
            cap = yaml.safe_load((domains_dir / "risk" / "capital.yaml").read_text()) or {}
            for k in ("capital", "portfolio_drawdown_limit", "position_size"):
                if k in cap:
                    base[k] = cap[k]

        # Fall back to legacy for any key not in domain
        for k in ("capital", "portfolio_drawdown_limit", "position_size"):
            base.setdefault(k, legacy_raw.get(k))

        # Step 1b: defaults via SizingConfig + adaptive_exit overlay
        defaults_blk: dict[str, Any] = {}
        sizing_keys: set[str] = set()
        if (domains_dir / "risk" / "sizing.yaml").exists():
            sz = yaml.safe_load((domains_dir / "risk" / "sizing.yaml").read_text()) or {}
            defaults_blk.update(sz)
            sizing_keys.update(sz.keys())
        legacy_defaults = legacy_raw.get("defaults") or {}
        for k, v in legacy_defaults.items():
            if k in sizing_keys:
                defaults_blk.setdefault(k, v)
        if (domains_dir / "risk" / "exits.yaml").exists():
            ae = yaml.safe_load((domains_dir / "risk" / "exits.yaml").read_text()) or {}
            defaults_blk["adaptive_exit"] = {**legacy_defaults.get("adaptive_exit", {}), **(ae.get("default") or {})}
        else:
            defaults_blk.setdefault("adaptive_exit", legacy_defaults.get("adaptive_exit", {}))

        base["defaults"] = defaults_blk

        # Step 1c: halt via halt.yaml (Phase 12.2c)
        halt_raw: dict[str, Any] | None = None
        halt_path = domains_dir / "risk" / "halt.yaml"
        if halt_path.exists():
            halt_raw_data = yaml.safe_load(halt_path.read_text()) or {}
            legacy_halt = legacy_raw.get("halt") or {}
            halt_raw = {**legacy_halt, **halt_raw_data}

        # Step 1d: build risk from the composed defaults + halt override
        risk = RiskConfig.from_legacy(base, halt_override=halt_raw)

        # Step 1e: infrastructure config (Phase 12.3)
        infra_keys = ("data_source", "rebalance", "research_mode", "retrain_freq", "retrain_window", "api_token")
        infra: dict[str, Any] = {k: None for k in infra_keys}
        infra_path = domains_dir / "infrastructure" / "config.yaml"
        if infra_path.exists():
            infra_data = yaml.safe_load(infra_path.read_text()) or {}
            for k in infra_keys:
                if k in infra_data:
                    infra[k] = infra_data[k]
        for k in infra_keys:
            if infra.get(k) is None:
                infra[k] = legacy_raw.get(k, "" if k == "api_token" else None)

        # Step 1f: MT5 broker config — configs/domains/broker/mt5.yaml
        # The domain file has an "mt5:" wrapper; we store the unwrapped value.
        mt5: dict[str, Any] = {}
        mt5_path = domains_dir / "broker" / "mt5.yaml"
        if mt5_path.exists():
            mt5_raw = yaml.safe_load(mt5_path.read_text()) or {}
            mt5 = mt5_raw.get("mt5", {})
        # Fall back to legacy for any missing key
        legacy_mt5 = legacy_raw.get("mt5") or {}
        for k in ("enabled", "bridge_host", "bridge_port", "symbol_map_path"):
            mt5.setdefault(k, legacy_mt5.get(k))

        # Step 1g: governance regime_geometry — configs/domains/governance/regime_geometry.yaml
        # Read as a standalone source for per-asset fallback. Also composed
        # into execution.governance.regime_geometry in step 1h for EngineConfig.
        regime_geometry_defaults: dict[str, Any] = {}
        rg_path = domains_dir / "governance" / "regime_geometry.yaml"
        if rg_path.exists():
            regime_geometry_defaults = yaml.safe_load(rg_path.read_text()) or {}

        # Step 1h: execution/governance — composed from governance/*.yaml
        # Reconstruct the execution.governance.* structure that
        # EngineConfig.from_dict() expects:
        #   execution.governance.regime_geometry
        #   execution.governance.liquidity_config
        #   execution.governance.narrative_config
        # Also extracted as standalone fields (liquidity_config, narrative_config)
        # for direct registry access.
        execution: dict[str, Any] = {}
        execution_governance: dict[str, Any] = {}

        if regime_geometry_defaults:
            execution_governance["regime_geometry"] = regime_geometry_defaults

        # liquidity_config — standalone + composed
        liquidity_config: dict[str, Any] = {}
        liq_path = domains_dir / "governance" / "liquidity.yaml"
        if liq_path.exists():
            liquidity_config = yaml.safe_load(liq_path.read_text()) or {}
        execution_governance["liquidity_config"] = liquidity_config

        # narrative_config — standalone + composed
        narrative_config: dict[str, Any] = {}
        nar_path = domains_dir / "governance" / "narrative.yaml"
        if nar_path.exists():
            narrative_config = yaml.safe_load(nar_path.read_text()) or {}
        execution_governance["narrative_config"] = narrative_config

        # Legacy fallback for governance keys
        legacy_execution = legacy_raw.get("execution") or {}
        legacy_governance = legacy_execution.get("governance") or {}
        legacy_liq = legacy_governance.get("liquidity_config") or {}
        for k, v in legacy_liq.items():
            liquidity_config.setdefault(k, v)
        legacy_nar = legacy_governance.get("narrative_config") or {}
        for k, v in legacy_nar.items():
            narrative_config.setdefault(k, v)

        if execution_governance:
            execution["governance"] = execution_governance
        # Fall back to legacy for any missing top-level key
        for k, v in legacy_execution.items():
            execution.setdefault(k, v)

        # Step 1h: optimizations — configs/domains/infrastructure/optimizations.yaml
        optimizations: dict[str, Any] = {}
        opt_path = domains_dir / "infrastructure" / "optimizations.yaml"
        if opt_path.exists():
            opt_raw = yaml.safe_load(opt_path.read_text()) or {}
            optimizations.update(opt_raw)
        # Fall back to legacy
        legacy_opts = legacy_raw.get("optimizations") or {}
        for k, v in legacy_opts.items():
            optimizations.setdefault(k, v)

        # Step 1i: portfolio config — configs/domains/portfolio/weights.yaml
        # The domain file has a "portfolio:" wrapper; store unwrapped.
        portfolio: dict[str, Any] = {}
        port_path = domains_dir / "portfolio" / "weights.yaml"
        if port_path.exists():
            port_raw = yaml.safe_load(port_path.read_text()) or {}
            portfolio = port_raw.get("portfolio", {})
        # Fall back to legacy
        legacy_port = legacy_raw.get("portfolio") or {}
        for k, v in legacy_port.items():
            portfolio.setdefault(k, v)

        # Step 1i-bis: factor model config — configs/domains/portfolio/factor_model.yaml
        # Factor exposure limits for P3 factor-constrained portfolio optimization.
        # Merged into the portfolio dict as portfolio.factor_exposure_limits.
        fm_path = domains_dir / "portfolio" / "factor_model.yaml"
        if fm_path.exists():
            fm_raw = yaml.safe_load(fm_path.read_text()) or {}
            fm_promoted = fm_raw.get("portfolio", {})
            if "factor_exposure_limits" in fm_promoted:
                # Per-asset factor_exposure_limits in weights.yaml take precedence
                # if they exist (unlikely, but respect the override chain).
                portfolio.setdefault("factor_exposure_limits", fm_promoted["factor_exposure_limits"])

        # Step 1j: calibration — configs/domains/ml/calibration.yaml
        calibration: dict[str, Any] = {}
        cal_path = domains_dir / "ml" / "calibration.yaml"
        if cal_path.exists():
            cal_raw = yaml.safe_load(cal_path.read_text()) or {}
            calibration = cal_raw.get("calibration", {})

        # Step 1k: ensemble — configs/domains/ml/ensemble.yaml
        ensemble: dict[str, Any] = {}
        ens_path = domains_dir / "ml" / "ensemble.yaml"
        if ens_path.exists():
            ens_raw = yaml.safe_load(ens_path.read_text()) or {}
            ensemble = ens_raw.get("ensemble", {})

        # Step 1l: meta_labeling — configs/domains/ml/meta_labeling.yaml
        meta_labeling: dict[str, Any] = {}
        ml_path = domains_dir / "ml" / "meta_labeling.yaml"
        if ml_path.exists():
            ml_raw = yaml.safe_load(ml_path.read_text()) or {}
            meta_labeling = ml_raw.get("meta_labeling", {})

        # Step 1l-bis: kelly sizing — configs/domains/ml/kelly.yaml
        # Unwrapped from the "kelly:" wrapper key. Emitted in defaults block.
        kelly: dict[str, Any] = {}
        kelly_path = domains_dir / "ml" / "kelly.yaml"
        if kelly_path.exists():
            kelly_raw = yaml.safe_load(kelly_path.read_text()) or {}
            kelly = kelly_raw.get("kelly", {})

        # Step 1m: triple_barrier label params — configs/domains/ml/triple_barrier.yaml
        # Stored as-is (has legacy: + assets: sections, not a defaults-shaped key).
        label_params: dict[str, Any] = {}
        tb_path = domains_dir / "ml" / "triple_barrier.yaml"
        if tb_path.exists():
            label_params = yaml.safe_load(tb_path.read_text()) or {}

        # Step 1n: alerting channels — configs/domains/infrastructure/alerts.yaml
        # Unwrapped from the "alerting:" wrapper key.
        alerting: dict[str, Any] = {}
        alerts_path = domains_dir / "infrastructure" / "alerts.yaml"
        if alerts_path.exists():
            alerts_raw = yaml.safe_load(alerts_path.read_text()) or {}
            alerting = alerts_raw.get("alerting", {})
        # Fall back to legacy
        legacy_alerting = legacy_raw.get("alerting") or {}
        for k in ("channels",):
            if k in legacy_alerting and k not in alerting:
                alerting[k] = legacy_alerting[k]

        # Step 1n(bis): stacking — read from sizing.yaml defaults_blk
        stacking: dict[str, Any] = defaults_blk.get("stacking", {})

        # Step 1o: spread_gate — configs/domains/execution/spreads.yaml
        # No wrapper key — stored as-is. Emitted in defaults block.
        spread_gate: dict[str, Any] = {}
        sg_path = domains_dir / "execution" / "spreads.yaml"
        if sg_path.exists():
            spread_gate = yaml.safe_load(sg_path.read_text()) or {}

        # Step 1p: session_gate — configs/domains/execution/sessions.yaml
        # No wrapper key — stored as-is. Emitted in defaults block.
        session_gate: dict[str, Any] = {}
        ss_path = domains_dir / "execution" / "sessions.yaml"
        if ss_path.exists():
            session_gate = yaml.safe_load(ss_path.read_text()) or {}

        # Step 1q: mode overrides — configs/domains/modes/*.yaml
        # Each file becomes a mode entry keyed by its stem (e.g. production.yaml → modes["production"]).
        modes: dict[str, Any] = {}
        modes_dir_path = domains_dir / "modes"
        if modes_dir_path.exists():
            for mode_file in sorted(modes_dir_path.glob("[!_]*.yaml")):
                mode_name = mode_file.stem
                modes[mode_name] = yaml.safe_load(mode_file.read_text()) or {}
        # Fall back to legacy for any mode not in domain files
        legacy_modes = legacy_raw.get("modes") or {}
        for k, v in legacy_modes.items():
            modes.setdefault(k, v)

        # Step 1r: environment overlays — configs/environments/*.yaml
        # Each file becomes an environment entry keyed by its stem (e.g. paper.yaml → environments["paper"]).
        # The active environment is applied as the final overlay in as_legacy_dict().
        environments: dict[str, Any] = {}
        if environments_dir.exists():
            for env_file in sorted(environments_dir.glob("[!_]*.yaml")):
                env_name = env_file.stem
                environments[env_name] = yaml.safe_load(env_file.read_text()) or {}

        # Step 2: asset loading — **authoritative source is _index.yaml**.
        # _index.yaml defines the canonical asset list. Per-asset YAML files
        # provide the config data for each listed asset. Any per-asset file
        # present on disk but absent from _index.yaml is silently ignored.
        # Legacy asset blocks are only used as a fallback for index-listed
        # assets that lack a per-asset domain file.
        #
        # Pass regime_geometry_defaults so per-asset composition can use
        # the governance default when a per-asset file lacks regime_geometry.
        index_names: set[str] | None = None
        index_path = domains_dir / "assets" / "_index.yaml"
        if index_path.exists():
            index_raw = yaml.safe_load(index_path.read_text()) or {}
            raw_list = index_raw.get("assets", [])
            if raw_list:
                index_names = set(raw_list)
        if index_names is None:
            # No _index.yaml (e.g. test fixture without one) —
            # fall back to filesystem scanning for backward compat
            pass
        merged_assets, asset_sources = _merge_assets(
            domains_dir=domains_dir,
            legacy_assets=legacy_raw.get("assets") or {},
            defaults_exit=risk.exits_default,
            governance_regime_geometry=regime_geometry_defaults,
            index_names=index_names,
        )

        # Step 3: collect legacy_extras — keys not yet in a domain file
        promoted_top: set[str] = {
            "capital",
            "position_size",
            "portfolio_drawdown_limit",
            "halt",
            "defaults",
            "assets",
            # Phase 12.3: infra/config.yaml
            "data_source",
            "rebalance",
            "research_mode",
            "retrain_freq",
            "retrain_window",
            "api_token",
            # Phase 12.6: broker/mt5.yaml, governance/*.yaml, infra/optimizations.yaml
            "mt5",
            "execution",
            "optimizations",
            # portfolio/weights.yaml
            "portfolio",
            # governance/regime_geometry.yaml
            "regime_geometry",
            # infrastructure/alerts.yaml
            "alerting",
            # modes/*.yaml
            "modes",
        }
        pruned_top: set[str] = set()
        # ``kelly`` was previously in pruned_top but is now promoted
        # to configs/domains/ml/kelly.yaml (P2 config promotion).
        # It's handled via promoted_defaults since it lives inside
        # ``defaults`` in the legacy YAML, not as a top-level key.
        # ``alerting`` was previously in pruned_top but is now promoted
        # to configs/domains/infrastructure/alerts.yaml.
        # calibration, ensemble, meta_labeling were previously in
        # pruned_top but are now promoted (ML domain files). They're
        # handled via promoted_defaults at the defaults level, not
        # top-level promoted_top, since they live inside ``defaults``
        # in the legacy YAML (never were top-level keys).
        ml_keys: set[str] = {"calibration", "ensemble", "meta_labeling", "kelly"}
        exec_gate_keys: set[str] = {"spread_gate", "session_gate", "stacking"}
        promoted_defaults: set[str] = set(defaults_blk.keys()) | {"adaptive_exit", "sell_only_assets"}
        promoted_defaults |= set(infra_keys) | ml_keys | exec_gate_keys
        legacy_extras: dict[str, Any] = {}
        for k, v in legacy_raw.items():
            if k not in promoted_top and k not in pruned_top:
                legacy_extras[k] = v
        for k in list(legacy_defaults.keys()):
            if k not in promoted_defaults and k not in legacy_extras:
                legacy_extras[k] = legacy_defaults[k]

        return cls(
            risk=risk,
            assets=merged_assets,
            infra=infra,
            mt5=mt5,
            execution=execution,
            optimizations=optimizations,
            portfolio=portfolio,
            regime_geometry=regime_geometry_defaults,
            calibration=calibration,
            ensemble=ensemble,
            meta_labeling=meta_labeling,
            kelly=kelly,
            label_params=label_params,
            alerting=alerting,
            stacking=stacking,
            spread_gate=spread_gate,
            session_gate=session_gate,
            liquidity_config=liquidity_config,
            narrative_config=narrative_config,
            modes=modes,
            environments=environments,
            environment_name=environment,
            legacy_extras=legacy_extras,
            asset_sources=asset_sources,
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        """Re-emit the legacy paper_trading.yaml shape losslessly."""
        body: dict[str, Any] = {
            "capital": self.risk.capital.initial,
            "position_size": self.risk.capital.position_size,
            "portfolio_drawdown_limit": self.risk.capital.portfolio_drawdown_limit,
            "halt": {
                "drawdown": self.risk.halt.drawdown,
                "monthly_pf": self.risk.halt.monthly_pf,
                "signal_drought": self.risk.halt.signal_drought,
                "prob_drift": self.risk.halt.prob_drift,
                "expected_prob_conf": self.risk.halt.expected_prob_conf,
                "prob_drift_min_samples": self.risk.halt.prob_drift_min_samples,
            },
        }

        defaults: dict[str, Any] = {}
        sizing_field_names = set(self.risk.sizing.__dataclass_fields__)
        for f in self.risk.sizing.__dataclass_fields__:
            defaults[f] = getattr(self.risk.sizing, f)

        ae = self.risk.exits_default
        defaults["adaptive_exit"] = {
            "enabled": ae.enabled,
            "be_lock_r": ae.be_lock_r,
            "trail_activation_r": ae.trail_activation_r,
            "trail_retrace_pct": ae.trail_retrace_pct,
            "max_hold_candles": ae.max_hold_candles,
            "time_decay_start": ae.time_decay_start,
            "scale_out_fraction": ae.scale_out_fraction,
            "scale_out_r": ae.scale_out_r,
        }
        defaults["sell_only_assets"] = sorted(self.risk.sell_only.assets)

        for k, v in self.legacy_extras.items():
            if k in ("mode", "modes", "mt5", "alerting", "ensemble", "optimizations", "execution"):
                continue
            if k not in sizing_field_names and k != "adaptive_exit" and k != "sell_only_assets":
                defaults[k] = v

        # ML domain files — emitted in the defaults block
        if self.calibration:
            defaults["calibration"] = self.calibration
        if self.ensemble:
            defaults["ensemble"] = self.ensemble
        if self.meta_labeling:
            defaults["meta_labeling"] = self.meta_labeling

        # Stacking config — emitted in the defaults block
        if self.stacking:
            defaults["stacking"] = self.stacking

        # Kelly config — emitted in the defaults block
        if self.kelly:
            defaults["kelly"] = self.kelly

        # Execution gate configs — emitted in the defaults block
        if self.spread_gate:
            defaults["spread_gate"] = self.spread_gate
        if self.session_gate:
            defaults["session_gate"] = self.session_gate
        body["defaults"] = defaults

        body["assets"] = {name: a.to_legacy_dict() for name, a in self.assets.items()}

        # Top-level legacy extras
        for k, v in self.legacy_extras.items():
            if k in ("mode", "modes"):
                body[k] = v

        # Phase 12.3: promoted infrastructure scalars
        for k in ("data_source", "rebalance", "research_mode", "retrain_freq", "retrain_window", "api_token"):
            v = self.infra.get(k)
            if v is not None:
                body[k] = v

        # Phase 12.6: promoted MT5, execution/governance, optimizations, portfolio
        if self.mt5:
            body["mt5"] = self.mt5
        if self.execution:
            body["execution"] = self.execution
        if self.optimizations:
            body["optimizations"] = self.optimizations
        if self.portfolio:
            body["portfolio"] = self.portfolio
        # Alerting channels — promoted from infrastructure/alerts.yaml
        if self.alerting:
            body["alerting"] = self.alerting

        # Mode overrides — promoted from modes/*.yaml
        if self.modes:
            body["modes"] = self.modes

        # Note: regime_geometry is already composed into
        # execution.governance.regime_geometry above. No standalone
        # emission needed — it was never a top-level legacy key.

        # Environment overlay (final layer, highest priority)
        env = self.environments.get(self.environment_name)
        if env:
            _deep_overlay(body, env)

        return body

    def summary(self) -> dict[str, Any]:
        domain_assets = sum(1 for s in self.asset_sources.values() if s == "domain")
        legacy_assets = sum(1 for s in self.asset_sources.values() if s == "legacy")
        return {
            "assets": len(self.assets),
            "domain_assets": domain_assets,
            "legacy_assets": legacy_assets,
            "sell_only": sorted(self.risk.sell_only.assets),
            "sizing_fields": len(self.risk.sizing.__dataclass_fields__),
            "legacy_extras": sorted(self.legacy_extras.keys()),
            "environments": sorted(self.environments.keys()),
            "environment_name": self.environment_name,
        }


# ── Helpers ──────────────────────────────────────────────────────────


def _deep_overlay(target: dict, source: dict) -> None:
    """In-place merge: ``source`` overrides ``target`` at every level."""
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_overlay(target[k], v)
        else:
            target[k] = v


# ── Asset merging ────────────────────────────────────────────────────


_DEFAULT_BLOCK_KEYS = ("shadow_sltp", "dynamic_sltp", "adaptive_exit")


def _merge_assets(
    *,
    domains_dir: Path,
    legacy_assets: dict[str, dict],
    defaults_exit,
    governance_regime_geometry: dict[str, Any] | None = None,
    index_names: set[str] | None = None,
) -> tuple[dict[str, AssetConfig], dict[str, str]]:
    """Merge per-asset configs into the registry.

    Parameters
    ----------
    index_names
        Authoritative set of asset names from ``_index.yaml``.
        When provided, only assets in this set are loaded. Per-asset
        files on disk that are not in the index are silently ignored.
        When ``None``, falls back to filesystem scanning (backward
        compatibility for tests that don't have ``_index.yaml``).
    """
    assets_out: dict[str, AssetConfig] = {}
    sources: dict[str, str] = {}

    defaults_yaml: dict[str, dict] = {}
    defaults_path = domains_dir / "assets" / "_defaults.yaml"
    if defaults_path.exists():
        defaults_yaml = yaml.safe_load(defaults_path.read_text()) or {}

    per_asset_files = {fn.stem: fn for fn in (domains_dir / "assets").glob("[!_]*.yaml")}

    if index_names is not None:
        # _index.yaml is authoritative — only load assets listed in it
        all_names = index_names
        # Log a warning for index-listed assets without a per-asset file
        for name in sorted(all_names):
            if name not in per_asset_files and name not in legacy_assets:
                logger.warning("Asset '%s' listed in _index.yaml but no per-asset YAML or legacy block found", name)
    else:
        all_names = set(per_asset_files) | set(legacy_assets)

    for name in sorted(all_names):
        per_file = per_asset_files.get(name)
        legacy_block = legacy_assets.get(name) or {}

        if per_file is not None:
            unique = yaml.safe_load(per_file.read_text()) or {}
            sources[name] = "domain"
        elif legacy_block:
            unique = _legacy_asset_to_unique(legacy_block)
            sources[name] = "legacy"
        else:
            continue

        composite = _compose_asset(unique, defaults_yaml, governance_regime_geometry)
        assets_out[name] = AssetConfig.from_dict(name, composite, defaults_exit)

    return assets_out, sources


def _legacy_asset_to_unique(legacy_block: dict) -> dict:
    carry = {k: v for k, v in legacy_block.items() if k not in ("config", "regime_geometry")}
    return carry


def _compose_asset(unique: dict, defaults_yaml: dict, governance_regime_geometry: dict[str, Any] | None = None) -> dict:
    """Compose a per-asset entry with shared defaults.

    Parameters
    ----------
    unique
        Per-asset unique keys (ticker, allocation, sl/tp, regime_geometry, …).
    defaults_yaml
        Shared defaults from _defaults.yaml (shadow_sltp, dynamic_sltp, adaptive_exit).
    governance_regime_geometry
        Optional governance-level regime_geometry default. Used as the fallback
        when the per-asset file doesn't define its own regime_geometry.
    """
    composite = dict(unique)
    # Regime geometry: per-asset file wins; governance default is fallback
    if governance_regime_geometry and "regime_geometry" not in composite:
        composite["regime_geometry"] = governance_regime_geometry
    composite.setdefault("adaptive_exit", defaults_yaml.get("adaptive_exit", {}))
    composite.setdefault("shadow_sltp", defaults_yaml.get("shadow_sltp", {}))
    composite.setdefault("dynamic_sltp", defaults_yaml.get("dynamic_sltp", {}))
    composite["config"] = {
        "shadow_sltp": composite.pop("shadow_sltp"),
        "dynamic_sltp": composite.pop("dynamic_sltp"),
        "adaptive_exit": composite.pop("adaptive_exit"),
    }
    return composite
