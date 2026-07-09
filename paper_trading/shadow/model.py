"""Shadow model runner — runs candidate models alongside production for comparison.

Shadow models share the same feature vector as production but produce independent
predictions. They never influence live trading — the pipeline is a pure observation
layer.

Usage:
    runner = ShadowModelRunner(asset_name, model_path)
    result = runner.run(feature_vector)
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import xgboost as xgb

logger = logging.getLogger("eigencapital.shadow_model")


@dataclass
class ShadowResult:
    """Output from a single shadow model inference."""

    shadow_id: str
    proba_long: float
    proba_short: float
    proba_neutral: float
    signal: str  # BUY / SELL / HOLD
    confidence: float
    inference_time_ms: float
    model_hash: str
    feature_hash: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ShadowModelSpec:
    """Specification for a shadow model to run alongside production.

    Stored in ``configs/domains/shadow_models.yaml`` for persistent config.
    """

    id: str
    model_path: str
    model_type: str = "xgboost"
    status: str = "offline"  # offline | shadow | canary | deployed


class ShadowModelRunner:
    """Loads and runs a candidate model for shadow comparison.

    Thread-safe (model objects are read-only after load). Lazy-loads the model
    on first call to avoid memory pressure for idle shadows.
    """

    def __init__(
        self,
        shadow_id: str,
        model_path: str | Path,
        max_inference_ms: float = 50.0,
        circuit_breaker_tolerance: int = 5,
    ):
        self.shadow_id = shadow_id
        self.model_path = Path(model_path)
        self._model: xgb.XGBClassifier | None = None
        self._model_hash: str | None = None
        self._consecutive_timeouts = 0
        self._disabled_until: float = 0.0
        self._max_ms = max_inference_ms
        self._cb_tolerance = circuit_breaker_tolerance

    def _load(self) -> bool:
        if not self.model_path.exists():
            logger.warning("Shadow model %s not found at %s", self.shadow_id, self.model_path)
            return False
        try:
            self._model = xgb.XGBClassifier()
            self._model.load_model(str(self.model_path))
            with open(self.model_path, "rb") as f:
                self._model_hash = hashlib.sha256(f.read()).hexdigest()[:16]
            return True
        except (OSError, ValueError) as e:
            logger.error("Failed to load shadow model %s: %s", self.shadow_id, e)
            return False

    def run(self, feature_vector: dict[str, float], feature_hash: str = "") -> ShadowResult | None:
        """Run shadow inference on a single feature vector.

        Returns None if the model is unavailable, circuit-broken, or inference fails.
        """
        now = time.time()
        if now < self._disabled_until:
            self._consecutive_timeouts += 1  # will be cleared on next successful run
            if self._consecutive_timeouts >= self._cb_tolerance:
                self._disabled_until = now + 86400  # 24h cool-off
                logger.warning(
                    "Shadow model %s circuit-breaker: %d consecutive timeouts, cooling off 24h",
                    self.shadow_id,
                    self._consecutive_timeouts,
                )
            return None

        if self._model is None and not self._load():
            return None

        t0 = time.perf_counter()
        try:
            feature_array = np.array([list(feature_vector.values())]).astype(np.float32)
            proba = self._model.predict_proba(feature_array)[0]
        except (ValueError, RuntimeError) as exc:
            logger.warning("Shadow model %s inference failed: %s", self.shadow_id, exc)
            return None

        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > self._max_ms:
            self._consecutive_timeouts += 1
        else:
            self._consecutive_timeouts = 0

        proba_long = float(proba[1])
        proba_short = float(proba[0])
        proba_neutral = 1.0 - proba_long - proba_short

        if proba_long > proba_short and proba_long > 0.5:
            signal = "BUY"
            confidence = proba_long
        elif proba_short > proba_long and proba_short > 0.5:
            signal = "SELL"
            confidence = proba_short
        else:
            signal = "HOLD"
            confidence = max(proba_long, proba_short)

        self._consecutive_timeouts = 0

        return ShadowResult(
            shadow_id=self.shadow_id,
            proba_long=proba_long,
            proba_short=proba_short,
            proba_neutral=proba_neutral,
            signal=signal,
            confidence=confidence,
            inference_time_ms=elapsed_ms,
            model_hash=self._model_hash or "unknown",
            feature_hash=feature_hash,
            timestamp=now,
        )
