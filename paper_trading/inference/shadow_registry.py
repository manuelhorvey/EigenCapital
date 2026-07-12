"""Shadow model registry — thread-safe lifecycle management.

Encapsulates ``ShadowModelRunner`` caching, shadow config loading,
and ``ShadowStorage`` lifecycle.  Extracted from ``pipeline.py`` as
part of MAINT-01 (split oversized modules).

Usage:
    registry = ShadowModelRegistry()
    runner = registry.get_or_create_runner("v2", config, "EURUSD")
    storage = registry.get_storage()
    registry.reset()  # test fixture cleanup
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from paper_trading.shadow.model import ShadowModelRunner
from paper_trading.shadow.storage import ShadowStorage

logger = logging.getLogger("eigencapital.shadow_registry")

_ShadowRegistryT = dict[tuple[str, str], ShadowModelRunner]  # (shadow_id, asset_name) -> runner

_SHADOW_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class ShadowModelRegistry:
    """Thread-safe registry of shadow model runners.

    Maintains a cache of ``ShadowModelRunner`` instances keyed by
    ``(shadow_id, asset_name)``.  Supports lifecycle reset for tests
    to prevent state bleeding across fixtures.

    Usage:
        registry = ShadowModelRegistry()
        runner = registry.get_or_create_runner("v2", {"model_path": "..."}, "EURUSD")
        storage = registry.get_storage()
        registry.reset()  # clear cache (test fixtures)
    """

    def __init__(self) -> None:
        self._registry: _ShadowRegistryT = {}
        self._storage: ShadowStorage | None = None
        self._configs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def load_configs(self) -> dict[str, dict]:
        """Load shadow model specs from configs/domains/shadow_models.yaml.

        Results cached in ``self._configs`` (mutated in-place so any module-level
        references to ``self._configs`` remain valid — see ARCH-01).
        Returns self._configs (the same dict object, mutated in place).
        """
        import yaml

        config_path = os.path.join(_SHADOW_BASE, "configs", "domains", "ml", "shadow_models.yaml")
        if not os.path.exists(config_path):
            self._configs.clear()
            return self._configs
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            models = data.get("shadow_models", [])
            loaded = {m["id"]: m for m in models if m.get("status") in ("shadow", "canary")}
            self._configs.clear()
            self._configs.update(loaded)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Failed to load shadow configs: %s", exc)
            self._configs.clear()
        return self._configs

    @property
    def configs(self) -> dict[str, dict]:
        """Currently loaded shadow configs (lazy-loaded on first access)."""
        if not self._configs:
            self.load_configs()
        return self._configs

    def get_storage(self) -> ShadowStorage:
        """Get or create the shared ShadowStorage instance (lazy init)."""
        if self._storage is None:
            base = os.path.join(_SHADOW_BASE, "data", "live", "shadow")
            self._storage = ShadowStorage(base_dir=base)
        return self._storage

    def get_or_create_runner(self, shadow_id: str, config: dict[str, Any], asset_name: str) -> ShadowModelRunner:
        """Get or create a ShadowModelRunner for the given shadow_id and asset.

        Supports ``{asset}`` placeholder in ``model_path`` (e.g.
        ``models/canary/{asset}.json``) so a single shadow config can
        reference per-asset model files.

        Thread-safe: uses internal lock around the check-then-set pattern
        to prevent concurrent ThreadPoolExecutor workers from racing on
        the same key.
        """
        key = (shadow_id, asset_name)
        with self._lock:
            if key not in self._registry:
                raw_path = config.get("model_path", "")
                resolved = raw_path.replace("{asset}", asset_name)
                model_path = os.path.join(_SHADOW_BASE, resolved)
                self._registry[key] = ShadowModelRunner(
                    shadow_id=shadow_id,
                    model_path=model_path,
                )
            return self._registry[key]

    def reset(self) -> None:
        """Clear all cached runners and storage.  Call in test fixtures."""
        with self._lock:
            self._registry.clear()
            self._storage = None
            self._configs.clear()


# Module-level singleton for backward compatibility.
# Production code uses this instance; tests can call ``_shadow_registry.reset()``
# between test cases to prevent state bleeding across fixtures.
_shadow_registry = ShadowModelRegistry()

# Backward-compatible module-level convenience references (ARCH-01).
# All point to the same underlying objects as _shadow_registry.
SHADOW_REGISTRY: _ShadowRegistryT = _shadow_registry._registry
SHADOW_CONFIGS: dict[str, dict] = _shadow_registry._configs
SHADOW_REGISTRY_LOCK = _shadow_registry._lock


def load_shadow_configs() -> dict[str, dict]:
    """Delegate to singleton's load_configs (backward compat)."""
    return _shadow_registry.load_configs()


def get_shadow_storage() -> ShadowStorage:
    """Delegate to singleton's get_storage (backward compat)."""
    return _shadow_registry.get_storage()


def get_shadow_runner(shadow_id: str, config: dict[str, Any], asset_name: str) -> ShadowModelRunner:
    """Delegate to singleton's get_or_create_runner (backward compat)."""
    return _shadow_registry.get_or_create_runner(shadow_id, config, asset_name)


def reset_shadow_registry() -> None:
    """Test hook: clear all cached shadow runners."""
    _shadow_registry.reset()
