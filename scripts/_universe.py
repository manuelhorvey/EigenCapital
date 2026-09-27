"""Shared universe derivation from the authoritative production config.

Single source of truth: configs/{EIGENCAPITAL_ENV}/config.toml →
[broker.allowed_symbols] (per docs/DOCUMENTATION_SOURCE_OF_TRUTH.md).

Operational scripts (instrument_eligibility, account_readiness, capture_t0)
import from here instead of maintaining inline symbol copies, which
historically drifted silently from the config (USTEC/USOIL/XNGUSD were
missing from script lists for weeks after they were admitted).

Conventions mirrored from the live loop (scripts/r4_rebalance_loop.py):
- R4_SYMBOLS         : every [broker.allowed_symbols] key, config order preserved
- ASSET_CLASSES      : config classification with "forex_excluded" → "forex"
                       (same split("_")[0] rule the live loop applies)

Imports NO broker/MT5 dependency — safe to import in offline contexts.
Raises if the environment config defines no universe: running readiness /
T0 / eligibility tooling against an unclassified universe is a
misconfiguration and must fail loudly, not loop over zero symbols.
"""

from __future__ import annotations

import os

from eigencapital.config import load_config

ENVIRONMENT = os.environ.get("EIGENCAPITAL_ENV", "production")

_ALLOWED: dict[str, str] = dict(load_config(ENVIRONMENT).broker.allowed_symbols)

if not _ALLOWED:
    raise RuntimeError(
        f"[broker.allowed_symbols] is empty for environment '{ENVIRONMENT}' — "
        "cannot derive the operational universe from config"
    )

# Universe order preserved exactly as authored in the config file.
R4_SYMBOLS: list[str] = list(_ALLOWED.keys())

# Symbol → asset class ("forex_excluded" → "forex", mirroring the live loop).
ASSET_CLASSES: dict[str, str] = {sym: cls.split("_")[0] for sym, cls in _ALLOWED.items()}
