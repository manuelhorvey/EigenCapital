"""Typed configuration models — Phase 3 scaffolding.

This package introduces typed dataclass models for each configuration
domain. The Phase 3 read-side mirror loads these models from new
domain files when present and falls back to the legacy YAML otherwise.
Exact key ordering and value equivalence with the legacy loader is
guaranteed by tests/test_domain_loader_equivalence.py.

Modules:
    risk           — capital, halt, sizing, exits (adaptive_exit, sell_only)
    portfolio      — weight_method + factor exposure limits
    ml             — ensemble, calibration, meta_labeling
    broker         — mt5 connection config
    execution      — spread gate, session gate, execution simulation
    governance     — regime geometry, liquidity, narrative
    infrastructure — alerting channels
    assets         — per-asset catalog (AssetConfig)
    modes          — mode-specific overlays
    optimizations  — optimization toggles
"""

from __future__ import annotations

__all__: list[str] = []
