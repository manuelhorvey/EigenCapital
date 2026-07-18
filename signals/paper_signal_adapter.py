import numpy as np
import pandas as pd

from paper_trading.entry.decision import TradeDecision


class PaperSignalAdapter:
    """
    Thin adapter: model probabilities + metadata -> TradeDecision.
    No persistence, no routing, no risk logic.
    """

    @staticmethod
    def from_probabilities(
        asset: str,
        prob_long: float,
        prob_short: float,
        prob_neutral: float,
        close_price: float,
        timestamp: str,
        threshold: float = 0.45,
        position_size: float = 1.0,
        archetype: str = "UNKNOWN",
    ) -> TradeDecision:
        signal = "BUY" if prob_long > threshold else ("SELL" if prob_short > threshold else "FLAT")
        label = 2 if signal == "BUY" else (0 if signal == "SELL" else 1)
        confidence = max(prob_long, prob_short)

        return TradeDecision(
            asset=asset,
            signal=signal,
            label=label,
            confidence=round(float(confidence * 100), 2),
            prob_long=round(float(prob_long), 4),
            prob_short=round(float(prob_short), 4),
            prob_neutral=round(float(prob_neutral), 4),
            close_price=round(float(close_price), 4),
            timestamp=timestamp,
            position_size=float(position_size),
            archetype=archetype,
        )

    @staticmethod
    def from_model_output(
        asset: str,
        proba: np.ndarray,
        close_prices: pd.Series,
        timestamps: pd.DatetimeIndex,
        threshold: float = 0.45,
        position_size: float = 1.0,
        archetype: str = "UNKNOWN",
    ) -> TradeDecision:
        if proba.shape[1] < 3:
            raise ValueError(f"Model returned {proba.shape[1]} classes, expected 3")
        probs_long = proba[:, 2]
        probs_short = proba[:, 0]
        probs_neutral = proba[:, 1]

        idx = -1
        return PaperSignalAdapter.from_probabilities(
            asset=asset,
            prob_long=probs_long[idx],
            prob_short=probs_short[idx],
            prob_neutral=probs_neutral[idx],
            close_price=(
                float(close_prices.iloc[idx]) if isinstance(close_prices, pd.Series) else float(close_prices[idx])
            ),
            timestamp=str(timestamps[idx].date()) if hasattr(timestamps[idx], "date") else str(timestamps[idx]),
            threshold=threshold,
            position_size=position_size,
            archetype=archetype,
        )
