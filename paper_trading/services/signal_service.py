import logging

from labels.meta_labels import MetaLabelModel

logger = logging.getLogger("quorrin.signal_service")


class SignalService:
    @staticmethod
    def load_meta_label_model(config: dict, name: str):
        if not config.get("meta_labeling", {}).get("enabled", False):
            return None
        try:
            model = MetaLabelModel(
                threshold=config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            model._load(model._model_path(name))
            if model._trained:
                logger.info("%s: meta-label model loaded from cache", name)
                return model
        except Exception as e:
            logger.debug("%s: no cached meta-label model: %s", name, e)
        return None

    @staticmethod
    def meta_size_multiplier(config: dict, last_meta_proba) -> float:
        if not config.get("meta_labeling", {}).get("enabled", False):
            return 1.0
        if last_meta_proba is None:
            return 1.0

        threshold = config.get("meta_labeling", {}).get("threshold", 0.55)
        min_size = config.get("meta_labeling", {}).get("min_size_on_threshold", 0.25)

        if last_meta_proba < threshold:
            return 0.0
        if last_meta_proba >= 1.0:
            return 1.0

        t = (last_meta_proba - threshold) / (1.0 - threshold)
        return min_size + t * (1.0 - min_size)
