import logging

import pytz

from paper_trading.entry.decision import PositionIntent, PositionSide

logger = logging.getLogger("eigencapital.engine_recovery_service")

ET = pytz.timezone("US/Eastern")


class EngineRecoveryService:
    def __init__(self, engine):
        self.engine = engine

    def _restore_saved_position(self, asset, pos_data: dict) -> None:
        pos_dict = pos_data.get("position")
        if pos_dict:
            intent = PositionIntent(
                side=PositionSide(pos_dict["side"]),
                entry_price=pos_dict["entry"],
                entry_date=pos_dict["entry_date"],
                stop_loss=pos_dict["sl"],
                take_profit=pos_dict["tp"],
                vol=pos_dict["vol"],
            )
            asset.position = pos_dict
            asset.pos_mgr.open(intent)
        cv = pos_data.get("current_value")
        if cv is not None:
            asset.current_value = cv
            asset.pos_mgr.current_value = cv
        pv = pos_data.get("peak_value")
        if pv is not None:
            asset.peak_value = pv
            asset.pos_mgr.peak_value = pv
        asset.trade_log = pos_data.get("trade_log", [])
        asset.pos_mgr.trade_log = list(pos_data.get("trade_log", []))
        asset.prob_history = pos_data.get("prob_history", [])
        asset._bars_at_entry = pos_data.get("bars_at_entry", 0)
        if "initial_sl" in pos_data:
            asset._initial_sl = pos_data["initial_sl"]
        if "initial_tp" in pos_data:
            asset._initial_tp = pos_data["initial_tp"]
        if "running_mae" in pos_data:
            asset._running_mae = pos_data["running_mae"]
        if "running_mfe" in pos_data:
            asset._running_mfe = pos_data["running_mfe"]

    def restore_positions(self, saved_positions: dict) -> None:
        engine = self.engine
        for name, pos_data in saved_positions.items():
            if name in engine.assets:
                self._restore_saved_position(engine.assets[name], pos_data)
            else:
                pos = pos_data.get("position", {})
                mt5_ticket = pos.get("mt5_ticket")
                side = pos.get("side", "?")
                entry = pos.get("entry", 0)
                logger.warning(
                    "Orphan position for removed/delisted asset '%s': side=%s entry=%.5f mt5_ticket=%s",
                    name,
                    side,
                    entry,
                    mt5_ticket,
                )
                if mt5_ticket is not None and getattr(engine.execution_bridge, "_is_real_broker", False):
                    try:
                        mt5_sym = engine.broker.ticker_to_mt5_symbol(name)
                        engine.broker.close_position(mt5_sym, str(mt5_ticket))
                        logger.info(
                            "Closed orphan MT5 position for removed asset '%s' on %s (ticket=%s)",
                            name,
                            mt5_sym,
                            mt5_ticket,
                        )
                    except (KeyError, OSError, ConnectionError, TimeoutError, ValueError, AttributeError) as _re_exc:
                        logger.exception(
                            "Failed to close orphan MT5 position for removed asset '%s' (ticket=%s): %s",
                            name,
                            mt5_ticket,
                            _re_exc,
                        )
