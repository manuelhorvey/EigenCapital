"""Deflated Sharpe Ratio — selection-bias-aware Sharpe significance.

Implements Bailey & López de Prado (2014), "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting and Non-Normality".

The observed Sharpe ratio of a strategy selected from N trials is
inflated by luck. The DSR deflates it against the expected maximum
Sharpe under N independent trials, then converts to a probability via
the Probabilistic Sharpe Ratio (PSR), which also corrects for skewness
and kurtosis in the return series.

Fail-closed semantics: without at least two trial Sharpes (or an explicit
cross-trial variance) the ratio CANNOT be computed — the result reports
INSUFFICIENT_TRIALS with significant=False rather than assuming away the
selection bias.

Usage:
    result = deflated_sharpe_ratio(
        observed_sharpe=1.8,
        n_trials=45,
        n_periods=1260,
        trial_sharpes=[...all trial sharpes tested on this dataset...],
        skewness=-0.3,
        kurtosis=4.2,
    )
    assert result.significant  # DSR >= confidence AND sufficient trials
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Dict, Any, Optional, Sequence

EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Result of deflated Sharpe ratio computation.

    Attributes:
        observed_sharpe: Observed (per-period) Sharpe ratio
        expected_max_sharpe: SR0 — expected maximum Sharpe across N trials
        deflated_sharpe: Probability that the true Sharpe exceeds SR0,
            corrected for non-normality. In [0, 1].
        significant: True when sufficient_trials and DSR >= confidence
        sufficient_trials: Whether trial evidence allowed deflation
        n_trials: Number of independent strategy variants tested
        n_periods: Number of return observations behind observed_sharpe
        trial_sr_std: Cross-trial standard deviation of Sharpe ratios
        skewness: Sample skewness of returns (0 = symmetric)
        kurtosis: Pearson kurtosis of returns (3 = normal)
        confidence: Significance threshold applied to DSR
        message: Explanation, including fail-closed reasons
    """

    observed_sharpe: float = 0.0
    expected_max_sharpe: float = 0.0
    deflated_sharpe: float = 0.0
    significant: bool = False
    sufficient_trials: bool = False
    n_trials: int = 0
    n_periods: int = 0
    trial_sr_std: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 3.0
    confidence: float = 0.95
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "observed_sharpe": round(self.observed_sharpe, 6),
            "expected_max_sharpe": round(self.expected_max_sharpe, 6),
            "deflated_sharpe": round(self.deflated_sharpe, 6),
            "significant": self.significant,
            "sufficient_trials": self.sufficient_trials,
            "n_trials": self.n_trials,
            "n_periods": self.n_periods,
            "trial_sr_std": round(self.trial_sr_std, 6),
            "skewness": round(self.skewness, 6),
            "kurtosis": round(self.kurtosis, 6),
            "confidence": self.confidence,
            "message": self.message,
        }


def sample_skewness(returns: Sequence[float]) -> float:
    """Sample skewness g1 = m3 / m2^1.5 (0 for symmetric returns).

    Args:
        returns: Period returns

    Returns:
        Skewness; raises ValueError if fewer than 4 observations
    """
    n = len(returns)
    if n < 4:
        raise ValueError("skewness requires at least 4 return observations")
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m3 = sum((r - mean) ** 3 for r in returns) / n
    if m2 <= 0:
        return 0.0
    return m3 / (m2**1.5)


def sample_kurtosis(returns: Sequence[float]) -> float:
    """Pearson kurtosis m4 / m2^2 (3.0 for normal returns).

    Args:
        returns: Period returns

    Returns:
        Kurtosis; raises ValueError if fewer than 4 observations
    """
    n = len(returns)
    if n < 4:
        raise ValueError("kurtosis requires at least 4 return observations")
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    if m2 <= 0:
        return 3.0
    return m4 / (m2**2)


