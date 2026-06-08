import numpy as np
import pandas as pd

from shared.pnl import DefaultPnLStrategy
from shared.signal import FixedThresholdStrategy
from shared.sizing import VolTargetSizing

_signal_strategy = FixedThresholdStrategy()
_sizing_strategy = VolTargetSizing()
_pnl_strategy = DefaultPnLStrategy()


def compute_proba(model, x: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(x)


def compute_signals(
    proba: np.ndarray,
    index: pd.Index,
    threshold: float = 0.45,
) -> pd.DataFrame:
    return _signal_strategy.compute(
        proba,
        index,
        threshold,
        close=pd.Series([0.0], index=index[:1]),
        position_size=1.0,
    ).signal_data.drop(columns=["close"], errors="ignore")


def signal_type_and_confidence(
    signal_value: int,
    prob_long: float,
    prob_short: float,
) -> tuple:
    signal_type = "BUY" if signal_value == 2 else ("SELL" if signal_value == 0 else "FLAT")
    confidence = max(prob_long, prob_short)
    confidence_pct = round(float(confidence * 100), 2)
    return signal_type, confidence, confidence_pct


def compute_vol_scalar(
    close: pd.Series,
    window: int = 30,
    target_vol: float = 0.30,
) -> float:
    config = {"vol_scalar": True} if window == 30 and target_vol == 0.30 else {}
    return _sizing_strategy.compute(close, config)


def compute_daily_pnl(
    current_value: float,
    direction: int,
    ret: float,
    position_size_fraction: float,
    pos_size: float = 1.0,
) -> float:
    return _pnl_strategy.compute_daily(current_value, direction, ret, position_size_fraction, pos_size)
