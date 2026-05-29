import sys

FORBIDDEN_MODULES = frozenset({
    "features.builder",
    "features.lead_lag_features",
    "features.pair_specific",
    "features.publication_lags",
    "features.cot_features",
    "features.base_features",
    "features.trend_features",
    "features.volatility_features",
    "features.mean_reversion_features",
    "features.structural_features",
    "features.interaction_features",
    "features.cross_asset_features",
    "labels.triple_barrier",
    "labels.generator",
    "shared.features",
    "shared.meta_labeling",
    "signals.signal_generator",
    "signals.paper_signal_adapter",
    "signals.signal_filters",
    "signals.thresholding",
    "signals.simple_threshold",
    "signals.alpha_weighting",
    "models.hybrid_ensemble",
    "models.macro_expert_head",
    "models.macro_only",
    "models.mean_reversion.mr_model",
    "portfolio.correlation_clusters",
    "portfolio.hrp_allocator",
    "portfolio.risk_parity",
    "risk.drawdown_controls",
    "risk.exposure_limits",
    "risk.position_sizing",
    "risk.stop_engine",
})

ALLOWED_FEATURE_MODULES = frozenset({
    "features.alpha_features",
    "features.data_fetch",
    "features.labels",
    "features.regime_features",
    "features.archetypes",
    "features.market_structure",
    "features.liquidity_regime",
    "features.macro_narrative",
    "features.fxstreet_fetcher",
})


def check_import_firewall() -> list[str]:
    return [m for m in FORBIDDEN_MODULES if m in sys.modules]


def assert_clean_import_graph():
    violations = check_import_firewall()
    if violations:
        raise RuntimeError(
            f"Import firewall violation: {len(violations)} legacy module(s) loaded:\n"
            + "\n".join(f"  - {m}" for m in violations)
            + "\n\nThese are no longer part of the production pipeline. "
            "Remove the import or migrate to the current alpha_features path."
        )


def verify_feature_pipeline() -> dict:
    loaded = set(sys.modules.keys())
    return {
        "status": "CLEAN" if not check_import_firewall() else "VIOLATION",
        "allowed_features_loaded": sorted(loaded & ALLOWED_FEATURE_MODULES),
        "forbidden_modules_loaded": sorted(loaded & FORBIDDEN_MODULES),
    }
