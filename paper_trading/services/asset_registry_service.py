import logging

from paper_trading.asset_engine_factory import build_asset_engine
from paper_trading.portfolio_builder import build_paper_portfolio
from shared.registry import StrategyRegistry

logger = logging.getLogger("eigencapital.asset_registry_service")


class AssetRegistryService:
    def __init__(self, engine):
        self.engine = engine

    def build(self) -> dict[str, object]:
        portfolio = build_paper_portfolio(self.engine._engine_cfg.halt)
        _reg = StrategyRegistry.get_instance()
        _reg.register_defaults(list(portfolio.keys()))
        assets = {}
        for name, spec in portfolio.items():
            assets[name] = build_asset_engine(
                ticker=spec["ticker"],
                name=name,
                contract=spec["contract"],
                allocation=spec["alloc"],
                halt_config=spec["halt"],
                config=spec["config"],
                sl_mult=spec.get("sl_mult", 1.0),
                tp_mult=spec.get("tp_mult", 2.5),
                max_depth=spec.get("max_depth", 2),
                regime_geometry=spec.get("regime_geometry", {}),
                context=self.engine._execution_context,
            )
        return assets
