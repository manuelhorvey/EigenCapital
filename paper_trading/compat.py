import importlib

_RESOLVER = {}


def _register(target, source):
    _RESOLVER[target] = source


def __getattr__(name):
    if name in _RESOLVER:
        mod_path, attr = _RESOLVER[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _import(name):
    mod_path, attr = _RESOLVER[name]
    mod = importlib.import_module(mod_path)
    return getattr(mod, attr)


# ── asset_engine.py dependencies ──────────────────────────────────
_register("ExecutionContext", ("paper_trading.execution_context", "ExecutionContext"))
_register("AttributionService", ("paper_trading.services.attribution_service", "AttributionService"))
_register("SignalService", ("paper_trading.services.signal_service", "SignalService"))
_register("MetricsService", ("paper_trading.services.metrics_service", "MetricsService"))
_register("GovernanceService", ("paper_trading.services.governance_service", "GovernanceService"))

# ── engine.py dependencies ────────────────────────────────────────
_register("StateStore", ("paper_trading.state_store", "StateStore"))
_register("SimulationStore", ("paper_trading.ops.simulation_snapshot", "SimulationStore"))
_register("MT5Broker", ("paper_trading.execution.mt5_broker", "MT5Broker"))
_register("MT5Client", ("paper_trading.ops.mt5_client", "MT5Client"))
_register("build_paper_portfolio", ("paper_trading.portfolio_builder", "build_paper_portfolio"))
_register("build_asset_engine", ("paper_trading.asset_engine_factory", "build_asset_engine"))

# ── execution_context.py dependencies ─────────────────────────────
_register("get_config", ("paper_trading.config_manager", "get_config"))
_register("_get_market_data_service", ("paper_trading.ops.market_data_service", "get_market_data_service"))

# ── pipeline.py dependencies ──────────────────────────────────────
_register("build_alpha_features", ("features.alpha_features", "build_alpha_features"))
_register("fetch_asset_data", ("features.data_fetch", "fetch_asset_data"))
_register("fetch_asset_ohlcv", ("features.data_fetch", "fetch_asset_ohlcv"))
_register("fetch_cot_features", ("features.data_fetch", "fetch_cot_features"))
_register("compute_take_profit", ("paper_trading.entry.tp_compiler", "compute_take_profit"))

# ── asset_engine.py additional ────────────────────────────────────
_register(
    "evaluate_regime_conviction_gate", ("paper_trading.governance.conviction_gate", "evaluate_regime_conviction_gate")
)
_register("run_decision_pipeline", ("paper_trading.execution.decision_pipeline", "run_decision_pipeline"))
_register("MetricsService", ("paper_trading.services.metrics_service", "MetricsService"))
_register("GovernanceService", ("paper_trading.services.governance_service", "GovernanceService"))
_register("SignalService", ("paper_trading.services.signal_service", "SignalService"))
