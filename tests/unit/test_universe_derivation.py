"""Universe derivation tests — scripts/_universe.py must mirror config authority.

The operational scripts (instrument_eligibility, account_readiness, capture_t0)
derive their universe from [broker.allowed_symbols] via scripts/_universe.py.
These tests pin the derivation so inline symbol copies cannot silently
reappear or diverge (the drift that left USTEC/USOIL/XNGUSD missing from
script lists after their admission).
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import _universe

from eigencapital.config import load_config


class _EmptyBroker:
    allowed_symbols: dict = {}


class _EmptyConfig:
    broker = _EmptyBroker()


class TestUniverseDerivation:
    """scripts/_universe.py is a derived view of the authoritative config."""

    def test_symbols_match_config_exactly_in_order(self):
        config = load_config("production")
        assert list(config.broker.allowed_symbols.keys()) == _universe.R4_SYMBOLS

    def test_no_duplicate_symbols(self):
        assert len(_universe.R4_SYMBOLS) == len(set(_universe.R4_SYMBOLS))

    def test_asset_classes_follow_loop_convention(self):
        """Classification must mirror the live loop: cls.split('_')[0],
        so 'forex_excluded' → 'forex' and HK50/JP225 → 'indices'."""
        config = load_config("production")
        expected = {sym: cls.split("_")[0] for sym, cls in config.broker.allowed_symbols.items()}
        assert expected == _universe.ASSET_CLASSES
        assert _universe.ASSET_CLASSES["AUDJPY"] == "forex"  # forex_excluded → forex
        assert _universe.ASSET_CLASSES["HK50"] == "indices"
        assert _universe.ASSET_CLASSES["JP225"] == "indices"

    def test_environment_respected(self):
        assert os.environ.get("EIGENCAPITAL_ENV", "production") == _universe.ENVIRONMENT

    def test_empty_universe_fails_closed(self, monkeypatch):
        """A config environment without a universe must raise, not yield an
        empty operational universe (readiness/T0 would otherwise loop over
        zero symbols and report success)."""
        # Patch at the source: reload() re-executes `from eigencapital.config
        # import load_config`, which would overwrite a patch placed on the
        # _universe module itself.
        monkeypatch.setattr("eigencapital.config.load_config", lambda env: _EmptyConfig())
        with pytest.raises(RuntimeError, match="allowed_symbols"):
            importlib.reload(_universe)
        # Restore the real derivation for any subsequent test in the session.
        monkeypatch.undo()
        importlib.reload(_universe)
        assert _universe.R4_SYMBOLS
