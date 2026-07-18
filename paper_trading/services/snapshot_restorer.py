import logging
from datetime import datetime

import pytz

logger = logging.getLogger("eigencapital.snapshot_restorer")

ET = pytz.timezone("US/Eastern")


class SnapshotRestorer:
    def __init__(self, engine):
        self.engine = engine

    def restore(self, snapshot) -> dict | None:
        from paper_trading.governance.risk_registry import reset as _reset_risk_governance
        from paper_trading.governance.risk_registry import restore_state as set_risk_state

        _reset_risk_governance()
        if snapshot is not None and snapshot.risk_state:
            try:
                set_risk_state(snapshot.risk_state)
                n_assets = len(snapshot.risk_state.get("sell_win_rates", {}))
                if n_assets:
                    logger.info(
                        "Restored risk governance state for %d asset(s) from snapshot",
                        n_assets,
                    )
            except (OSError, ValueError, TypeError, KeyError):
                logger.exception("Failed to restore risk state from snapshot")

        if snapshot is not None and snapshot.engine_status:
            self.engine.start_date = datetime.fromisoformat(
                snapshot.engine_status.get("start_time", self.engine.start_date.isoformat())
            )

        saved_positions = (snapshot.open_positions or {}) if snapshot else {}
        return saved_positions

    def restore_asset_values(self, snapshot) -> None:
        if snapshot is not None and snapshot.asset_values:
            for name, cv in snapshot.asset_values.items():
                if name in self.engine.assets:
                    asset = self.engine.assets[name]
                    asset.current_value = cv
                    asset.pos_mgr.current_value = cv
                    if cv > asset.peak_value:
                        asset.peak_value = cv
                        asset.pos_mgr.peak_value = cv
            logger.info(
                "Restored current_value for %d assets from snapshot",
                len(snapshot.asset_values),
            )
