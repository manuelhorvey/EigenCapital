import hashlib
import logging
from pathlib import Path
import time

logger = logging.getLogger("eigencapital.model_integrity_service")


class ModelIntegrityService:
    def __init__(self, engine):
        self.engine = engine

    def check_integrity(self) -> None:
        for asset_name, asset in list(self.engine.assets.items()):
            if not hasattr(asset, "_model_hash") or not hasattr(asset, "model_path"):
                continue
            model_path = asset.model_path
            if not Path(model_path).exists():
                continue
            try:
                with open(model_path, "rb") as fm:
                    current_hash = hashlib.sha256(fm.read()).hexdigest()[:16]
                if current_hash != asset._model_hash and current_hash != "unknown":
                    logger.info(
                        "experiment: model hash changed for %s (%s… → %s…) — reloading",
                        asset_name,
                        asset._model_hash[:8],
                        current_hash[:8],
                    )
                    asset.train(force=False)
            except (OSError, ValueError, TypeError, AttributeError):
                logger.debug(
                    "experiment: model integrity check skipped for %s",
                    asset_name,
                    exc_info=True,
                )

    def auto_retrain(self) -> None:
        counter = getattr(self.engine, "_retrain_cycle_counter", 0)
        self.engine._retrain_cycle_counter = counter + 1
        if self.engine._retrain_cycle_counter % 100 != 0:
            return
        min_stale_days = 90
        for rt_name, rt_asset in list(self.engine.assets.items()):
            rt_mp = getattr(rt_asset, "model_path", None)
            if not rt_mp or not Path(rt_mp).exists():
                continue
            try:
                rt_mtime = Path(rt_mp).stat().st_mtime
                rt_age_days = (time.time() - rt_mtime) / 86400
                if rt_age_days > min_stale_days:
                    logger.info(
                        "retrain: %s model is %.0f days old (threshold=%d) — retraining",
                        rt_name,
                        rt_age_days,
                        min_stale_days,
                    )
                    full_panel = self.engine._build_full_panel()
                    rt_asset.train(force=True, full_panel=full_panel)
            except OSError:
                pass
