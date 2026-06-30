import logging

import pandas as pd

from features.fxstreet_fetcher import get_active_narrative, is_narrative_stale
from features.liquidity_regime import (
    classify_liquidity_regime,
    compute_liquidity_features,
)
from features.liquidity_regime import (
    liquidity_governance_scalars as _liquidity_scalars,
)
from features.macro_narrative import narrative_governance_scalars as _narrative_scalars

logger = logging.getLogger("quorrin.asset_governance")


class AssetGovernance:
    def __init__(self, name: str, config: dict, halt_config: dict):
        self.name = name
        self.config = config
        self.halt_config = halt_config

        self._narrative_active = None
        self._narrative_stale = False
        self._narrative_sl_mult = 1.0
        self._narrative_size_scalar = 1.0

        self._liquidity_regime = "NORMAL"
        self._liquidity_sl_mult = 1.0
        self._liquidity_size_scalar = 1.0
        self._liquidity_halted = False
        self._liquidity_features: dict | None = None

    def _apply_narrative_scalars(self, narr) -> None:
        stale = is_narrative_stale(narr.week_start)
        cfg = self.config.get("narrative_config", {})
        scalars = _narrative_scalars(
            narr,
            geopol_sl_widen_pct=cfg.get("geopol_sl_widen_pct", 10.0),
            risk_off_size_reduce_pct=cfg.get("risk_off_size_reduce_pct", 20.0),
            min_confidence=cfg.get("min_confidence", 0.6),
            stale=stale,
        )
        self._narrative_active = narr
        self._narrative_stale = stale
        self._narrative_sl_mult = scalars["sl_mult"]
        self._narrative_size_scalar = scalars["size_scalar"]

    def load_narrative_state(self) -> None:
        try:
            narr = get_active_narrative()
            if narr is not None:
                self._apply_narrative_scalars(narr)
        except Exception as e:
            logger.debug("%s: no active narrative: %s", self.name, e)

    def set_narrative_state(self, narr) -> None:
        try:
            self._apply_narrative_scalars(narr)
        except Exception as e:
            logger.error("%s: failed to set narrative state: %s", self.name, e)

    def load_liquidity_state(self, price_data: pd.DataFrame | None) -> None:
        if not self.config.get("liquidity_config", {}).get("enabled", True):
            return
        try:
            if price_data is not None and len(price_data) > 22:
                self.refresh_liquidity(price_data)
        except Exception as e:
            logger.debug("%s: no liquidity state on init: %s", self.name, e)

    def refresh_liquidity(self, df: pd.DataFrame) -> None:
        cfg = self.config.get("liquidity_config", {})
        if not cfg.get("enabled", True):
            self._liquidity_regime = "NORMAL"
            self._liquidity_sl_mult = 1.0
            self._liquidity_size_scalar = 1.0
            self._liquidity_halted = False
            self._liquidity_features = None
            return
        window = cfg.get("regime_window", 21)
        min_samples = cfg.get("min_samples", 60)
        features = compute_liquidity_features(df, window=window, min_samples=min_samples)
        self._liquidity_features = features
        regime = classify_liquidity_regime(
            features,
            vol_thin_threshold=cfg.get("volume_z_thin_threshold", -1.5),
            vol_stressed_threshold=cfg.get("volume_z_stressed_threshold", -3.0),
            amihud_high_threshold=cfg.get("amihud_high_threshold", 1.5),
            amihud_stressed_threshold=cfg.get("amihud_stressed_threshold", 4.0),
        )
        self._liquidity_regime = regime
        scalars = _liquidity_scalars(
            regime,
            features=features,
            thin_sl_widen_pct=cfg.get("thin_sl_widen_pct", 15.0),
            thin_size_reduce_pct=cfg.get("thin_size_reduce_pct", 15.0),
            stressed_sl_widen_pct=cfg.get("stressed_sl_widen_pct", 30.0),
            stressed_size_reduce_pct=cfg.get("stressed_size_reduce_pct", 30.0),
        )
        self._liquidity_sl_mult = scalars["sl_mult"]
        self._liquidity_size_scalar = scalars["size_scalar"]
        self._liquidity_halted = scalars["halted"]
        if regime != "NORMAL":
            logger.info(
                "%s: liquidity regime=%s vol_z=%.2f amihud_z=%.2f sl=%.2fx size=%.2fx%s",
                self.name,
                regime,
                features.get("volume_z", 0),
                features.get("amihud_z", 0),
                self._liquidity_sl_mult,
                self._liquidity_size_scalar,
                " HALTED" if self._liquidity_halted else "",
            )

    def narrative_warnings(self) -> list[str]:
        reasons = []
        if (
            self._narrative_active is not None
            and not self._narrative_stale
            and (self._narrative_sl_mult > 1.05 or self._narrative_size_scalar < 0.95)
        ):
            narr = self._narrative_active
            reasons.append(
                f"Narrative governance active: geopol={narr.geopol_risk_score:.2f} "
                f"regime={narr.overall_regime} sl={self._narrative_sl_mult:.2f}x "
                f"size={self._narrative_size_scalar:.2f}x"
            )
        return reasons

    def liquidity_warnings(self) -> list[str]:
        reasons = []
        if self._liquidity_halted:
            reasons.append(
                f"Liquidity STRESSED: regime={self._liquidity_regime} "
                f"vol_z={self._liquidity_features.get('volume_z', 0):.2f} "
                f"amihud_z={self._liquidity_features.get('amihud_z', 0):.2f}"
            )
        elif self._liquidity_regime != "NORMAL":
            reasons.append(
                f"Liquidity governance active: regime={self._liquidity_regime} "
                f"sl={self._liquidity_sl_mult:.2f}x size={self._liquidity_size_scalar:.2f}x"
            )
        return reasons

    def halt_config_dict(self) -> dict:
        return dict(self.halt_config)
