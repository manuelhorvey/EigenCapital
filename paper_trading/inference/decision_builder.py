"""Decision builder — constructs TradeDecision from inference results.

Extracted from ``AssetInferencePipeline._build_decision`` as part of
MAINT-01 (split oversized modules).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import pytz

from paper_trading.entry.decision import SignalType, TradeDecision

logger = logging.getLogger("eigencapital.decision_builder")

ET = pytz.timezone("US/Eastern")


def build_decision(
    asset: Any,
    result: Any,
    pos_size: float,
    archetype: str,
    df: pd.DataFrame,
    feature_hash: str = "",
) -> TradeDecision:
    """Build a ``TradeDecision`` from inference results and asset state.

    Extracted from ``AssetInferencePipeline._build_decision``.

    Args:
        asset: The asset engine (must have ``signal_data``, ``current_price``, etc.).
        result: Signal computation result with ``signal_data``, ``signal_type``,
            ``label``, ``confidence_pct``.
        pos_size: Position size from the sizing strategy.
        archetype: Classified archetype label.
        df: Price DataFrame with ``close`` column (fallback for close price).
        feature_hash: Feature vector hash for traceability.

    Returns:
        A populated ``TradeDecision``.
    """
    # Record inference proxy directions
    asset._last_macro_dir = None
    asset._last_blend_dir = None
    asset._entry_signal_dir = (
        1 if result.signal_type == "BUY" else (-1 if result.signal_type == "SELL" else 0)
    )

    macro_head = getattr(asset.model, "macro_head", None) if asset.model else None
    if macro_head is not None:
        try:
            macro_cols = [c for c in macro_head.features if c in result.signal_data.columns]
            if len(macro_cols) >= 3:
                macro_probs = macro_head.predict_proba(
                    result.signal_data.iloc[[-1]][macro_cols]
                )[0]
                asset._last_macro_dir = int(np.argmax(macro_probs)) - 1
                asset._last_blend_dir = int(np.argmax(result.signal_data.iloc[-1].values)) - 1
        except (ValueError, TypeError, IndexError):
            logger.debug("%s: macro proxy inference failed", asset.name)

    # ── Extract signal data ─────────────────────────────────────────
    asset.signal_data = result.signal_data
    latest = asset.signal_data.iloc[-1]
    asset.last_signal_date = latest.name

    close_price = float(latest["close"])
    if pd.isna(close_price) or close_price == 0.0:
        close_price = float(df["close"].ffill().iloc[-1])
    if pd.isna(close_price) and asset.current_price is not None:
        close_price = float(asset.current_price)

    # ── Meta-label confidence ───────────────────────────────────────
    meta_proba = getattr(asset, "_last_meta_proba", None)
    meta_label_confidence = (
        round(float(meta_proba) * 100.0, 2) if meta_proba is not None else None
    )

    # ── Calibrated confidence ───────────────────────────────────────
    cal_conf_override = getattr(asset, "_calibrated_confidence", None)
    final_confidence = (
        round(float(cal_conf_override * 100), 2)
        if cal_conf_override is not None
        else result.confidence_pct
    )

    decision = TradeDecision(
        asset=asset.name,
        signal=SignalType(result.signal_type),
        label=result.label,
        confidence=final_confidence,
        prob_long=round(float(latest["prob_long"]), 4),
        prob_short=round(float(latest["prob_short"]), 4),
        prob_neutral=round(float(latest["prob_neutral"]), 4),
        close_price=round(close_price, 4),
        timestamp=str(datetime.now(tz=ET).date()),
        position_size=float(pos_size),
        archetype=archetype,
        feature_hash=feature_hash,
        meta_label_confidence=meta_label_confidence,
    )
    logger.debug(
        "%s ENTRY: signal=%s close_price=%.4f current_price=%s confidence=%.1f pos_size=%.4f",
        asset.name,
        decision.signal,
        decision.close_price,
        asset.current_price,
        decision.confidence,
        pos_size,
    )
    return decision
