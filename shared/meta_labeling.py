"""Meta-labeling layer: secondary model that scores primary signal confidence.

Trains a lightweight binary classifier on historical trade outcomes,
then filters/reduces primary signals based on predicted profitability.
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger("quantforge.meta_labeling")

META_CONFIDENCE_THRESHOLD_FULL = 0.55
META_CONFIDENCE_THRESHOLD_REDUCED = 0.40
MIN_TRADES_FOR_TRAINING = 50

FEATURE_NAMES = [
    "primary_confidence",
    "regime_state_encoded",
    "feature_stability_penalty",
    "vol_zscore",
    "days_since_regime_change",
]


@dataclass
class MetaInferenceResult:
    meta_confidence: float
    meta_decision: str  # FULL / REDUCED / SKIP
    scale_factor: float
    # Geometry adjustments: multiply base sl_mult/tp_mult by these
    sl_adjust: float = 1.0
    tp_adjust: float = 1.0


def encode_regime(state: str) -> int:
    mapping = {"GREEN": 2, "YELLOW": 1, "RED": 0, "LOW_VOL": 2, "TRANSITION": 1, "HIGH_VOL": 0}
    return mapping.get(state.upper().replace(' ', '_'), 1)


def compute_vol_zscore(close: pd.Series, window: int = 21) -> float:
    rets = close.pct_change().dropna()
    if len(rets) < window + 5:
        return 0.0
    recent_vol = float(rets.iloc[-window:].std())
    hist_vol = float(rets.iloc[-252:].std()) if len(rets) >= 252 else float(rets.std())
    if hist_vol < 1e-10:
        return 0.0
    return (recent_vol - hist_vol) / hist_vol


def decision_from_confidence(confidence: float,
                              base_sl_mult: float = 1.0,
                              base_tp_mult: float = 1.0) -> MetaInferenceResult:
    """Convert meta-model confidence into execution decision with geometry adjustments.

    LOW confidence → SKIP (don't trade)
    MEDIUM confidence → REDUCED size + tighter SL/TP (cut losses fast, take quick profits)
    HIGH confidence → FULL size + standard geometry (let winners run)

    Args:
        confidence: predicted probability of winning trade [0, 1]
        base_sl_mult: base stop-loss multiplier before adjustment
        base_tp_mult: base take-profit multiplier before adjustment

    Returns:
        MetaInferenceResult with scale_factor, sl_adjust, tp_adjust
    """
    if confidence >= META_CONFIDENCE_THRESHOLD_FULL:
        return MetaInferenceResult(
            meta_confidence=round(confidence, 4),
            meta_decision="FULL",
            scale_factor=1.0,
            sl_adjust=1.0,
            tp_adjust=1.0,
        )
    elif confidence >= META_CONFIDENCE_THRESHOLD_REDUCED:
        # Tighter: reduce SL by 20%, bring TP closer by 20%
        return MetaInferenceResult(
            meta_confidence=round(confidence, 4),
            meta_decision="REDUCED",
            scale_factor=0.5,
            sl_adjust=0.80,
            tp_adjust=0.80,
        )
    else:
        return MetaInferenceResult(
            meta_confidence=round(confidence, 4),
            meta_decision="SKIP",
            scale_factor=0.0,
            sl_adjust=0.0,
            tp_adjust=0.0,
        )


class MetaModel:
    """Lightweight binary classifier for meta-labeling."""

    def __init__(self):
        self.model: Optional[LogisticRegression] = None
        self.scaler: Optional[StandardScaler] = None
        self._trained = False
        self._n_trades = 0

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train(self, features: pd.DataFrame, labels: pd.Series) -> None:
        if len(features) < MIN_TRADES_FOR_TRAINING:
            logger.info(
                "skipping meta-model training: %d trades < %d minimum",
                len(features), MIN_TRADES_FOR_TRAINING,
            )
            self._trained = False
            self._n_trades = len(features)
            return

        expected = set(FEATURE_NAMES)
        missing = expected - set(features.columns)
        if missing:
            logger.warning("missing features for meta-model: %s", missing)
            self._trained = False
            return

        X = features[FEATURE_NAMES].values
        y = labels.values

        # Handle constant features by adding tiny jitter so the scaler doesn't choke
        col_std = np.std(X, axis=0)
        if col_std.min() < 1e-10:
            jitter_mask = col_std < 1e-10
            jitter = np.random.default_rng(42).normal(0, 1e-6, size=(X.shape[0], jitter_mask.sum()))
            X[:, jitter_mask] += jitter
            logger.info("added jitter to %d constant features in meta-model input", int(jitter_mask.sum()))

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = LogisticRegression(
            class_weight="balanced",
            C=1.0,
            solver="lbfgs",
            max_iter=1000,
            random_state=42,
        )
        self.model.fit(X_scaled, y)
        self._trained = True
        self._n_trades = len(features)
        logger.info(
            "meta-model trained on %d trades, %d features",
            len(features), X.shape[1],
        )

    def predict(self, features: dict) -> MetaInferenceResult:
        if not self._trained or self.model is None or self.scaler is None:
            return MetaInferenceResult(
                meta_confidence=0.5,
                meta_decision="FULL",
                scale_factor=1.0,
            )

        missing = [f for f in FEATURE_NAMES if f not in features]
        if missing:
            logger.warning("meta-model predict missing features: %s", missing)
            return MetaInferenceResult(
                meta_confidence=0.5,
                meta_decision="FULL",
                scale_factor=1.0,
            )

        row = np.array([[features[f] for f in FEATURE_NAMES]])
        row_scaled = self.scaler.transform(row)
        proba = self.model.predict_proba(row_scaled)[0]
        # proba[0] = class 0 (losing trade), proba[1] = class 1 (winning trade)
        win_prob = float(proba[1])
        return decision_from_confidence(win_prob)

    def get_state(self) -> dict:
        return {
            "trained": self._trained,
            "n_trades": self._n_trades,
        }


def build_meta_features_from_trade(
    trade: dict,
    prob_history: list[dict],
    validity_history: list[dict],
    feature_stability_penalty: float,
    close: pd.Series,
) -> Optional[dict]:
    """Build a single feature row for a completed trade.

    Matches the trade's entry_date to the closest prob_history entry
    to extract primary_confidence and regime state at signal time.
    """
    entry_date = trade.get("entry_date", "")
    if not entry_date:
        return None

    # Find the prob_history entry closest to entry_date
    matching_signal = None
    for p in reversed(prob_history):
        if p.get("date", "") <= entry_date:
            matching_signal = p
            break
    if matching_signal is None and prob_history:
        matching_signal = prob_history[0]
    if matching_signal is None:
        return None

    primary_confidence = matching_signal.get("confidence", 50) / 100.0

    # Find validity state at entry time
    regime_state = "YELLOW"
    days_since_regime_change = 999
    if validity_history:
        for v in validity_history:
            v_ts = v.get("timestamp", "")
            if isinstance(v_ts, str) and v_ts <= entry_date:
                regime_state = v.get("state", "YELLOW")
                days_since_regime_change = v.get("periods_in_state", 999)
            elif hasattr(v_ts, "strftime") and str(v_ts)[:10] <= entry_date:
                regime_state = v.get("state", "YELLOW")
                days_since_regime_change = v.get("periods_in_state", 999)

    vol_z = compute_vol_zscore(close)

    return {
        "primary_confidence": primary_confidence,
        "regime_state_encoded": encode_regime(regime_state),
        "feature_stability_penalty": feature_stability_penalty,
        "vol_zscore": vol_z,
        "days_since_regime_change": float(days_since_regime_change),
    }


def build_meta_training_data(
    trade_log: list[dict],
    prob_history: list[dict],
    validity_history: list[dict],
    feature_stability_penalty: float,
    close: pd.Series,
) -> tuple[Optional[pd.DataFrame], Optional[pd.Series]]:
    """Build training DataFrame and label Series from historical trades."""
    rows = []
    labels = []
    for trade in trade_log:
        if trade.get("pnl") is None:
            continue
        features = build_meta_features_from_trade(
            trade, prob_history, validity_history,
            feature_stability_penalty, close,
        )
        if features is None:
            continue
        rows.append(features)
        labels.append(1 if trade["pnl"] > 0 else 0)

    if len(rows) < MIN_TRADES_FOR_TRAINING:
        return None, None
    return pd.DataFrame(rows), pd.Series(labels)


def build_inference_features(
    primary_confidence: float,
    regime_state: str,
    periods_in_state: int,
    feature_stability_penalty: float,
    close: pd.Series,
) -> dict:
    return {
        "primary_confidence": primary_confidence,
        "regime_state_encoded": encode_regime(regime_state),
        "feature_stability_penalty": feature_stability_penalty,
        "vol_zscore": compute_vol_zscore(close),
        "days_since_regime_change": float(periods_in_state),
    }
