"""Backward-compat re-export of ``paper_trading.orchestrator._engine``.

This module exists so that existing imports of
``paper_trading.orchestrator.engine`` continue to work.  New code should
import directly from ``paper_trading.orchestrator._engine``.

The class was renamed to ``_engine.py`` during the dual-path consolidation
(remediation/audit-hardening-2026-07-17).  See the docstring in
``_engine.py`` for design details.
"""

import warnings

from paper_trading.orchestrator._engine import EngineOrchestrator, EnginePhase  # noqa: F401

warnings.warn(
    "paper_trading.orchestrator.engine is deprecated — use paper_trading.orchestrator._engine directly",
    DeprecationWarning,
    stacklevel=2,
)
