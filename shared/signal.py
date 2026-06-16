from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SignalResult:
    signal_data: pd.DataFrame
    signal_type: str
    confidence_pct: float
    label: int


class SignalStrategy(ABC):
    @abstractmethod
    def compute(
        self,
        proba: np.ndarray,
        index: pd.Index,
        threshold: float,
        close: pd.Series,
        position_size: float,
    ) -> SignalResult: ...


class FixedThresholdStrategy(SignalStrategy):
    def compute(
        self,
        proba: np.ndarray,
        index: pd.Index,
        threshold: float,
        close: pd.Series,
        position_size: float,
    ) -> SignalResult:
        probs_long = proba[:, 2]
        probs_short = proba[:, 0]
        signals = pd.Series(0, index=index)
        signals[probs_long > threshold] = 2
        signals[probs_short > threshold] = 0

        signal_data = pd.DataFrame(
            {
                "close": close.reindex(index),
                "signal": signals,
                "prob_long": probs_long,
                "prob_short": probs_short,
                "prob_neutral": proba[:, 1],
                "position_size": position_size,
            },
            index=index,
        )

        if len(signal_data) == 0:
            return SignalResult(
                signal_data=signal_data,
                signal_type="FLAT",
                confidence_pct=0.0,
                label=1,
            )

        latest = signal_data.iloc[-1]
        signal_type = "BUY" if latest["signal"] == 2 else ("SELL" if latest["signal"] == 0 else "FLAT")
        confidence = max(latest["prob_long"], latest["prob_short"])
        confidence_pct = round(float(confidence * 100), 2)
        label = int(latest["signal"])

        return SignalResult(
            signal_data=signal_data,
            signal_type=signal_type,
            confidence_pct=confidence_pct,
            label=label,
        )
