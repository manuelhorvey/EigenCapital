"""Provenance Hashing — re-exported from core (A4).

The canonical implementation now lives in ``eigencapital.core.provenance``
because production backtest code imports it and the ``research`` package is not
part of the installed distribution. This module exists so existing research
imports and tests keep working unchanged.

Usage:
    h = compute_provenance_hash({...})
"""

from __future__ import annotations

from eigencapital.core.provenance import canonical_json_dumps, compute_provenance_hash, verify_provenance

__all__ = ["canonical_json_dumps", "compute_provenance_hash", "verify_provenance"]
