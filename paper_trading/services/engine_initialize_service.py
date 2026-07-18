import logging

logger = logging.getLogger("eigencapital.engine_initialize_service")


class EngineInitializeService:
    def __init__(self, engine):
        self.engine = engine

    def initialize(self):
        from features.registry import ASSET_LABEL_PARAMS

        for name, asset in self.engine.assets.items():
            registry_params = ASSET_LABEL_PARAMS.get(name)
            if registry_params is not None and (
                asset.sl_mult != registry_params["sl"] or asset.tp_mult != registry_params["pt"]
            ):
                logger.warning(
                    "%s: runtime exit (sl=%.2f,tp=%.2f) != "
                    "training label params (sl=%.2f,pt=%.2f) — "
                    "asymmetric exits OK, but monitor ΔSharpe impact",
                    name,
                    asset.sl_mult,
                    asset.tp_mult,
                    registry_params["sl"],
                    registry_params["pt"],
                )
            try:
                full_panel = self.engine._build_full_panel()
                asset.train(force=True, full_panel=full_panel)
                logger.info("%s: training done", name)
            except (OSError, ValueError, TypeError, RuntimeError, ImportError) as e:
                logger.error("%s: training FAILED - %s", name, e)
