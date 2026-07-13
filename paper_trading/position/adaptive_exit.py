from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("eigencapital.adaptive_exit")


@dataclass
class AdaptiveExitResult:
    new_sl: float | None = None
    action: str = "none"
    description: str = ""
    scale_out_fraction: float | None = None
    scale_out_price: float | None = None


class AdaptiveExitEngine:
    """R-based scale-out + retracement trailing stop engine.

    Four-stage model:
      1. Breakeven lock — move SL to entry at X R-multiple MFE
      2. R-based scale-out — close fraction at target R-multiple
      3. Retracement trail — trail remainder at X% retrace from peak MFE
         Retrace percentage is dynamically tightened when MFE / SL distance
         exceeds configurable thresholds (mfe_ratio_tighten).
      4. Time decay — tighten trailing tolerance as max-hold approaches

    Tracks its own peak price so it can be used independently of
    PositionProtection or DynamicSLTPEngine.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._best_price: float | None = None
        self._breakeven_activated: bool = False
        self._trail_activated: bool = False
        self._sl_update_count: int = 0
        self._current_phase: str = "STATIC"
        self._peak_r: float | None = None
        self._scale_out_fired: bool = False
        self._mfe_tighten_activated: bool = False

    def _apply_mfe_ratio_tighten(self, peak_r: float, config: dict) -> float:
        """Dynamically reduce trail_retrace_pct when MFE/SL ratio is high.

        Config keys (under ``mfe_ratio_tighten``):
          enabled: bool              — default False
          ratio_thresholds: list[[float, float]]
              Each entry is [mfe_sl_ratio, retrace_multiplier].
              Example: [[2.0, 0.8], [3.0, 0.6]] means:
                - When MFE > 2× SL distance, multiply retrace by 0.8
                - When MFE > 3× SL distance, multiply retrace by 0.6

        Returns the effective retrace_pct multiplier [0.0, 1.0].
        """
        tighten_cfg = config.get("mfe_ratio_tighten", {})
        if not tighten_cfg.get("enabled", False):
            return 1.0

        sl_dist_r = max(config.get("sl_distance_r", 1.0), 0.01)
        mfe_sl_ratio = peak_r / sl_dist_r
        thresholds = tighten_cfg.get("ratio_thresholds", [[2.0, 0.8], [3.0, 0.6]])
        if not thresholds:
            return 1.0

        # Find the most aggressive multiplier that applies
        multiplier = 1.0
        for ratio_thresh, retrace_mult in sorted(thresholds, key=lambda x: x[0]):
            if mfe_sl_ratio >= ratio_thresh:
                multiplier = min(multiplier, retrace_mult)

        if multiplier < 1.0:
            self._mfe_tighten_activated = True

        return max(multiplier, 0.1)  # cap at 10% minimum

    def compute(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        current_sl: float,
        vol_at_entry: float,
        bars_since_entry: int,
        config: dict | None = None,
    ) -> AdaptiveExitResult:
        if config is None:
            config = {}

        if side == "long":
            self._best_price = max(self._best_price or entry_price, current_price)
        else:
            self._best_price = min(self._best_price or entry_price, current_price)
        best = self._best_price

        if best == entry_price:
            return AdaptiveExitResult()

        vol = max(vol_at_entry, 1e-9)
        if side == "long":
            peak_r = (best - entry_price) / (entry_price * vol)
        else:
            peak_r = (entry_price - best) / (entry_price * vol)
        self._peak_r = peak_r

        result = AdaptiveExitResult()

        # Stage 1: Breakeven lock
        be_lock_r = config.get("be_lock_r", 0.5)
        if not self._breakeven_activated and peak_r >= be_lock_r:
            new_sl = max(entry_price, current_sl) if side == "long" else min(entry_price, current_sl)

            if (side == "long" and new_sl > current_sl) or (side == "short" and new_sl < current_sl):
                result.new_sl = new_sl
                result.action = "breakeven"
                result.description = f"breakeven at {be_lock_r}R MFE"
                self._breakeven_activated = True
                self._sl_update_count += 1
                self._current_phase = "BREAKEVEN"
                return result

        # Stage 2: R-based scale-out (partial profit taking)
        scale_out_fraction = config.get("scale_out_fraction")
        scale_out_r = config.get("scale_out_r")
        should_scale = (
            scale_out_fraction is not None
            and scale_out_r is not None
            and not self._scale_out_fired
            and peak_r >= scale_out_r
        )
        if should_scale:
            self._scale_out_fired = True
            if side == "long":
                so_price = entry_price + scale_out_r * vol * entry_price
            else:
                so_price = entry_price - scale_out_r * vol * entry_price
            result.scale_out_fraction = scale_out_fraction
            result.scale_out_price = so_price
            result.action = "scale_out"
            result.description = f"scale_out {scale_out_fraction * 100:.0f}% at {scale_out_r}R (price={so_price:.4f})"
            self._sl_update_count += 1
            self._current_phase = "SCALE_OUT"
            return result

        # Stage 3: Retracement trailing (with MFE-ratio dynamic tightening)
        activation_r = config.get("trail_activation_r", 0.8)
        retrace_pct = config.get("trail_retrace_pct", 0.50)
        mfe_mult = self._apply_mfe_ratio_tighten(peak_r, config)
        effective_retrace = retrace_pct * mfe_mult

        if peak_r >= activation_r:
            if side == "long":
                retrace_level = best - effective_retrace * (best - entry_price)
                if retrace_level > current_sl:
                    result.new_sl = retrace_level
                    result.action = "trail"
                    result.description = (
                        f"trail {effective_retrace * 100:.0f}% retrace"
                        f" (peak={best:.4f}, peak_r={peak_r:.2f}"
                        f"{', mfe_ratio_tighten=' + str(mfe_mult) if mfe_mult < 1.0 else ''})"
                    )
            else:
                retrace_level = best + effective_retrace * (entry_price - best)
                if retrace_level < current_sl:
                    result.new_sl = retrace_level
                    result.action = "trail"
                    result.description = (
                        f"trail {effective_retrace * 100:.0f}% retrace"
                        f" (peak={best:.4f}, peak_r={peak_r:.2f}"
                        f"{', mfe_ratio_tighten=' + str(mfe_mult) if mfe_mult < 1.0 else ''})"
                    )
            self._trail_activated = True

        # Stage 4: Time decay — tighten trailing near max hold
        max_hold = config.get("max_hold_candles", 40)
        decay_start = config.get("time_decay_start", max_hold // 2)
        if max_hold > 0 and bars_since_entry >= decay_start and bars_since_entry < max_hold and self._trail_activated:
            progress = (bars_since_entry - decay_start) / max(max_hold - decay_start, 1)
            if progress > 0.3 and result.action == "none":
                tighter_retrace = effective_retrace * max(1.0 - progress * 0.3, 0.3)
                if side == "long":
                    tighter_level = best - tighter_retrace * (best - entry_price)
                    if tighter_level > current_sl:
                        result.new_sl = tighter_level
                        result.action = "time_decay"
                else:
                    tighter_level = best + tighter_retrace * (entry_price - best)
                    if tighter_level < current_sl:
                        result.new_sl = tighter_level
                        result.action = "time_decay"

        if result.new_sl is not None:
            self._sl_update_count += 1

        if self._trail_activated and max_hold > 0 and bars_since_entry >= decay_start and bars_since_entry < max_hold:
            self._current_phase = "DECAY"
        elif self._trail_activated:
            if self._mfe_tighten_activated:
                self._current_phase = "MFE_TIGHTEN"
            else:
                self._current_phase = "TRAILING"
        elif self._breakeven_activated:
            self._current_phase = "BREAKEVEN"
        else:
            self._current_phase = "STATIC"

        return result

    @property
    def phase(self) -> str:
        """SCALE_OUT | BREAKEVEN | MFE_TIGHTEN | TRAILING | DECAY | STATIC"""
        return self._current_phase

    @property
    def peak_mfe_r(self) -> float | None:
        """Best MFE reached this trade in R-units."""
        return self._peak_r

    @property
    def sl_update_count(self) -> int:
        """Number of times SL was updated this trade."""
        return self._sl_update_count
