"""Control-plane routes — mutate live engine/orchestrator state.

These are deliberately few and require explicit action (POST). Unlike the
read-only route modules, they operate on the live registered engine via
``paper_trading.governance.health.get_registered_engine`` so a control action
takes effect immediately rather than on the next persisted-state reload.
"""

import logging

from paper_trading.api.common import json_dumps
from paper_trading.governance.health import get_registered_engine

logger = logging.getLogger("quorrin.control_routes")


def handle_emergency_halt_reset(body: bytes) -> tuple[str, int]:
    """Reset the orchestrator emergency halt.

    Clears the latched ``_emergency_halt``/``_halt_reason`` so the engine
    resumes trading on the next cycle. Safe when no emergency halt is active
    (no-op). Requires the live engine to be registered; returns 503 otherwise.
    """
    engine = get_registered_engine()
    if engine is None:
        return (
            json_dumps(
                {
                    "ok": False,
                    "error": "engine_not_registered",
                    "message": "No live engine registered — control action unavailable.",
                },
                indent=2,
            ),
            503,
        )

    orchestrator = getattr(engine, "_orchestrator", None)
    if orchestrator is None or not hasattr(orchestrator, "reset_emergency_halt"):
        return (
            json_dumps(
                {
                    "ok": False,
                    "error": "orchestrator_unavailable",
                    "message": "Live engine has no emergency-halt orchestrator.",
                },
                indent=2,
            ),
            503,
        )

    was_halted = bool(orchestrator.emergency_halt)
    orchestrator.reset_emergency_halt()
    logger.info("control: emergency halt reset (was_halted=%s)", was_halted)
    return (
        json_dumps(
            {
                "ok": True,
                "emergency_halt": False,
                "was_halted": was_halted,
                "message": "Emergency halt cleared. Trading resumes next cycle.",
            },
            indent=2,
        ),
        200,
    )
