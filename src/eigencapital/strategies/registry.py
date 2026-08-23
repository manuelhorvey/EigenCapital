"""Strategy Registry — central registry for strategy implementations.

Usage:
    registry = StrategyRegistry()
    registry.register(MyStrategy)
    strategy_cls = registry.get("trend_v1")
"""

from __future__ import annotations

from typing import Dict, Type

from eigencapital.strategies.base import BaseStrategy


class StrategyNotFoundError(KeyError):
    """Raised when strategy_id is not in the registry."""

    def __init__(self, strategy_id: str) -> None:
        super().__init__(f"Strategy '{strategy_id}' not found in registry")
        self.strategy_id = strategy_id


class StrategyRegistry:
    """Central registry for strategy implementations."""

    def __init__(self) -> None:
        self._strategies: Dict[str, Type[BaseStrategy]] = {}

    def register(self, strategy_cls: Type[BaseStrategy]) -> None:
        """Register a strategy class.

        The class must have a strategy_id class attribute or property.
        """
        # Instantiate temporarily to get the strategy_id
        instance = strategy_cls()
        sid = instance.strategy_id
        self._strategies[sid] = strategy_cls

    def get(self, strategy_id: str) -> Type[BaseStrategy]:
        """Get a strategy class by ID."""
        if strategy_id not in self._strategies:
            raise StrategyNotFoundError(strategy_id)
        return self._strategies[strategy_id]

    def create(self, strategy_id: str) -> BaseStrategy:
        """Create a new instance of a registered strategy."""
        cls = self.get(strategy_id)
        return cls()

    def list_ids(self) -> list[str]:
        """List all registered strategy IDs."""
        return sorted(self._strategies.keys())

    def __contains__(self, strategy_id: str) -> bool:
        return strategy_id in self._strategies

    def __len__(self) -> int:
        return len(self._strategies)
