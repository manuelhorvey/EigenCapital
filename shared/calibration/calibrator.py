"""Calibration models — transforms raw binary classifier probabilities.

Two implementations:
    1. BinnedCalibrator — non-parametric, robust, recommended default.
        Divides [0, 1] into equal-width bins; each bin stores the empirical
        P(positive | bin). Linear interpolation between bin centers.

        2. BetaCalibrator — parametric, smoother, requires more data.
       Fits a Beta distribution to the logit of predictions via
       maximum likelihood. More sample-efficient but less robust
       to distribution shift.

Both implement the CalibrationMethod protocol:
    fit(p_long, outcomes) -> Self
    calibrate(p_long) -> np.ndarray
    save(path) / load(path)
"""

from __future__ import annotations

import json
import logging
import sys
import typing
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

logger = logging.getLogger("eigencapital.calibration")


def compute_ece(
    probs: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error."""
    probs = np.asarray(probs, dtype=float)
    outcomes = np.asarray(outcomes, dtype=int)
    if len(probs) < n_bins:
        return 0.0
    bin_boundaries = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n_total = len(probs)
    for i in range(n_bins):
        lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
        in_bin = (probs >= lo) & (probs < hi)
        if i == n_bins - 1:
            in_bin |= probs == 1.0
        n_bin = in_bin.sum()
        if n_bin > 0:
            bin_acc = outcomes[in_bin].mean()
            bin_conf = probs[in_bin].mean()
            ece += (n_bin / n_total) * abs(bin_acc - bin_conf)
    return float(ece)


class CalibrationMethod(ABC):
    """Protocol for a probability calibration model."""

    fitted: bool = False

    @abstractmethod
    def fit(self, p_long: np.ndarray, outcomes: np.ndarray) -> Self: ...

    @abstractmethod
    def calibrate(self, p_long: np.ndarray) -> np.ndarray: ...

    @abstractmethod
    def save(self, path: str | Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: str | Path) -> Self: ...


class BinnedCalibrator(CalibrationMethod):
    """Non-parametric binned calibration with linear interpolation.

    Divides [0, 1] into n_bins equal-width bins. Each bin stores the
    empirical P(outcome=1 | bin). Calibration uses linear interpolation
    between bin centers. Extrapolation clamps to nearest bin center.

    This is the RECOMMENDED default — robust to fold-to-fold distribution
    shift, no distributional assumptions, and reliable with >=50 samples.

    Reference: Zadrozny & Elkan (2001), "Obtaining calibrated probability
    estimates from decision trees and naive Bayesian classifiers."
    """

    def __init__(self, n_bins: int = 10, min_samples_per_bin: int = 5):
        self.n_bins = n_bins
        self.min_samples_per_bin = min_samples_per_bin
        self.bin_centers: np.ndarray | None = None
        self.bin_empirical_probs: np.ndarray | None = None
        self.fitted = False

    def fit(self, p_long: np.ndarray, outcomes: np.ndarray) -> Self:
        p_long = np.asarray(p_long, dtype=float)
        outcomes = np.asarray(outcomes, dtype=int)

        bin_boundaries = np.linspace(0.0, 1.0, self.n_bins + 1)
        centers = np.empty(self.n_bins)
        empirical = np.empty(self.n_bins)

        for i in range(self.n_bins):
            lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
            in_bin = (p_long >= lo) & (p_long < hi)
            if i == self.n_bins - 1:
                in_bin |= p_long == 1.0
            centers[i] = (lo + hi) / 2.0
            n_bin = in_bin.sum()
            if n_bin >= self.min_samples_per_bin:
                empirical[i] = outcomes[in_bin].mean()
            else:
                empirical[i] = 0.5  # neutral fallback for sparse bins

        self.bin_centers = centers
        self.bin_empirical_probs = empirical
        self.fitted = True
        return self

    def calibrate(self, p_long: np.ndarray) -> np.ndarray:
        if not self.fitted or self.bin_centers is None or self.bin_empirical_probs is None:
            logger.warning("BinnedCalibrator not fitted — returning raw probabilities")
            return np.asarray(p_long, dtype=float)

        p_long = np.asarray(p_long, dtype=float).ravel()
        result = np.interp(p_long, self.bin_centers, self.bin_empirical_probs)
        return typing.cast(np.ndarray, np.clip(result, 0.001, 0.999))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "type": "BinnedCalibrator",
            "n_bins": self.n_bins,
            "min_samples_per_bin": self.min_samples_per_bin,
            "bin_centers": self.bin_centers.tolist() if self.bin_centers is not None else None,
            "bin_empirical_probs": self.bin_empirical_probs.tolist() if self.bin_empirical_probs is not None else None,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved BinnedCalibrator to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        n_bins = int(data["n_bins"])
        min_samples = int(data.get("min_samples_per_bin", 5))
        cal = cls(n_bins=n_bins, min_samples_per_bin=min_samples)
        if data.get("bin_centers") is not None:
            cal.bin_centers = np.array(data["bin_centers"], dtype=float)
            cal.bin_empirical_probs = np.array(data["bin_empirical_probs"], dtype=float)
            cal.fitted = True
        return cal


class BetaCalibrator(CalibrationMethod):
    """Beta calibration — 3-parameter transformation using Beta distribution.

    Fits: calibrated_p = 1 / (1 + exp(-(a * logit(p) + b)))
    where logit(p) = log(p / (1 - p)).

    This is a special case of Beta calibration (Kull, Silva Filho & Flach, 2017)
    that corresponds to the Beta(alpha, beta) CDF. More flexible than Platt
    scaling (which is a special case with fixed shape), but more stable than
    isotonic regression.

    Requires MORE data than BinnedCalibrator (recommended >=200 samples).
    """

    def __init__(self):
        self.a: float = 1.0
        self.b: float = 0.0
        self.fitted = False

    def fit(self, p_long: np.ndarray, outcomes: np.ndarray) -> Self:
        p_long = np.asarray(p_long, dtype=float)
        outcomes = np.asarray(outcomes, dtype=int)

        # Clip to avoid log(0)
        eps = 1e-6
        p = np.clip(p_long, eps, 1.0 - eps)
        logit_p = np.log(p / (1.0 - p))

        from scipy.optimize import minimize

        def neg_log_likelihood(params):
            a, b = params
            logits = a * logit_p + b
            pred = expit(logits)
            pred = np.clip(pred, eps, 1.0 - eps)
            return -np.sum(outcomes * np.log(pred) + (1.0 - outcomes) * np.log(1.0 - pred))

        result = minimize(neg_log_likelihood, [1.0, 0.0], method="L-BFGS-B")
        if result.success:
            self.a, self.b = result.x
            self.fitted = True
        else:
            logger.warning("BetaCalibrator fit failed: %s — using identity", result.message)
            self.a, self.b = 1.0, 0.0
            self.fitted = False
        return self

    def calibrate(self, p_long: np.ndarray) -> np.ndarray:
        if not self.fitted:
            logger.warning("BetaCalibrator not fitted — returning raw probabilities")
            return np.asarray(p_long, dtype=float)

        p_long = np.asarray(p_long, dtype=float)
        eps = 1e-6
        p = np.clip(p_long, eps, 1.0 - eps)
        logit_p = np.log(p / (1.0 - p))
        logits = self.a * logit_p + self.b
        calibrated = expit(logits)
        return typing.cast(np.ndarray, np.clip(calibrated, 0.001, 0.999))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "type": "BetaCalibrator",
            "a": self.a,
            "b": self.b,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved BetaCalibrator to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        cal = cls()
        cal.a = float(data["a"])
        cal.b = float(data["b"])
        cal.fitted = True
        return cal


class PlattCalibrator(CalibrationMethod):
    """Platt scaling on log-odds — 2-parameter logistic calibration.

    Fits: ``logit(calibrated_p) = a * logit(p) + b``

    This is equivalent to fitting a logistic regression on the log-odds
    of the raw predictions. It is the recommended default for compressed
    probability distributions because:

    - Only 2 parameters (a, b) — robust to severe compression
    - Operates on log-odds, the native space of XGBoost's binary:logistic
    - Monotonic — preserves rank ordering of predictions
    - Extrapolates reasonably outside the training range

    Uses sklearn's LogisticRegression with C=1e6 (essentially no
    regularization) on ``logit(p_long)`` as the single feature.

    Reference: Platt (1999), "Probabilistic Outputs for Support Vector
    Machines and Comparisons to Regularized Likelihood Methods."
    """

    def __init__(self):
        self.a: float = 1.0
        self.b: float = 0.0
        self.fitted = False
        self._model: LogisticRegression | None = None

    def fit(self, p_long: np.ndarray, outcomes: np.ndarray) -> Self:
        p_long = np.asarray(p_long, dtype=float).ravel()
        outcomes = np.asarray(outcomes, dtype=int).ravel()

        eps = 1e-6
        p = np.clip(p_long, eps, 1.0 - eps)
        logit_p = np.log(p / (1.0 - p))

        X = logit_p.reshape(-1, 1)
        self._model = LogisticRegression(C=1e6, solver="lbfgs", random_state=42)
        self._model.fit(X, outcomes)
        self.a = float(self._model.coef_[0, 0])
        self.b = float(self._model.intercept_[0])
        self.fitted = True
        return self

    def calibrate(self, p_long: np.ndarray) -> np.ndarray:
        if not self.fitted or self._model is None:
            logger.warning("PlattCalibrator not fitted — returning raw probabilities")
            return np.asarray(p_long, dtype=float)

        p_long = np.asarray(p_long, dtype=float).ravel()
        eps = 1e-6
        p = np.clip(p_long, eps, 1.0 - eps)
        logit_p = np.log(p / (1.0 - p))
        X = logit_p.reshape(-1, 1)
        calibrated = self._model.predict_proba(X)[:, 1]
        return typing.cast(np.ndarray, np.clip(calibrated, 0.001, 0.999))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "type": "PlattCalibrator",
            "a": self.a,
            "b": self.b,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved PlattCalibrator to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        cal = cls()
        cal.a = float(data["a"])
        cal.b = float(data["b"])
        cal.fitted = True
        # Reconstruct the sklearn model from saved params
        cal._model = LogisticRegression(C=1e6, solver="lbfgs", random_state=42)
        cal._model.coef_ = np.array([[cal.a]])
        cal._model.intercept_ = np.array([cal.b])
        cal._model.classes_ = np.array([0, 1])
        return cal


class DirectionalCalibrator(CalibrationMethod):
    """Direction-conditional probability calibrator.

    Trains separate calibrator instances on BUY-prediction and
    SELL-prediction subsets of the training data.  At inference time,
    applies the direction-appropriate calibrator based on the raw
    prediction.

    The base calibrator type can be selected via ``base_calibrator``:
    - ``"binned"`` (default): uses BinnedCalibrator for each side
    - ``"platt"``: uses PlattCalibrator (recommended for compressed distributions)

    This directly addresses the finding that "wrong BUY is more confident
    than correct BUY" (GBPJPY, USDJPY, NZDUSD) — by fitting the
    calibrator only on BUY predictions, it learns the true
    P(UP | model says BUY) without contamination from SELL predictions
    that happen to produce high p_long.

    The SELL-side calibrator flips perspective: it calibrates
    P(DOWN | model says SELL) using ``1 - p_long`` as the input and
    ``1 - outcome`` as the target.  At inference, the calibrated sell
    probability is ``1 - calibrator_sell(1 - p_long)``.

    Reference: The original BUY/SELL Information Audit (2026-06-25)
    found ECE(buy) ≈ 0.288 vs ECE(sell) ≈ 0.051 across 6 assets —
    the 5.6x gap is the primary failure mode this calibrator targets.
    """

    BASE_CALIBRATORS = {
        "binned": BinnedCalibrator,
        "platt": PlattCalibrator,
    }

    def __init__(self, n_bins: int = 10, min_samples_per_bin: int = 5, base_calibrator: str = "binned"):
        self.n_bins = n_bins
        self.min_samples_per_bin = min_samples_per_bin
        self.base_calibrator_type = base_calibrator
        CalibratorCls = self.BASE_CALIBRATORS.get(base_calibrator, BinnedCalibrator)
        if base_calibrator == "binned":
            self.buy_calibrator = CalibratorCls(n_bins=n_bins, min_samples_per_bin=min_samples_per_bin)
            self.sell_calibrator = CalibratorCls(n_bins=n_bins, min_samples_per_bin=min_samples_per_bin)
        else:
            self.buy_calibrator = CalibratorCls()
            self.sell_calibrator = CalibratorCls()
        self._buy_fitted = False
        self._sell_fitted = False
        self.fitted = False

    def fit(self, p_long: np.ndarray, outcomes: np.ndarray, predictions: np.ndarray | None = None) -> Self:
        """Fit direction-conditional calibrators.

        Parameters
        ----------
        p_long : np.ndarray
            Raw model probabilities (P(class=1)).
        outcomes : np.ndarray
            Actual outcomes (0 or 1).  1 = TP / up-move, 0 = SL / down-move.
        predictions : np.ndarray | None
            Model's directional signal (-1 = SELL, 0 = FLAT, 1 = BUY).
            If None, inferred from p_long: p_long > 0.5 → BUY, else SELL.
        """
        p_long = np.asarray(p_long, dtype=float)
        outcomes = np.asarray(outcomes, dtype=int)

        if predictions is not None:
            predictions = np.asarray(predictions, dtype=int)
            buy_mask = predictions == 1
            sell_mask = predictions == -1
        else:
            buy_mask = p_long > 0.5
            sell_mask = p_long < 0.5

        # ── Fit BUY calibrator on BUY-prediction subset ─────────────
        buy_idx = np.where(buy_mask)[0]
        if len(buy_idx) >= self.min_samples_per_bin * 3:
            self.buy_calibrator.fit(p_long[buy_idx], outcomes[buy_idx])
            self._buy_fitted = True
        else:
            logger.warning(
                "DirectionalCalibrator: too few BUY predictions (%d) to fit — skip BUY side",
                len(buy_idx),
            )

        # ── Fit SELL calibrator on SELL-prediction subset ────────────
        # Flip perspective: calibrate P(DOWN | model says SELL)
        # using 1 - p_long as input and 1 - outcome as target.
        sell_idx = np.where(sell_mask)[0]
        if len(sell_idx) >= self.min_samples_per_bin * 3:
            sell_p = 1.0 - p_long[sell_idx]  # P(DOWN) raw estimate
            sell_outcome = 1 - outcomes[sell_idx]  # 1 if SELL was correct
            self.sell_calibrator.fit(sell_p, sell_outcome)
            self._sell_fitted = True
        else:
            logger.warning(
                "DirectionalCalibrator: too few SELL predictions (%d) to fit — skip SELL side",
                len(sell_idx),
            )

        self.fitted = self._buy_fitted or self._sell_fitted
        return self

    def calibrate(self, p_long: np.ndarray) -> np.ndarray:
        """Apply direction-conditional calibration.

        For each prediction, applies the BUY calibrator when p_long > 0.5
        and the SELL calibrator (inverse perspective) when p_long < 0.5.
        Predictions at exactly 0.5 pass through unchanged.

        If a direction's calibrator was not fitted (insufficient data),
        falls back to returning the raw p_long for that subset.
        """
        if not self.fitted:
            logger.warning("DirectionalCalibrator not fitted — returning raw probabilities")
            return np.asarray(p_long, dtype=float)

        p_long = np.asarray(p_long, dtype=float).ravel()
        result = p_long.copy()

        buy_mask = p_long > 0.5
        sell_mask = p_long < 0.5

        # Apply BUY calibrator
        if self._buy_fitted and buy_mask.any():
            result[buy_mask] = self.buy_calibrator.calibrate(p_long[buy_mask])

        # Apply SELL calibrator (inverse perspective)
        if self._sell_fitted and sell_mask.any():
            sell_p = 1.0 - p_long[sell_mask]  # P(DOWN) input
            cal_sell_p = self.sell_calibrator.calibrate(sell_p)
            result[sell_mask] = 1.0 - cal_sell_p  # Convert back to P(UP)

        # Neutral predictions (p_long == 0.5) pass through unchanged

        return typing.cast(np.ndarray, np.clip(result, 0.001, 0.999))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Delegate serialization to sub-calibrators
        buy_data: dict | None = None
        if self._buy_fitted:
            buy_data = {
                "type": type(self.buy_calibrator).__name__,
                "a": getattr(self.buy_calibrator, "a", None),
                "b": getattr(self.buy_calibrator, "b", None),
                "bin_centers": (
                    self.buy_calibrator.bin_centers.tolist()
                    if hasattr(self.buy_calibrator, "bin_centers") and self.buy_calibrator.bin_centers is not None
                    else None
                ),
                "bin_empirical_probs": (
                    self.buy_calibrator.bin_empirical_probs.tolist()
                    if hasattr(self.buy_calibrator, "bin_empirical_probs")
                    and self.buy_calibrator.bin_empirical_probs is not None
                    else None
                ),
            }

        sell_data: dict | None = None
        if self._sell_fitted:
            sell_data = {
                "type": type(self.sell_calibrator).__name__,
                "a": getattr(self.sell_calibrator, "a", None),
                "b": getattr(self.sell_calibrator, "b", None),
                "bin_centers": (
                    self.sell_calibrator.bin_centers.tolist()
                    if hasattr(self.sell_calibrator, "bin_centers") and self.sell_calibrator.bin_centers is not None
                    else None
                ),
                "bin_empirical_probs": (
                    self.sell_calibrator.bin_empirical_probs.tolist()
                    if hasattr(self.sell_calibrator, "bin_empirical_probs")
                    and self.sell_calibrator.bin_empirical_probs is not None
                    else None
                ),
            }

        data = {
            "type": "DirectionalCalibrator",
            "base_calibrator_type": self.base_calibrator_type,
            "n_bins": self.n_bins,
            "min_samples_per_bin": self.min_samples_per_bin,
            "buy_fitted": self._buy_fitted,
            "sell_fitted": self._sell_fitted,
            "buy_calibrator": buy_data,
            "sell_calibrator": sell_data,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        logger.info("Saved DirectionalCalibrator to %s", path)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        n_bins = int(data["n_bins"])
        min_samples = int(data.get("min_samples_per_bin", 5))
        base_cal = data.get("base_calibrator_type", "binned")
        cal = cls(n_bins=n_bins, min_samples_per_bin=min_samples, base_calibrator=base_cal)

        # Restore BUY calibrator
        buy_raw = data.get("buy_calibrator")
        if buy_raw is not None:
            cal._buy_fitted = data.get("buy_fitted", False)
            buy_type = buy_raw.get("type", "BinnedCalibrator")
            if buy_type == "PlattCalibrator":
                cal.buy_calibrator.a = float(buy_raw.get("a", 1.0))
                cal.buy_calibrator.b = float(buy_raw.get("b", 0.0))
                cal.buy_calibrator.fitted = cal._buy_fitted
                if cal._buy_fitted:
                    from sklearn.linear_model import LogisticRegression

                    cal.buy_calibrator._model = LogisticRegression(C=1e6, solver="lbfgs", random_state=42)
                    cal.buy_calibrator._model.coef_ = np.array([[cal.buy_calibrator.a]])
                    cal.buy_calibrator._model.intercept_ = np.array([cal.buy_calibrator.b])
                    cal.buy_calibrator._model.classes_ = np.array([0, 1])
            elif buy_raw.get("bin_centers"):
                cal.buy_calibrator.bin_centers = np.array(buy_raw["bin_centers"], dtype=float)
                if buy_raw.get("bin_empirical_probs"):
                    cal.buy_calibrator.bin_empirical_probs = np.array(buy_raw["bin_empirical_probs"], dtype=float)
                cal.buy_calibrator.fitted = cal._buy_fitted

        # Restore SELL calibrator
        sell_raw = data.get("sell_calibrator")
        if sell_raw is not None:
            cal._sell_fitted = data.get("sell_fitted", False)
            sell_type = sell_raw.get("type", "BinnedCalibrator")
            if sell_type == "PlattCalibrator":
                cal.sell_calibrator.a = float(sell_raw.get("a", 1.0))
                cal.sell_calibrator.b = float(sell_raw.get("b", 0.0))
                cal.sell_calibrator.fitted = cal._sell_fitted
                if cal._sell_fitted:
                    from sklearn.linear_model import LogisticRegression

                    cal.sell_calibrator._model = LogisticRegression(C=1e6, solver="lbfgs", random_state=42)
                    cal.sell_calibrator._model.coef_ = np.array([[cal.sell_calibrator.a]])
                    cal.sell_calibrator._model.intercept_ = np.array([cal.sell_calibrator.b])
                    cal.sell_calibrator._model.classes_ = np.array([0, 1])
            elif sell_raw.get("bin_centers"):
                cal.sell_calibrator.bin_centers = np.array(sell_raw["bin_centers"], dtype=float)
                if sell_raw.get("bin_empirical_probs"):
                    cal.sell_calibrator.bin_empirical_probs = np.array(sell_raw["bin_empirical_probs"], dtype=float)
                cal.sell_calibrator.fitted = cal._sell_fitted

        cal.fitted = cal._buy_fitted or cal._sell_fitted
        return cal
