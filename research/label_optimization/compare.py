"""Significance testing and behavioral distance between experiments."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.stats import ttest_rel, wilcoxon, t as t_dist, bootstrap


# Metrics where lower is better (inverted direction check)
_LOWER_IS_BETTER = {"ece", "ece_mean", "brier", "brier_mean", "cal_inversion_rate",
                     "cal_inversion_rate_mean", "max_drawdown_pct", "max_drawdown_mean",
                     "imbalance_ratio", "flat_rate",
                     "reliability", "log_loss"}


def paired_comparison(
    baseline_folds: list[dict[str, Any]],
    config_folds: list[dict[str, Any]],
    metric: str = "sharpe",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Compare two experiments across folds using paired tests.

    Args:
        baseline_folds: Fold results for the baseline (production) config.
        config_folds: Fold results for the experiment config.
        metric: Metric name to compare (e.g. 'sharpe', 'ece', 'profit_factor').
        alpha: Significance level.

    Returns:
        Dict with test statistics and interpretation.
    """
    b_vals = np.array([float(f[metric]) for f in baseline_folds if f.get(metric) is not None])
    c_vals = np.array([float(f[metric]) for f in config_folds if f.get(metric) is not None])

    if len(b_vals) < 2 or len(c_vals) < 2 or len(b_vals) != len(c_vals):
        return {
            "metric": metric,
            "n_folds": min(len(b_vals), len(c_vals)),
            "error": "Insufficient paired fold data for comparison",
        }

    diffs = c_vals - b_vals
    n = len(diffs)

    # Paired t-test
    t_stat, t_p = ttest_rel(c_vals, b_vals)
    t_p = float(t_p)

    # Wilcoxon signed-rank (non-parametric)
    try:
        w_stat, w_p = wilcoxon(diffs, alternative="two-sided")
        w_p = float(w_p)
    except ValueError:
        w_stat, w_p = 0.0, 1.0

    # Bootstrap 95% CI for the difference
    try:
        boot = bootstrap(
            (diffs,),
            np.mean,
            n_resamples=9999,
            confidence_level=1 - alpha,
            method="BCa",
            random_state=42,
        )
        ci_low, ci_high = float(boot.confidence_interval.low), float(boot.confidence_interval.high)
    except Exception:
        ci_low, ci_high = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))

    # Cohen's d (effect size)
    pooled_std = np.sqrt((np.std(b_vals, ddof=1) ** 2 + np.std(c_vals, ddof=1) ** 2) / 2)
    cohens_d = float(diffs.mean() / max(pooled_std, 1e-10))

    # Direction-aware interpretation
    lower_better = metric in _LOWER_IS_BETTER
    diff_direction = diffs.mean()
    # A positive diff means config > baseline. For "lower is better" metrics,
    # a positive diff is degradation; for "higher is better", it's improvement.
    if lower_better:
        direction = "improvement" if diff_direction < 0 else "degradation"
    else:
        direction = "improvement" if diff_direction > 0 else "degradation"

    significant = t_p < alpha
    if significant:
        verdict = f"Significant {direction} (t-test p={t_p:.4f}, d={cohens_d:.3f})"
    else:
        verdict = f"No significant difference (t-test p={t_p:.4f}, d={cohens_d:.3f})"

    return {
        "metric": metric,
        "n_folds": n,
        "baseline_mean": float(b_vals.mean()),
        "config_mean": float(c_vals.mean()),
        "diff_mean": float(diffs.mean()),
        "diff_std": float(diffs.std(ddof=1)),
        "ci_95_low": round(ci_low, 6),
        "ci_95_high": round(ci_high, 6),
        "t_statistic": round(float(t_stat), 4),
        "t_p_value": round(t_p, 4),
        "wilcoxon_statistic": round(float(w_stat), 2),
        "wilcoxon_p_value": round(w_p, 4),
        "cohens_d": round(cohens_d, 4),
        "significant": significant,
        "direction": direction,
        "verdict": verdict,
    }


def compare_experiments(
    baseline_id: str,
    experiment_ids: list[str],
    metrics: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Compare multiple experiments against a common baseline.

    Args:
        baseline_id: Experiment ID of the baseline (production config).
        experiment_ids: Experiment IDs to compare.
        metrics: Metric names to compare (default: ['sharpe', 'ece', 'cal_inversion_rate']).

    Returns:
        List of comparison results.
    """
    if metrics is None:
        metrics = ["sharpe", "ece", "cal_inversion_rate"]

    import sqlite3
    from pathlib import Path
    from research.label_optimization.schema import EXPERIMENT_DB

    conn = sqlite3.connect(str(EXPERIMENT_DB))
    conn.row_factory = sqlite3.Row

    def _get_folds(eid: str) -> list[dict]:
        rows = conn.execute(
            "SELECT * FROM fold_results WHERE experiment_id = ? ORDER BY fold",
            (eid,)
        ).fetchall()
        return [dict(r) for r in rows]

    baseline_folds = _get_folds(baseline_id)
    if not baseline_folds:
        conn.close()
        return [{"error": f"No fold results for baseline {baseline_id}"}]

    results = []
    for eid in experiment_ids:
        config_folds = _get_folds(eid)
        if not config_folds:
            results.append({"experiment_id": eid, "error": "No fold results"})
            continue
        for metric in metrics:
            comp = paired_comparison(baseline_folds, config_folds, metric=metric)
            comp["baseline_id"] = baseline_id
            comp["experiment_id"] = eid
            results.append(comp)

    conn.close()
    return results


def behavioral_distance(
    baseline_probs: np.ndarray,
    config_probs: np.ndarray,
    n_bins: int = 20,
) -> dict[str, float]:
    """Distributional distance between two probability output sets.

    Args:
        baseline_probs: Prediction probabilities from the baseline model.
        config_probs: Prediction probabilities from the experiment model.
        n_bins: Number of bins for histogram-based divergences.

    Returns:
        Dict with Jensen-Shannon divergence, KL divergence,
        mean absolute probability shift, and direction flip rate.
    """
    from scipy.stats import entropy as kl_div
    from scipy.spatial.distance import jensenshannon

    # Align lengths
    n = min(len(baseline_probs), len(config_probs))
    bp = baseline_probs[:n]
    cp = config_probs[:n]

    # Mean absolute probability shift
    mean_abs_shift = float(np.mean(np.abs(cp - bp)))

    # Direction flip rate
    b_dir = (bp >= 0.5).astype(float)
    c_dir = (cp >= 0.5).astype(float)
    flip_rate = float((b_dir != c_dir).mean())

    # Confidence shift (magnitude of change when direction agrees)
    same_dir = b_dir == c_dir
    if same_dir.any():
        conf_shift = float(np.mean(np.abs(cp[same_dir] - bp[same_dir])))
    else:
        conf_shift = 0.0

    # Jensen-Shannon divergence (histogram-based)
    bins = np.linspace(0, 1, n_bins + 1)
    b_hist, _ = np.histogram(bp, bins=bins, density=True)
    c_hist, _ = np.histogram(cp, bins=bins, density=True)
    b_hist = b_hist + 1e-12  # avoid log(0)
    c_hist = c_hist + 1e-12
    js_div = float(jensenshannon(b_hist, c_hist, base=2))

    # KL divergence
    kl = float(kl_div(b_hist, c_hist))

    return {
        "jensen_shannon_div": round(js_div, 6),
        "kl_divergence": round(kl, 6),
        "mean_prob_shift": round(mean_abs_shift, 6),
        "direction_flip_rate": round(flip_rate, 6),
        "confidence_shift_same_dir": round(conf_shift, 6),
    }
