"""Chaos engineering infrastructure — fault injection primitives for
production-resilience testing.

Provides:

- ``ChaosRegistry`` — registry of available fault scenarios
- ``fault_inject`` context manager — temporarily replaces a callable with
  one that fails according to a fault recipe

Scope:
- The chaos layer is *test-only* (excluded from production imports via
  pre-commit hook).  It monkey-patches callables in a controlled way,
  with deterministic cleanup.
- This module does NOT alter production behavior at runtime.

Usage::

    from tests.chaos.chaos_tools import fault_inject, ConnectionDropOnce

    def test_orchestrator_survives_connection_drop(monkeypatch):
        with fault_inject(mt5_client, "fetch_ohlcv", ConnectionDropOnce()):
            with pytest.raises(MT5ConnectionError):
                mt5_client.fetch_ohlcv("EURUSD", years=2)
"""

from __future__ import annotations

import random
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Any


@dataclass
class FaultRecipe:
    """Configuration for a fault scenario."""

    name: str
    description: str
    exception: type[Exception] | None = None
    message: str = "fault-injection"
    n_failures: int = 1  # number of times to fail before recovering
    fail_probability: float = 1.0  # probability each call fails
    return_value: Any = None  # if not failing, what to return
    delay_seconds: float = 0.0  # simulate latency


class ChaosRegistry:
    """Catalog of registered chaos scenarios.  Doc-only — used for
    introspection in test reports."""

    def __init__(self) -> None:
        self._scenarios: list[FaultRecipe] = []

    def register(self, recipe: FaultRecipe) -> None:
        self._scenarios.append(recipe)

    def list_scenarios(self) -> list[FaultRecipe]:
        return list(self._scenarios)


REGISTRY = ChaosRegistry()


def _patched_factory(recipe: FaultRecipe, original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap *original* with a fault injector based on *recipe*."""

    state = {"failures_left": recipe.n_failures}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if recipe.delay_seconds > 0:
            import time

            time.sleep(recipe.delay_seconds)
        if random.random() < recipe.fail_probability and state["failures_left"] > 0:
            state["failures_left"] -= 1
            if recipe.exception is None:
                raise RuntimeError(recipe.message)
            raise recipe.exception(recipe.message)
        return original(*args, **kwargs)

    return wrapper


@contextmanager
def fault_inject(
    host: ModuleType | object,
    attr: str,
    recipe: FaultRecipe,
):
    """Temporarily replace ``host.attr`` with a fault-injected version.

    Restores the original on exit (even on exceptions).
    """
    REGISTRY.register(recipe)
    original = getattr(host, attr)
    if not callable(original):
        raise TypeError(f"{attr!r} on {host!r} is not callable")
    patched = _patched_factory(recipe, original)
    setattr(host, attr, patched)
    try:
        yield patched
    finally:
        setattr(host, attr, original)
