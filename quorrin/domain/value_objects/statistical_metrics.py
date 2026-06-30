from __future__ import annotations

import numpy as np
from scipy.stats import norm


def sharpe_ratio(
    returns: np.ndarray,
    rf: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    excess = returns - rf
    std = np.std(excess, ddof=1)
    if std < 1e-12:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods_per_year))


def _moments(returns: np.ndarray) -> tuple[float, float]:
    n = len(returns)
    if n < 3:
        return 0.0, 0.0
    std = np.std(returns, ddof=1)
    if std < 1e-12:
        return 0.0, 0.0
    demeaned = returns - np.mean(returns)
    m3 = np.mean(demeaned**3)
    skew = m3 / (std**3)
    if n > 2:
        skew = skew * np.sqrt(n * (n - 1)) / (n - 2)
    m4 = np.mean(demeaned**4)
    kurt = m4 / (std**4)
    excess_kurt = kurt - 3.0
    return float(skew), float(excess_kurt)


def _sharpe_variance(sharpe: float, skew: float, excess_kurt: float, n_obs: int) -> float:
    if n_obs < 2:
        return 1.0
    var_est = (1.0 + excess_kurt * sharpe**2 / 4.0 - skew * sharpe) / (n_obs - 1)
    if var_est <= 0:
        var_est = 1.0 / (n_obs - 1)
    return var_est


def probabilistic_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    excess_kurt: float = 0.0,
    benchmark: float = 0.0,
) -> float:
    if n_obs < 2 or not np.isfinite(sharpe):
        return 0.5
    var_sharpe = _sharpe_variance(sharpe, skew, excess_kurt, n_obs)
    if var_sharpe <= 0:
        return 0.5
    z = (sharpe - benchmark) / np.sqrt(var_sharpe)
    return float(norm.cdf(z))


def expected_max_sharpe(num_trials: int) -> float:
    if num_trials <= 1:
        return 0.0
    gamma_euler = 0.5772156649
    inv_n = 1.0 / num_trials
    term1 = (1.0 - gamma_euler) * norm.ppf(1.0 - inv_n)
    term2 = gamma_euler * norm.ppf(1.0 - inv_n / np.e)
    return float(term1 + term2)


def deflated_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    excess_kurt: float = 0.0,
    num_trials: int = 1,
) -> float:
    if n_obs < 2 or not np.isfinite(sharpe) or num_trials <= 1:
        return probabilistic_sharpe_ratio(sharpe, n_obs, skew, excess_kurt, 0.0)
    var_sharpe = _sharpe_variance(sharpe, skew, excess_kurt, n_obs)
    if var_sharpe <= 0:
        return 0.5
    std_sharpe = np.sqrt(var_sharpe)
    e_max = expected_max_sharpe(num_trials)
    benchmark_deflated = std_sharpe * e_max
    return probabilistic_sharpe_ratio(sharpe, n_obs, skew, excess_kurt, benchmark_deflated)


def minimum_track_record_length(
    sharpe: float,
    skew: float = 0.0,
    excess_kurt: float = 0.0,
    alpha: float = 0.05,
) -> int:
    if not np.isfinite(sharpe) or abs(sharpe) < 1e-6:
        return 10**6
    z_alpha = norm.ppf(1.0 - alpha)
    var_coef = 1.0 + excess_kurt * sharpe**2 / 4.0 - skew * sharpe
    if var_coef <= 0:
        return 2
    n_min = 1.0 + var_coef * (z_alpha / sharpe) ** 2
    return max(2, int(np.ceil(n_min)))


def expected_calibration_error(
    probs: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> float:
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


def confidence_reliability_score(
    probs: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
) -> float:
    return 1.0 - expected_calibration_error(probs, outcomes, n_bins)


def herfindahl_index(returns: np.ndarray) -> float:
    returns = np.asarray(returns, dtype=float)
    total_abs = np.sum(np.abs(returns))
    if total_abs < 1e-12:
        return 0.0
    weights = returns / total_abs
    return float(np.sum(weights**2))
