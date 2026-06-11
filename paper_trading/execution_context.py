from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionContext:
    """Cross-cutting services shared by all AssetEngine instances.

    Bundles the shared engine services so they can be passed as a single
    object to ``build_asset_engine()`` and ``AssetEngine.__init__()``
    instead of as separate positional parameters.

    All fields have sensible fallbacks to module-level singletons,
    so creating an ``ExecutionContext()`` with no arguments is safe
    for tests and REPL usage.
    """

    state_store: object | None = None
    execution_bridge: object | None = None
    market_data_service: object | None = None
    engine_config: object | None = None

    def get_state_store(self) -> object:
        if self.state_store is not None:
            return self.state_store
        import os

        from paper_trading.state_store import StateStore

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return StateStore(base)

    def get_execution_bridge(self) -> object | None:
        return self.execution_bridge

    def get_market_data_service(self) -> object:
        if self.market_data_service is not None:
            return self.market_data_service
        from paper_trading.ops.market_data_service import get_market_data_service

        return get_market_data_service()

    def get_engine_config(self) -> object:
        if self.engine_config is not None:
            return self.engine_config
        from paper_trading.config_manager import get_config

        return get_config()
