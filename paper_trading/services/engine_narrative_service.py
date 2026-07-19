"""Narrative service with background refresh for non-blocking LLM calls.

The weekly narrative refresh (FXStreet scrape + LLM API) is expensive:
it makes multiple HTTP requests with up to 60s timeouts.  To avoid
blocking the main trading cycle, the actual pipeline runs on a daemon
background thread.  The synchronous ``_refresh_narrative()`` call only
checks whether a refresh is needed and, if so, kicks off the thread.

The narrative state is applied synchronously from the on-disk JSON
files on each engine cycle, so the latest available narrative is always
active even while a background refresh is in progress.
"""

from __future__ import annotations

import logging
import os
import threading
import time
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

# Minimum seconds between background narrative refresh attempts
_NARRATIVE_REFRESH_COOLDOWN = 300.0  # 5 minutes


class EngineNarrativeService:
    """Narrative service with background refresh for non-blocking LLM calls."""

    def __init__(self, engine):
        self.engine = engine
        self._narrative_thread: threading.Thread | None = None
        self._narrative_lock = threading.Lock()
        self._last_refresh_attempt: float = 0.0

    def init_narrative(self) -> None:
        engine = self.engine
        engine._narrative_api_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
        # Apply whatever narrative is available on disk (fast -- no HTTP)
        self.apply_active_narrative()

    def apply_active_narrative(self) -> None:
        """Apply the currently active narrative from disk to all assets.

        This is called synchronously every engine cycle and is fast
        (just reads a JSON file and sets attribute values).  No HTTP calls.
        """
        status = get_narrative_status()
        active = status.get("active")
        if active:
            from features.macro_narrative import MacroNarrativeFeatures

            narr = MacroNarrativeFeatures(**active)
            for asset in self.engine.assets.values():
                asset.set_narrative_state(narr)

    def _background_refresh_worker(self) -> None:
        """Run the narrative pipeline on a background thread.

        This is the expensive path: fetches FXStreet article, calls LLM API,
        saves pending narrative, and auto-confirms if past deadline.

        Errors are logged but never propagated -- the engine cycle must never
        crash due to a narrative refresh failure.
        """
        engine = self.engine
        now = datetime.now(tz=ET)
        try:
            api_key = engine._narrative_api_key or None
            ok = run_weekly_narrative_pipeline(api_key)
            if ok:
                deadline_hour = get_config().narrative_config.get("auto_confirm_deadline_hour", 12)
                if now.hour >= deadline_hour or not api_key:
                    confirm_pending_narrative()
                    self.apply_active_narrative()
                    logger.info(
                        "[background] Narrative auto-confirmed for week starting %s",
                        now.strftime("%Y-%m-%d"),
                    )
                else:
                    logger.info(
                        "[background] Narrative pending -- awaiting confirmation (deadline %d:00 ET)",
                        deadline_hour,
                    )
            else:
                logger.warning("[background] Narrative refresh failed -- carrying forward last week")
        except Exception as exc:
            logger.error("[background] Narrative refresh worker crashed: %s", exc, exc_info=True)
        finally:
            self._last_refresh_attempt = time.monotonic()

    def _refresh_narrative(self) -> bool:
        """Check if narrative needs refresh and start background thread if so.

        Returns True if a refresh was determined to be needed (regardless of
        whether the background thread has completed).  The caller uses this
        only for logging -- the trading cycle is NOT blocked by the refresh.

        The background thread is a daemon thread so it does not prevent
        engine shutdown.
        """
        now = datetime.now(tz=ET)
        is_monday = now.weekday() == 0
        status = get_narrative_status()
        stale = status.get("stale", True)

        # Fast path: no refresh needed
        if not is_monday and not stale:
            return False
        if not stale and not (is_monday and status.get("needs_confirmation")):
            return False

        # Cooldown: don't hammer the API if a refresh just happened
        if time.monotonic() - self._last_refresh_attempt < _NARRATIVE_REFRESH_COOLDOWN:
            logger.debug("Narrative refresh skipped -- within cooldown (%.0fs)", _NARRATIVE_REFRESH_COOLDOWN)
            return True

        # Start background thread if not already running
        with self._narrative_lock:
            if self._narrative_thread is not None and self._narrative_thread.is_alive():
                logger.debug("Narrative refresh already in progress on background thread")
                return True
            self._narrative_thread = threading.Thread(
                target=self._background_refresh_worker,
                name="narrative-refresh",
                daemon=True,
            )
            self._narrative_thread.start()
            logger.info(
                "Narrative refresh kicked off on background thread (stale=%s, monday=%s, api_key=%s)",
                stale,
                is_monday,
                "yes" if self.engine._narrative_api_key else "no",
            )

        return True
