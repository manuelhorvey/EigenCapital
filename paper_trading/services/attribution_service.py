import logging
import os

import pandas as pd

from paper_trading.attribution.collector import TradeAttributionRecord

logger = logging.getLogger("eigencapital.attribution_service")


class AttributionService:
    @staticmethod
    def set_experiment_context(*, attribution_export_dir, experiment_id: str, export_dir: str | None = None):
        if export_dir is not None:
            attribution_export_dir = export_dir
            os.makedirs(export_dir, exist_ok=True)
        return attribution_export_dir

    @staticmethod
    def flush_attribution(*, name, attribution_buffer, attribution_export_dir, experiment_id):
        if not attribution_buffer or not attribution_export_dir:
            return
        try:
            path = os.path.join(attribution_export_dir, f"{name}_attribution.parquet")
            records = list(attribution_buffer)
            frame = TradeAttributionRecord.to_frame(records, experiment_id=experiment_id)
            if os.path.exists(path):
                existing = pd.read_parquet(path)
                frame = pd.concat([existing, frame], ignore_index=True)
            frame.to_parquet(path, index=False)
            attribution_buffer.clear()
            logger.debug("attribution: flushed %d records for %s to %s", len(records), name, path)
        except Exception:
            logger.exception("attribution: failed to flush records for %s", name)
