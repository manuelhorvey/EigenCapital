"""BrokerFactory — creates MT5/Paper broker instances and MT5 data providers.

Extracted from ``PaperTradingEngine.__init__`` (God-class decomposition, Phase 1).
Reduces the engine's initialisation surface by ~40 lines and moves YAML loading
for the MT5 symbol map into a single responsible class.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from paper_trading.config_manager import EngineConfig
from paper_trading.execution.mt5_broker import MT5Broker
from paper_trading.ops.mt5_client import MT5Client

logger = logging.getLogger("eigencapital.broker_factory")

# __file__ is paper_trading/factories/broker_factory.py → 3 dirname up to project root
BASE = str(Path(__file__).resolve().parent.parent.parent)


class BrokerFactory:
    """Creates broker instances and MT5 data providers from engine config.

    Usage::

        broker = BrokerFactory.create_mt5_broker(cfg)
        is_real = True

    or for paper mode::

        broker = PaperBroker(initial_capital=cfg.capital, execution_configs=...)
        is_real = False
    """

    @staticmethod
    def _load_symbol_map(symbol_map_path: str | None) -> dict[str, str]:
        """Load an MT5 symbol map from a YAML file.

        Returns an empty dict if the path is ``None`` or the file does not exist.
        """
        import yaml

        if not symbol_map_path:
            return {}
        map_path = str(Path(BASE) / symbol_map_path)
        if not Path(map_path).exists():
            logger.warning("MT5 symbol map not found at %s", map_path)
            return {}
        with open(map_path) as f:
            symbol_map = yaml.safe_load(f) or {}
        logger.info("Loaded MT5 symbol map from %s (%d symbols)", map_path, len(symbol_map))
        return symbol_map

    @staticmethod
    def create_mt5_broker(cfg: EngineConfig) -> MT5Broker:
        """Build an ``MT5Broker`` from engine configuration.

        Loads the symbol map from ``cfg.mt5.symbol_map_path`` (if set) and
        returns a fully configured broker instance.  Does **not** connect the
        broker — call ``broker.ensure_connected()`` separately.
        """
        mt5 = cfg.mt5
        symbol_map = BrokerFactory._load_symbol_map(mt5.symbol_map_path)

        return MT5Broker(
            account=mt5.account,
            password=mt5.password,
            server=mt5.server,
            symbol_map=symbol_map,
            bridge_host=mt5.bridge_host,
            bridge_port=mt5.bridge_port,
        )

    @staticmethod
    def install_mt5_data_provider(cfg: EngineConfig) -> None:
        """Create an ``MT5Client`` from config and register it as the global data provider.

        Calls ``set_mt5_client()`` on the data-fetcher module so that
        cross-asset macro data (DXY, VIX, etc.) is fetched via MT5 rather
        than yfinance.  Logs a warning if the connection fails — the data
        fetcher will fall back to yfinance.
        """
        from paper_trading.ops.data_fetcher import set_mt5_client

        symbol_map = BrokerFactory._load_symbol_map(cfg.mt5.symbol_map_path)

        client = MT5Client(
            account=cfg.mt5.account,
            password=cfg.mt5.password,
            server=cfg.mt5.server,
            bridge_host=cfg.mt5.bridge_host,
            bridge_port=cfg.mt5.bridge_port,
            symbol_map=symbol_map,
        )
        if not client.connect():
            logger.error("MT5 data provider failed to connect — data fetches will fall back to yfinance")
        set_mt5_client(client, symbol_map)
        logger.info("MT5 data provider installed")
