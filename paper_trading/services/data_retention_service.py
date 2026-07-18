import logging
from datetime import datetime

import pytz

logger = logging.getLogger("eigencapital.data_retention_service")

ET = pytz.timezone("US/Eastern")


class DataRetentionService:
    def __init__(self, engine):
        self.engine = engine

    def prune(self) -> None:
        today = datetime.now(tz=ET).strftime("%Y-%m-%d")
        if self.engine._last_prune_date == today:
            return
        self.engine._last_prune_date = today

        try:
            from paper_trading.ops.prune_data import RETENTION, prune_all

            retention = dict(RETENTION)
            cfg_retention = getattr(self.engine._engine_cfg, "retention", {})
            key_map = {
                "trades_days": "trades",
                "attribution_days": "attribution",
                "equity_history_days": "equity_history",
                "trace_days": "trace.jsonl",
                "wal_days": "wal/engine.jsonl",
                "log_days": "engine.log",
                "shadow_feedback_days": "shadow_feedback",
                "shadow_memory_days": "shadow_memory",
            }
            for cfg_key, ret_key in key_map.items():
                val = cfg_retention.get(cfg_key)
                if val is not None and isinstance(val, (int, float)) and val > 0:
                    retention[ret_key] = int(val)

            logger.info(
                "Pruning data older than retention limits: trades=%dd, attr=%dd, eq=%dd, log=%dd",
                retention.get("trades", 365),
                retention.get("attribution", 365),
                retention.get("equity_history", 90),
                retention.get("engine.log", 14),
            )
            stats = prune_all(apply=True, retention=retention)
            total = sum(s.get("pruned", 0) + s.get("pruned_files", 0) for s in stats.values() if isinstance(s, dict))
            if total > 0:
                logger.info("Pruned %d items across %d data types", total, len(stats))
            else:
                logger.debug("No data needed pruning today")
        except (OSError, ValueError, TypeError, KeyError) as e:
            logger.warning("Auto-prune failed: %s", e)
