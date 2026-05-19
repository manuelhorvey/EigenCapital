import pandas as pd
import numpy as np
from typing import Optional

from features.builder import build_features, compute_macro_derived
from features.contract import FeatureContract
from shared.signal import FixedThresholdStrategy
from shared.sizing import VolTargetSizing
from shared.pnl import DefaultPnLStrategy


_signal_strategy = FixedThresholdStrategy()
_sizing_strategy = VolTargetSizing()
_pnl_strategy = DefaultPnLStrategy()


def compute_proba(model, X: pd.DataFrame) -> np.ndarray:
    return model.predict_proba(X)


def compute_signals(
    proba: np.ndarray,
    index: pd.Index,
    threshold: float = 0.45,
) -> pd.DataFrame:
    return _signal_strategy.compute(
        proba, index, threshold,
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


def compute_tb_vol(close: pd.Series, span: int = 100, floor: float = 0.01) -> float:
    returns = np.log(close / close.shift(1))
    vol = returns.ewm(span=span).std()
    return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else floor


def compute_daily_pnl(
    current_value: float,
    direction: int,
    ret: float,
    position_size_fraction: float,
    pos_size: float = 1.0,
) -> float:
    return _pnl_strategy.compute_daily(current_value, direction, ret, position_size_fraction, pos_size)


def compute_position_return(
    side: str,
    entry_price: float,
    exit_price: float,
) -> float:
    if side == "long":
        return exit_price / entry_price - 1
    else:
        return entry_price / exit_price - 1


def compute_sl_tp(
    side: str,
    entry_price: float,
    vol: float,
    multiplier: float = 2.0,
) -> tuple:
    if side == "long":
        sl = entry_price * (1 - vol * multiplier)
        tp = entry_price * (1 + vol * multiplier)
    else:
        sl = entry_price * (1 + vol * multiplier)
        tp = entry_price * (1 - vol * multiplier)
    return sl, tp


def compute_features(
    df: pd.DataFrame,
    macro: pd.DataFrame,
    ref: Optional[pd.DataFrame],
    contract: FeatureContract,
) -> pd.DataFrame:
    return build_features(df, macro, ref, contract)


def compute_macro_derived_wrapper(macro_df: pd.DataFrame) -> pd.DataFrame:
    return compute_macro_derived(macro_df)