def expected_maximum_sharpe(trial_sharpes: Sequence[float]) -> float:
    """Expected maximum Sharpe ratio SR0 under N independent trials.

    SR0 = std(SR) * [(1 - gamma) * Z^-1(1 - 1/N) + gamma * Z^-1(1 - 1/(N*e))]
    with gamma = Euler-Mascheroni constant (Bailey & López de Prado 2014).

    Args:
        trial_sharpes: Sharpe ratios of ALL variants tested on the dataset

    Returns:
        Expected maximum Sharpe (SR0)

    Raises:
        ValueError: if fewer than 2 trial Sharpes are supplied
    """
    n = len(trial_sharpes)
    if n < 2:
        raise ValueError(
            f"INSUFFICIENT_TRIALS: {n} trial Sharpes < 2 minimum. Deflation "
            f"requires the dispersion of all tested variants; supply every "
            f"Sharpe tried on this dataset or an explicit trial_sr_std."
        )
    mean = sum(trial_sharpes) / n
    variance = sum((s - mean) ** 2 for s in trial_sharpes) / (n - 1)
    std = math.sqrt(variance)
    if std <= 1e-15:
        return 0.0
    normal = NormalDist()
    z1 = normal.inv_cdf(1.0 - 1.0 / n)
    z2 = normal.inv_cdf(1.0 - 1.0 / (n * math.e))
    return std * ((1.0 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def _resolve_trial_sr_std(
    trial_sr_std: Optional[float],
    trial_sharpes: Optional[Sequence[float]],
) -> Optional[float]:
    """Resolve cross-trial Sharpe dispersion from explicit inputs."""
    if trial_sr_std is not None:
        if trial_sr_std < 0:
            raise ValueError("trial_sr_std must be >= 0")
        return trial_sr_std
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        n = len(trial_sharpes)
        mean = sum(trial_sharpes) / n
        variance = sum((s - mean) ** 2 for s in trial_sharpes) / (n - 1)
        return math.sqrt(variance)
    return None


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_periods: int,
    returns: Optional[Sequence[float]] = None,
    trial_sharpes: Optional[Sequence[float]] = None,
    trial_sr_std: Optional[float] = None,
    skewness: Optional[float] = None,
    kurtosis: Optional[float] = None,
    confidence: float = 0.95,
) -> DeflatedSharpeResult:
    """Compute the Deflated Sharpe Ratio.

    Either supply `returns` (moments and period count derived) or supply
    `n_periods`, `skewness`, and `kurtosis` explicitly. Trial dispersion
    comes from `trial_sharpes` or an explicit `trial_sr_std`.

    Args:
        observed_sharpe: Per-period Sharpe ratio of the selected strategy
        n_trials: Number of independent variants tested on the dataset
        n_periods: Observations behind observed_sharpe (ignored if
            `returns` given)
        returns: Return series; derives n_periods/skewness/kurtosis
        trial_sharpes: All trial Sharpes tested on this dataset
        trial_sr_std: Explicit cross-trial Sharpe standard deviation
        skewness: Return skewness (used if `returns` not given)
        kurtosis: Pearson kurtosis (used if `returns` not given)
        confidence: Significance threshold for the DSR probability

    Returns:
        DeflatedSharpeResult; never raises for insufficient evidence —
        reports sufficient_trials=False instead.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")

    resolved_skew = skewness
    resolved_kurt = kurtosis
    resolved_periods = n_periods
    if returns is not None:
        if len(returns) < 4:
            return DeflatedSharpeResult(
                observed_sharpe=observed_sharpe,
                n_trials=n_trials,
                confidence=confidence,
                message=(
                    "INSUFFICIENT_OBSERVATIONS: skew/kurtosis estimation "
                    "requires at least 4 returns."
                ),
            )
        resolved_periods = len(returns)
        resolved_skew = sample_skewness(returns)
        resolved_kurt = sample_kurtosis(returns)

    if resolved_periods < 2 or resolved_skew is None or resolved_kurt is None:
        raise ValueError(
            "Provide either `returns` or all of n_periods, skewness, "
            "kurtosis — assuming normality is not permitted."
        )

    sr_std = _resolve_trial_sr_std(trial_sr_std, trial_sharpes)
    if sr_std is None:
        return DeflatedSharpeResult(
            observed_sharpe=observed_sharpe,
            n_trials=n_trials,
            n_periods=resolved_periods,
            skewness=resolved_skew,
            kurtosis=resolved_kurt,
            confidence=confidence,
            message=(
                "INSUFFICIENT_TRIALS: no cross-trial Sharpe dispersion "
                "available. Record every variant tested on this dataset "
                "(TrialMetadata) so selection bias can be quantified."
            ),
        )

    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        sr0 = expected_maximum_sharpe(list(trial_sharpes))
    elif n_trials >= 2:
        normal = NormalDist()
        sr0 = sr_std * (
            (1.0 - EULER_GAMMA) * normal.inv_cdf(1.0 - 1.0 / n_trials)
            + EULER_GAMMA * normal.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
        )
    else:
        sr0 = 0.0

    moment_term = (
        1.0
        - resolved_skew * observed_sharpe
        + ((resolved_kurt - 1.0) / 4.0) * observed_sharpe**2
    )
    if moment_term <= 1e-12:
        return DeflatedSharpeResult(
            observed_sharpe=observed_sharpe,
            expected_max_sharpe=sr0,
            n_trials=n_trials,
            n_periods=resolved_periods,
            trial_sr_std=sr_std,
            skewness=resolved_skew,
            kurtosis=resolved_kurt,
            confidence=confidence,
            message=(
                "DEGENERATE_MOMENTS: skew/kurtosis combination makes the "
                "PSR denominator undefined at this Sharpe level."
            ),
        )

    psr_statistic = (
        (observed_sharpe - sr0) * math.sqrt(resolved_periods - 1)
    ) / math.sqrt(moment_term)
    dsr = NormalDist().cdf(psr_statistic)

    sufficient = n_trials >= 2
    significant = sufficient and dsr >= confidence

    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        expected_max_sharpe=sr0,
        deflated_sharpe=dsr,
        significant=significant,
        sufficient_trials=sufficient,
        n_trials=n_trials,
        n_periods=resolved_periods,
        trial_sr_std=sr_std,
        skewness=resolved_skew,
        kurtosis=resolved_kurt,
        confidence=confidence,
        message=(
            f"DSR = {dsr:.4f} vs confidence {confidence:.2f} "
            f"(SR0 = {sr0:.4f}, observed = {observed_sharpe:.4f}, "
            f"N = {n_trials})."
            + ("" if significant else " Not significant after deflation.")
        ),
    )
