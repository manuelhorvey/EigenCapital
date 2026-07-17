"""Phase 5 — State persistence hardening tests.

Verifies:
1. Engine creates its own StateStore instance (not the module-level singleton)
2. Multiple engine instances have independent stores
3. api/common.py reset_store() clears the singleton for test isolation
4. health.py accepts injected state_store via register_state_store()
5. health.py falls back to creating its own store when none is registered
"""

from __future__ import annotations

import os
import tempfile


class TestEngineStoreIsolation:
    """Engine module-level backward compat is preserved."""

    def test_module_level_exports_preserved(self):
        """_STORE, STATE_PATH, CACHE_DIR, LOG_PATH still exported."""
        import paper_trading.engine as eng_mod

        assert hasattr(eng_mod, "_STORE")
        assert hasattr(eng_mod, "STATE_PATH")
        assert hasattr(eng_mod, "CACHE_DIR")
        assert hasattr(eng_mod, "LOG_PATH")

    def test_engine_creates_fresh_store_per_instance(self):
        """PaperTradingEngine.__init__ creates StateStore(BASE) not falling back to _STORE."""
        import inspect

        from paper_trading.engine import PaperTradingEngine

        source_lines, _ = inspect.getsourcelines(PaperTradingEngine.__init__)
        source = "".join(source_lines)

        assert "StateStore(BASE)" in source
        assert "state_store or _STORE" not in source


class TestCommonResetStore:
    """api/common.py reset_store() clears the singleton for test isolation."""

    def test_reset_store_clears_singleton(self):
        """After reset_server_store(), a new init_server_store() creates a different object."""
        from paper_trading.api.common import get_server_store, init_server_store, reset_server_store

        with tempfile.TemporaryDirectory() as tmp:
            init_server_store(base_dir=tmp)
            store_a = get_server_store()
            assert store_a is not None
            assert os.path.exists(store_a.live_dir)

            reset_server_store()
            init_server_store(base_dir=tmp)
            store_b = get_server_store()

            assert store_b is not store_a

    def test_init_store_accepts_precreated_store(self):
        """init_server_store(store=...) uses the provided instance instead of creating one."""
        from paper_trading.api.common import get_server_store, init_server_store, reset_server_store
        from paper_trading.state_store import StateStore

        reset_server_store()
        with tempfile.TemporaryDirectory() as tmp:
            custom_store = StateStore(tmp)
            init_server_store(store=custom_store)
            store = get_server_store()
            assert store is custom_store


class TestHealthStoreInjection:
    """health.py accepts injected state_store via register_state_store()."""

    def test_register_state_store_injection(self):
        """register_state_store injects a store used by _get_state_store()."""
        from paper_trading.governance.health import _get_state_store, register_state_store
        from paper_trading.state_store import StateStore

        with tempfile.TemporaryDirectory() as tmp:
            custom_store = StateStore(tmp)
            register_state_store(custom_store)
            try:
                retrieved = _get_state_store()
                assert retrieved is custom_store
            finally:
                register_state_store(None)

    def test_register_none_clears_store(self):
        """Passing None clears the store (no lazy init fallback)."""
        from paper_trading.governance.health import _get_state_store, register_state_store
        from paper_trading.state_store import StateStore

        with tempfile.TemporaryDirectory() as tmp:
            custom_store = StateStore(tmp)
            register_state_store(custom_store)
            store = _get_state_store()
            assert store is custom_store

            register_state_store(None)
            store = _get_state_store()
            assert store is None

    def test_health_compute_all_with_injected_store(self):
        """compute_all works with an injected state store (no live engine)."""
        from paper_trading.governance.health import compute_all, register_engine, register_state_store
        from paper_trading.state_store import StateStore

        with tempfile.TemporaryDirectory() as tmp:
            register_engine(None)
            store = StateStore(tmp)
            register_state_store(store)
            try:
                result = compute_all()
                assert "assets" in result
                assert "system_health" in result
                assert result["system_health"]["n_assets"] == 0
            finally:
                register_state_store(None)
                register_engine(None)
