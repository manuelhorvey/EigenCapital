"""Dynamic SL/TP placement engine with ATR, trailing stops, and post-entry adjustment.

Provides four methods:
  1. ``atr`` — ATR-based adaptive barriers (wider when vol high, tighter when low)
  2. ``vol_ewm`` — Original EWM vol-based (backward compatible)
  3. ``trailing`` — Trailing stop that locks in profits after a threshold
  4. ``static`` — Fixed percentage from entry (legacy fallback)

Post-entry adjustment tightens SL when vol drops and moves TP closer
when momentum stalls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger("quantforge.dynamic_sltp")


@dataclass
class SLTPResult:
    stop_loss: float
    take_profit: float
    trailing_activation_price: float | None = None
    method_used: str = "atr"


@dataclass
class TrailingResult:
    trailing_sl: float | None = None
    activated: bool = False
    locked_profit: float | None = None


@dataclass
class ScaleTier:
    fraction: float
    price: float


@dataclass
class PostEntryAdjustment:
    new_sl: float | None = None
    new_tp: float | None = None
    reason: str | None = None


class DynamicSLTPEngine:
    """Multi-method SL/TP placement with trailing and adjustment.

    Parameters
    ----------
    method : str
        One of ``atr``, ``vol_ewm``, ``trailing``, ``static``.
    atr_period : int
        ATR lookback period.
    atr_mult_sl : float
        ATR multiplier for stop-loss distance.
    atr_mult_tp : float
        ATR multiplier for take-profit distance.
    min_rr_ratio : float
        Minimum reward-to-risk ratio enforced at entry.
    trailing_activation_mult : float
        Multiplier on SL distance; price must move this far from entry
        before trailing activates.  E.g. 1.5 = trail activates when
        profit > 1.5× SL distance.
    trailing_distance_mult : float
        Multiplier on current ATR for trailing stop distance once active.
    post_adjust_interval_bars : int
        Minimum bars between post-entry adjustments.
    max_sl_widen_pct : float
        Maximum allowed SL widening fraction (0 = never widen).
    use_gap_protection : bool
        If True, widen SL by expected gap during high-vol sessions.
    calibration_scale : float
        Extra multiplier on the calibration ratio (1.0 = match EWM vol,
        1.2 = 20% wider barriers for higher TP rates).
    """

    def __init__(
        self,
        method: str = "atr",
        atr_period: int = 14,
        atr_mult_sl: float = 2.0,
        atr_mult_tp: float = 3.0,
        min_rr_ratio: float = 1.5,
        trailing_activation_mult: float = 1.5,
        trailing_distance_mult: float = 2.0,
        post_adjust_interval_bars: int = 3,
        max_sl_widen_pct: float = 0.0,
        use_gap_protection: bool = True,
        calibration_scale: float = 1.0,
        confidence_sl_adjust: float = 0.0,
    ):
        self.method = method
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self.min_rr_ratio = min_rr_ratio
        self.trailing_activation_mult = trailing_activation_mult
        self.trailing_distance_mult = trailing_distance_mult
        self.post_adjust_interval_bars = post_adjust_interval_bars
        self.max_sl_widen_pct = max_sl_widen_pct
        self.use_gap_protection = use_gap_protection
        self.calibration_scale = calibration_scale
        self.confidence_sl_adjust = confidence_sl_adjust
        self._best_price_seen: float | None = None

    def reset_best_price(self, entry_price: float) -> None:
        """Reset the best-price tracker at entry (start of a new position)."""
        self._best_price_seen = entry_price

    # ── Public API ────────────────────────────────────────────────

    def compute_barriers(
        self,
        entry_price: float,
        side: str,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        regime: str = "neutral",
        vol: float | None = None,
        meta_confidence: float | None = None,
    ) -> SLTPResult:
        """Compute initial stop-loss and take-profit levels.

        Parameters
        ----------
        entry_price : float
            Fill price of the entry.
        side : str
            ``"long"`` or ``"short"``.
        df : pd.DataFrame
            Price data (must contain ``"close"``).
        sl_mult, tp_mult : float
            Base multipliers from config (regime-adjusted already).
        regime : str
            Regime label for regime-aware override.
        vol : float | None
            Precomputed vol (only used if method == ``vol_ewm``).
        meta_confidence : float | None
            Meta-label P(TP>SL). When set, adjusts SL distance inversely:
            high confidence → tighter SL, low confidence → wider SL.
        """
        if self.method == "atr":
            result = self._atr_barriers(entry_price, side, df, sl_mult, tp_mult, regime)
        elif self.method == "vol_ewm":
            result = self._vol_ewm_barriers(entry_price, side, vol or 0.01, sl_mult, tp_mult, regime)
        elif self.method == "trailing":
            result = self._trailing_initial_barriers(entry_price, side, df, sl_mult, tp_mult, regime)
        else:
            result = self._static_barriers(entry_price, side, vol or 0.01, sl_mult, tp_mult)

        if meta_confidence is not None and self.confidence_sl_adjust > 0:
            factor = self._confidence_sl_factor(meta_confidence)
            if side == "long":
                sl_dist = entry_price - result.stop_loss
                result.stop_loss = entry_price - sl_dist * factor
            else:
                sl_dist = result.stop_loss - entry_price
                result.stop_loss = entry_price + sl_dist * factor

        return result

    def calibrate(self, df: pd.DataFrame) -> None:
        """Auto-calibrate ``atr_mult_sl`` so ATR-based barriers match
        EWM vol-based barriers in current market conditions.

        Call once per asset at init to set the scale factor.
        """
        with np.errstate(all="ignore"):
            ewm_vol = self._estimate_vol(df)
        atr_pct = self._compute_atr(df, self.atr_period) / (float(df["close"].iloc[-1]) + 1e-9)
        if ewm_vol > 0 and atr_pct > 0:
            ratio = ewm_vol / atr_pct
            self.atr_mult_sl = ratio * self.calibration_scale
            logger.info(
                "ATR calibrated: atr_mult_sl=%.3f (ewm_vol=%.4f, atr_pct=%.4f, scale=%.2f)",
                self.atr_mult_sl,
                ewm_vol,
                atr_pct,
                self.calibration_scale,
            )

    def compute_trailing_stop(
        self,
        side: str,
        entry_price: float,
        current_price: float,
        initial_sl: float,
        current_sl: float,
        take_profit: float,
        df: pd.DataFrame,
    ) -> TrailingResult:
        """Compute new trailing stop level if price has moved favourably.

        Trailing activates when price exceeds ``trailing_activation_mult``
        times the initial SL distance.  Once active, the stop is a fixed
        ATR multiple behind the best price seen.
        """
        if side == "long":
            if self._best_price_seen is None:
                self._best_price_seen = entry_price
            self._best_price_seen = max(self._best_price_seen, current_price)
            best = self._best_price_seen
            move = (best - entry_price) / (entry_price - initial_sl + 1e-9)
        else:
            if self._best_price_seen is None:
                self._best_price_seen = entry_price
            self._best_price_seen = min(self._best_price_seen, current_price)
            best = self._best_price_seen
            move = (entry_price - best) / (initial_sl - entry_price + 1e-9)

        if move >= self.trailing_activation_mult:
            atr = self._compute_atr(df, self.atr_period)
            dist = atr * self.trailing_distance_mult
            new_sl = best - dist if side == "long" else best + dist
            if new_sl is not None and self._is_tighter(new_sl, current_sl, side):
                locked = (best - entry_price) / entry_price if side == "long" else (entry_price - best) / entry_price
                return TrailingResult(
                    trailing_sl=new_sl,
                    activated=True,
                    locked_profit=round(locked, 4),
                )
        return TrailingResult(activated=False)

    def post_entry_adjust(
        self,
        side: str,
        entry_price: float,
        current_sl: float,
        current_tp: float,
        df: pd.DataFrame,
        vol: float | None = None,
        bars_since_entry: int = 0,
    ) -> PostEntryAdjustment:
        """Narrow SL or adjust TP after entry based on new information.

        Rules:
        - If current vol is significantly lower than entry vol, tighten SL.
        - If price stalled near TP without hitting it, nudge TP closer.
        - Never widen SL (unless ``max_sl_widen_pct > 0``).
        """
        if bars_since_entry < self.post_adjust_interval_bars:
            return PostEntryAdjustment()

        current_vol = self._estimate_vol(df)
        if vol is not None and current_vol > 0:
            vol_ratio = current_vol / vol
            if vol_ratio < 0.7:
                new_sl = self._propose_tighter_sl(side, entry_price, current_sl, vol_ratio)
                if new_sl is not None:
                    return PostEntryAdjustment(
                        new_sl=new_sl,
                        reason=f"vol_dropped_{vol_ratio:.2f}x",
                    )

        price = float(df["close"].iloc[-1])
        if side == "long":
            progress = (price - entry_price) / (current_tp - entry_price + 1e-9)
        else:
            progress = (entry_price - price) / (entry_price - current_tp + 1e-9)

        if 0.6 < progress < 0.95 and bars_since_entry > 5:
            factor = 0.85
            if side == "long":
                new_tp = entry_price + (current_tp - entry_price) * factor
            else:
                new_tp = entry_price - (entry_price - current_tp) * factor
            return PostEntryAdjustment(
                new_tp=new_tp,
                reason=f"tp_nudged_{factor:.2f}x_progress_{progress:.2f}",
            )

        return PostEntryAdjustment()

    def _confidence_sl_factor(self, meta_confidence: float) -> float:
        """Map meta-confidence [threshold, 1.0] → SL distance multiplier.

        High confidence → tighter SL (factor < 1), low confidence → wider SL.
        At threshold (e.g. 0.55) returns 1.0 (baseline); at 1.0 returns
        (1 - confidence_sl_adjust).
        """
        threshold = 0.5
        clamped = max(threshold, min(meta_confidence, 1.0))
        return 1.0 - (clamped - threshold) / (1.0 - threshold + 1e-9) * self.confidence_sl_adjust

    # ── Barrier computation methods ───────────────────────────────

    def _atr_barriers(
        self,
        entry_price: float,
        side: str,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        regime: str,
    ) -> SLTPResult:
        # Use ATR as a responsive vol estimator.  Convert ATR(price) → %
        # so it's comparable to EWM vol, then apply config multipliers.
        atr_price = self._compute_atr(df, self.atr_period)
        atr_pct = atr_price / (entry_price + 1e-9)

        # Regime overlay: widen SL in volatile regimes, narrow in calm
        reg_sl = self._regime_sl_mult(regime)
        reg_tp = self._regime_tp_mult(regime)

        # Effective vol for barrier placement: blend ATR % with config multipliers
        vol_used = atr_pct * self.atr_mult_sl  # atr_mult_sl calibrates ATR → vol scale
        sl_dist = entry_price * vol_used * sl_mult * reg_sl
        tp_dist = entry_price * vol_used * tp_mult * reg_tp

        # Enforce minimum RR ratio
        rr = tp_dist / (sl_dist + 1e-9)
        if rr < self.min_rr_ratio:
            tp_dist = sl_dist * self.min_rr_ratio

        # Gap protection: add expected gap to SL distance
        if self.use_gap_protection:
            gap = self._estimate_gap_risk(df)
            sl_dist += gap

        if side == "long":
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        return SLTPResult(
            stop_loss=max(sl, 0.0) if side == "long" else sl,
            take_profit=tp if side == "long" else max(tp, 0.0),
            method_used="atr",
        )

    def _vol_ewm_barriers(
        self,
        entry_price: float,
        side: str,
        vol: float,
        sl_mult: float,
        tp_mult: float,
        regime: str,
    ) -> SLTPResult:
        reg_sl = self._regime_sl_mult(regime) * sl_mult
        reg_tp = self._regime_tp_mult(regime) * tp_mult

        if side == "long":
            sl = entry_price * (1 - vol * reg_sl)
            tp = entry_price * (1 + vol * reg_tp)
        else:
            sl = entry_price * (1 + vol * reg_sl)
            tp = entry_price * (1 - vol * reg_tp)

        return SLTPResult(stop_loss=sl, take_profit=tp, method_used="vol_ewm")

    def _trailing_initial_barriers(
        self,
        entry_price: float,
        side: str,
        df: pd.DataFrame,
        sl_mult: float,
        tp_mult: float,
        regime: str,
    ) -> SLTPResult:
        result = self._atr_barriers(entry_price, side, df, sl_mult, tp_mult, regime)
        result.method_used = "trailing"
        activation = self.trailing_activation_mult * abs(entry_price - result.stop_loss)
        result.trailing_activation_price = entry_price + activation if side == "long" else entry_price - activation
        return result

    def _static_barriers(
        self,
        entry_price: float,
        side: str,
        vol: float,
        sl_mult: float,
        tp_mult: float,
    ) -> SLTPResult:
        if side == "long":
            sl = entry_price * (1 - vol * sl_mult)
            tp = entry_price * (1 + vol * tp_mult)
        else:
            sl = entry_price * (1 + vol * sl_mult)
            tp = entry_price * (1 - vol * tp_mult)
        return SLTPResult(stop_loss=sl, take_profit=tp, method_used="static")

    # ── Helpers ───────────────────────────────────────────────────

    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df.get("high", df["close"])
        low = df.get("low", df["close"])
        close = df["close"]

        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(period, min_periods=1).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) and atr > 0 else 0.01

    def _estimate_vol(self, df: pd.DataFrame) -> float:
        returns = np.log(df["close"] / df["close"].shift(1))
        vol = returns.ewm(span=100).std().iloc[-1]
        return float(vol) if not pd.isna(vol) and vol > 0 else 0.01

    def _estimate_gap_risk(self, df: pd.DataFrame) -> float:
        """Estimate expected overnight/weekend gap in price units."""
        if len(df) < 5:
            return 0.0
        gaps = abs(df["close"].pct_change().shift(-1))
        gap = gaps.rolling(20).mean().iloc[-1] * float(df["close"].iloc[-1])
        return float(gap) if not pd.isna(gap) else 0.0

    def _regime_sl_mult(self, regime: str) -> float:
        multipliers = {
            "calm": 0.8,
            "range": 0.8,
            "trend": 1.0,
            "neutral": 1.0,
            "volatile": 1.3,
            "crisis": 1.5,
        }
        return multipliers.get(regime.lower(), 1.0)

    def _regime_tp_mult(self, regime: str) -> float:
        multipliers = {
            "calm": 1.2,
            "range": 1.2,
            "trend": 1.0,
            "neutral": 1.0,
            "volatile": 0.8,
            "crisis": 0.6,
        }
        return multipliers.get(regime.lower(), 1.0)

    def _propose_tighter_sl(
        self,
        side: str,
        entry_price: float,
        current_sl: float,
        vol_ratio: float,
    ) -> float | None:
        if side == "long":
            current_dist = entry_price - current_sl
            new_dist = current_dist * vol_ratio
            new_sl = entry_price - new_dist
            if new_sl < current_sl + 1e-9:  # wider or equal
                if self.max_sl_widen_pct > 0:
                    max_widen = current_sl * (1 - self.max_sl_widen_pct)
                    return max(new_sl, max_widen)
                return None
            return new_sl
        else:
            current_dist = current_sl - entry_price
            new_dist = current_dist * vol_ratio
            new_sl = entry_price + new_dist
            if new_sl > current_sl - 1e-9:  # wider or equal
                if self.max_sl_widen_pct > 0:
                    max_widen = current_sl * (1 + self.max_sl_widen_pct)
                    return min(new_sl, max_widen)
                return None
            return new_sl

    def _is_tighter(self, proposed: float, current: float, side: str) -> bool:
        """True if proposed SL is tighter (closer to entry) than current."""
        if side == "long":
            return proposed > current
        else:
            return proposed < current


def build_dynamic_sltp_from_config(asset_config: dict, df: pd.DataFrame | None = None) -> DynamicSLTPEngine:
    """Construct engine from YAML config dict, optionally calibrating with price data."""
    sltp_cfg = asset_config.get("dynamic_sltp", {})
    engine = DynamicSLTPEngine(
        method=sltp_cfg.get("method", "atr"),
        atr_period=sltp_cfg.get("atr_period", 14),
        atr_mult_sl=sltp_cfg.get("atr_mult_sl", 2.0),
        atr_mult_tp=sltp_cfg.get("atr_mult_tp", 3.0),
        min_rr_ratio=sltp_cfg.get("min_rr_ratio", 1.5),
        trailing_activation_mult=sltp_cfg.get("trailing_activation_mult", 1.5),
        trailing_distance_mult=sltp_cfg.get("trailing_distance_mult", 2.0),
        post_adjust_interval_bars=sltp_cfg.get("post_adjust_interval_bars", 3),
        max_sl_widen_pct=sltp_cfg.get("max_sl_widen_pct", 0.0),
        use_gap_protection=sltp_cfg.get("use_gap_protection", True),
        calibration_scale=sltp_cfg.get("calibration_scale", 1.0),
        confidence_sl_adjust=sltp_cfg.get("confidence_sl_adjust", 0.0),
    )
    if df is not None and sltp_cfg.get("auto_calibrate", True):
        engine.calibrate(df)
    return engine
