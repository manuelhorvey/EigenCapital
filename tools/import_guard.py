import sys

# Modules that should NOT be loaded in production. These were deprecated
# refactors — their presence in a fresh import graph is fine (lazy
# archives), but loading them in production code signals regression.
#
# NOTE: ``labels.triple_barrier`` and ``labels.generator`` are the
# CANONICAL vectorized implementations. Their previous classification as
# "forbidden" was a historic mistake; they're explicitly allowed here.

FORBIDDEN_MODULES = frozenset(
    {
        "features.builder",
        "features.lead_lag_features",
        "features.pair_specific",
        "features.publication_lags",
        # "features.cot_features" removed 2026-07-09 (deprecated)
        "features.base_features",
        "features.structural_features",
        "features.interaction_features",
        "shared.features",
        "shared.meta_labeling",
        "signals.signal_generator",
        "signals.paper_signal_adapter",
        "signals.signal_filters",
        "signals.thresholding",
        "signals.alpha_weighting",
        "models.macro_only",
        "portfolio.correlation_clusters",
        "portfolio.hrp_allocator",
        "portfolio.risk_parity",
        "risk.exposure_limits",
        "risk.stop_engine",
    }
)

ALLOWED_FEATURE_MODULES = frozenset(
    {
        "features.alpha_features",
        "features.data_fetch",
        "features.labels",
        "features.regime_features",
        "features.archetypes",
        "features.market_structure",
        "features.liquidity_regime",
        "features.macro_narrative",
        "features.fxstreet_fetcher",
    }
)


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
