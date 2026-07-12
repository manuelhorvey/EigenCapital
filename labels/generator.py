import logging
import os

import pandas as pd

from features.registry import FEATURE_REGISTRY
from labels.triple_barrier import apply_triple_barrier
from shared.volatility import VOLATILITY_PRIMITIVE_VERSION, VolatilityPrimitive

logger = logging.getLogger("eigencapital.labels.generator")


class LabelGenerator:
    """
    Phase 0 Functional Implementer.
    Generates deterministic label datasets with version-locked metadata.
    """

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.raw_dir = os.path.join(data_dir, "raw")
        self.processed_dir = os.path.join(data_dir, "processed")
        os.makedirs(self.processed_dir, exist_ok=True)

    def generate_all(self, force: bool = False):
        """Generate labels for all assets in registry."""
        results = {}
        for ticker, contract in FEATURE_REGISTRY.items():
            try:
                results[ticker] = self.generate_asset_labels(contract, force=force)
            except (OSError, ValueError, TypeError, KeyError) as e:
                logger.error("Failed to generate labels for %s: %s", ticker, e)
        return results

    def generate_asset_labels(self, contract, force: bool = False):
        """
        Generates dual labels (Shadow + New) for a single asset.
        """
        v_hash = contract.label_version
        filename = f"{contract.name}_labels_{v_hash}.parquet"
        out_path = os.path.join(self.processed_dir, filename)

        if os.path.exists(out_path) and not force:
            logger.info("Skipping %s: version %s already exists.", contract.name, v_hash)
            return out_path

        # Load raw daily data
        raw_path = os.path.join(self.raw_dir, f"{contract.name}_1d.parquet")
        if not os.path.exists(raw_path):
            # Try alternate naming: Ticker
            raw_path = os.path.join(self.raw_dir, f"{contract.ticker}_1d.parquet")

        if not os.path.exists(raw_path):
            # Try alternate naming: Ticker without suffix
            raw_path = os.path.join(self.raw_dir, f"{contract.ticker.replace('=X', '').replace('=F', '')}_1d.parquet")

        if not os.path.exists(raw_path):
            raise FileNotFoundError(f"Raw data not found for {contract.name} at {raw_path}")

        df = pd.read_parquet(raw_path)

        # Build volatility primitive from contract params (with fallback)
        vol_method = contract.label_params.get("vol_method", "ewm_100")
        atr_period = contract.label_params.get("atr_period", 14)
        vol_prim = VolatilityPrimitive.detect(df, period=atr_period) if vol_method == "atr" else None

        # New Labels (from current contract params)
        logger.info("Computing NEW labels for %s (v:%s)...", contract.name, v_hash)
        new_labeled = apply_triple_barrier(
            df,
            pt_sl=contract.label_params.get("pt_sl", [2, 2]),
            vertical_barrier=contract.label_params.get("vertical_barrier", 20),
            vol_primitive=vol_prim,
        )

        # Shadow Labels (Legacy/Reference — always EWM vol for baseline comparison)
        logger.info("Computing SHADOW labels for %s...", contract.name)
        shadow_labeled = apply_triple_barrier(df, pt_sl=[2, 2], vertical_barrier=20)

        final_df = df.copy()
        final_df["label_new"] = (new_labeled["label"] + 1).astype(int)
        final_df["label_shadow"] = (shadow_labeled["label"] + 1).astype(int)

        # Metadata — persist volatility primitive info for replayability
        final_df.attrs["label_version"] = v_hash
        final_df.attrs["contract_params"] = str(contract.label_params)
        final_df.attrs["vol_method"] = new_labeled.attrs.get("vol_method", vol_method)
        final_df.attrs["vol_primitive_version"] = VOLATILITY_PRIMITIVE_VERSION

        final_df.to_parquet(out_path)
        logger.info("Saved %s labels to %s", contract.name, out_path)

        return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    gen = LabelGenerator()
    gen.generate_all()
