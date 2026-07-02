import logging
import os
from datetime import datetime

import pytz

from features.fxstreet_fetcher import (
    confirm_pending_narrative,
    get_narrative_status,
    run_weekly_narrative_pipeline,
)
from paper_trading.config_manager import get_config

logger = logging.getLogger("eigencapital.engine_narrative_service")

ET = pytz.timezone("US/Eastern")


class EngineNarrativeService:
    def __init__(self, engine):
        self.engine = engine

    def init_narrative(self) -> None:
        engine = self.engine
        engine._narrative_api_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
        self._apply_active_narrative()

    def _apply_active_narrative(self) -> None:
        status = get_narrative_status()
        active = status.get("active")
        if active:
            from features.macro_narrative import MacroNarrativeFeatures

            narr = MacroNarrativeFeatures(**active)
            for asset in self.engine.assets.values():
                asset.set_narrative_state(narr)

    def _refresh_narrative(self) -> bool:
        engine = self.engine
        now = datetime.now(tz=ET)
        is_monday = now.weekday() == 0
        status = get_narrative_status()
        stale = status.get("stale", True)
        if not is_monday and not stale:
            return False
        if stale or (is_monday and status.get("needs_confirmation")):
            api_key = engine._narrative_api_key or None
            ok = run_weekly_narrative_pipeline(api_key)
            if ok:
                deadline_hour = get_config().narrative_config.get("auto_confirm_deadline_hour", 12)
                if now.hour >= deadline_hour or not api_key:
                    confirm_pending_narrative()
                    self._apply_active_narrative()
                    logger.info("Narrative auto-confirmed for week")
                else:
                    logger.info("Narrative pending — awaiting confirmation (deadline %d:00 ET)", deadline_hour)
            else:
                logger.warning("Narrative refresh failed — carrying forward last week")
        return True
