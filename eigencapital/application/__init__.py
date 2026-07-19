"""EigenCapital Application Layer.

This package contains application-level services that orchestrate domain
entities and infrastructure. It is the primary entry point for the
hexagonal architecture — infrastructure (paper_trading/) depends on
this layer, not the other way around.

Services:
- EngineService — lifecycle management for the paper trading engine
"""

from eigencapital.application.engine_service import EngineService, CycleResult, EngineStatus

__all__ = [
    "EngineService",
    "CycleResult",
    "EngineStatus",
]
