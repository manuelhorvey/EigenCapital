from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd

from quorrin.domain.entities.signal import SignalResult, SignalType


class SignalService(ABC):
    @abstractmethod
    def compute(
        self,
        proba: np.ndarray,
        index: pd.Index | None,
        threshold: float,
        close: pd.Series | None,
        position_size: float,
    ) -> SignalResult: ...


class FixedThresholdService(SignalService):
    def compute(
        self,
        proba: np.ndarray,
        index: pd.Index | None = None,
        threshold: float = 0.6,
        close: pd.Series | None = None,
        position_size: float = 1.0,
    ) -> SignalResult:
        return generate_signal(proba, threshold=threshold, position_size=position_size)


def generate_signal(
    proba: np.ndarray,
    threshold: float = 0.6,
    position_size: float = 1.0,
) -> SignalResult:
    if proba.ndim == 1:
        probs_long = proba
        probs_short = 1.0 - proba
    elif proba.shape[1] >= 3:
        probs_long = proba[:, 1]
        probs_short = proba[:, 2]
    else:
        probs_long = proba[:, 0]
        probs_short = 1.0 - probs_long

    last_long = float(probs_long[-1]) if len(probs_long) > 0 else 0.0
    last_short = float(probs_short[-1]) if len(probs_short) > 0 else 0.0
    last_neutral = 1.0 - last_long - last_short

    signal_type, confidence = _apply_threshold(last_long, last_short, threshold)
    label = 1 if signal_type == SignalType.BUY else (-1 if signal_type == SignalType.SELL else 0)

    return SignalResult(
        signal_type=signal_type,
        confidence_pct=confidence,
        label=label,
        prob_long=last_long,
        prob_short=last_short,
        prob_neutral=max(last_neutral, 0.0),
        position_size=position_size,
    )


def _apply_threshold(
    prob_long: float,
    prob_short: float,
    threshold: float,
) -> tuple[SignalType, float]:
    if prob_long >= threshold:
        return SignalType.BUY, prob_long
    if prob_short >= threshold:
        return SignalType.SELL, prob_short
    return SignalType.FLAT, max(prob_long, prob_short)
