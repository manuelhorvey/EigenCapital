"""Correlation model for the R4-S shadow portfolio constructor.

Builds pairwise correlation estimates from ACTUAL historical daily returns.
No instrument-name assumptions: correlation is an estimated, dynamic risk
relationship, never a static property of an instrument pair.

NO-LOOKAHEAD CONTRACT:
    `CorrelationModel.build(returns, as_of)` hard-truncates the input frame
    to rows with index <= `as_of` before computing anything. It is
    structurally impossible for future rows to influence the estimate.
    `CorrelationSnapshot.as_of` records the truncation timestamp for audit.

STABILITY DIAGNOSIS:
    Instability is exposed, not hidden: `CorrelationSnapshot.stability`
    reports cross-window agreement (mean pairwise |Δcorr| across the
    configured lookback windows). High instability surfaces as a first-class
    field in every shadow decision record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# Canonical FX-liquid lookbacks (daily bars). Research-driven defaults, not
# magic numbers: 20 ≈ one trading month (fast), 60 ≈ one quarter (baseline),
# 120 ≈ half year (slow). Configurable for sensitivity analysis.
DEFAULT_LOOKBACKS: Tuple[int, ...] = (20, 60, 120)

# Minimum overlapping observations for a trustworthy pairwise correlation.
MIN_PAIRWISE_OBS = 30


@dataclass(frozen=True)
class CorrelationModelConfig:
    """Configuration for the shadow correlation model.

    Isolated from frozen R4 configuration: these values live only in the
    shadow package and cannot influence production behavior.
    """

    lookbacks: Tuple[int, ...] = DEFAULT_LOOKBACKS
    primary_lookback: int = 60
    min_pairwise_obs: int = MIN_PAIRWISE_OBS
    min_rolling_obs: int = 10  # floor for short windows
    # Shrinkage toward the identity (Ledoit-Wolf-style diagonal shrinkage).
    # Stabilizes eigen-structure for small candidate sets; documented as
    # experimental (Section 8 of the R4-S research brief).
    shrinkage: float = 0.1

    def __post_init__(self) -> None:
        if self.primary_lookback not in self.lookbacks:
            raise ValueError(f"primary_lookback {self.primary_lookback} must be one of lookbacks {self.lookbacks}")
        if not 0.0 <= self.shrinkage < 1.0:
            raise ValueError(f"shrinkage must be in [0, 1), got {self.shrinkage}")
        if any(lb < 2 for lb in self.lookbacks):
            raise ValueError("all lookbacks must be >= 2")


@dataclass
class CorrelationSnapshot:
    """Point-in-time correlation evidence for one decision cycle."""

    as_of: str
    corr: pd.DataFrame
    primary_lookback: int
    observations_used: int
    pairwise_obs_counts: pd.DataFrame
    avg_pairwise_corr: float
    max_abs_pairwise_corr: float
    cross_window_stability: float  # mean |Δcorr| across lookbacks (lower = stable)
    per_lookback_avg: Dict[int, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "primary_lookback": self.primary_lookback,
            "observations_used": self.observations_used,
            "avg_pairwise_corr": round(self.avg_pairwise_corr, 6),
            "max_abs_pairwise_corr": round(self.max_abs_pairwise_corr, 6),
            "cross_window_stability": round(self.cross_window_stability, 6),
            "per_lookback_avg": {str(k): round(v, 6) for k, v in self.per_lookback_avg.items()},
            "min_pairwise_obs": int(self.pairwise_obs_counts.values.min()) if self.pairwise_obs_counts.size else 0,
            "symbols": list(self.corr.columns),
        }


class CorrelationModel:
    """Rolling, recency-aware correlation estimator over actual daily returns."""

    def __init__(self, config: CorrelationModelConfig | None = None) -> None:
        self.config = config or CorrelationModelConfig()

    # ── No-lookahead truncation ──────────────────────────────────────
    @staticmethod
    def _truncate(returns: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
        """Return only rows with index <= as_of. Hard no-lookahead boundary.

        Mixed tz-awareness is normalized before comparison: pandas raises
        `Invalid comparison between dtype=datetime64[ns] and Timestamp` when
        one side is tz-naive and the other tz-aware (R4-S 2026-09-08: live
        MT5 bar indexes are tz-naive server time while callers pass
        `pd.Timestamp(datetime.now(UTC))`). A tz-aware `as_of` is stripped
        to wall-clock so the boundary stays in bar-index terms — never
        re-localize the index, which would shift the truncation point.
        """
        idx = returns.index
        if isinstance(idx, pd.DatetimeIndex):
            if as_of.tzinfo is not None and idx.tz is None:
                as_of = as_of.tz_localize(None)
            elif as_of.tzinfo is None and idx.tz is not None:
                as_of = as_of.tz_localize(idx.tz)
            mask = idx <= as_of
            return returns.loc[mask]
        # Non-datetime index: caller must have pre-truncated. Refuse to guess.
        raise TypeError("returns index must be a DatetimeIndex for point-in-time truncation")

    def build(self, returns: pd.DataFrame, as_of: pd.Timestamp) -> CorrelationSnapshot | None:
        """Build the correlation snapshot using ONLY data available at `as_of`.

        Returns None when there is insufficient history to say anything
        meaningful (the caller records that as a data gap, not a fallback).
        """
        if not isinstance(returns, pd.DataFrame) or returns.empty:
            return None

        hist = self._truncate(returns, pd.Timestamp(as_of))
        primary_lb = self.config.primary_lookback
        if len(hist) < self.config.min_rolling_obs:
            return None

        effective_lb = min(primary_lb, len(hist))
        window = hist.tail(effective_lb)

        # Pairwise-complete correlations (never forward/backward fill here —
        # filling would fabricate co-movement that never happened).
        corr = window.corr(min_periods=self.config.min_pairwise_obs)

        obs_counts = self._pairwise_obs_counts(window)
        valid = corr.notna()
        if valid.sum().sum() == 0:
            return None

        # Off-diagonal only: the diagonal (1.0) is not a pairwise relationship.
        n = corr.shape[0]
        off_diag = ~np.eye(n, dtype=bool) & valid.values
        vals = corr.values[off_diag]
        avg_corr = float(np.mean(vals)) if vals.size else 0.0
        max_abs = float(np.max(np.abs(vals))) if vals.size else 0.0

        # Cross-window stability: mean |Δcorr| of off-diagonal entries between
        # each secondary window and the primary window.
        per_lb_avg: Dict[int, float] = {primary_lb: avg_corr}
        deltas: List[float] = []
        for lb in self.config.lookbacks:
            if lb == primary_lb:
                continue
            if len(hist) < lb:
                continue
            w2 = hist.tail(lb)
            # min_periods must not exceed the window itself (short windows).
            min_obs = min(self.config.min_pairwise_obs, max(lb // 2, 2))
            c2 = w2.corr(min_periods=min_obs)
            if c2.isna().all().all():
                continue
            n2 = c2.shape[0]
            off2 = ~np.eye(n2, dtype=bool) & c2.notna().values
            vals2 = c2.values[off2]
            per_lb_avg[lb] = float(np.mean(vals2)) if vals2.size else 0.0
            # Align both matrices, compare off-diagonal entries present in both.
            common = corr.index.intersection(c2.index)
            if len(common) >= 2:
                a = corr.loc[common, common].values
                b = c2.loc[common, common].values
                n_c = len(common)
                off_c = ~np.eye(n_c, dtype=bool)
                pair_diffs = np.abs(a - b)[off_c & ~np.isnan(a) & ~np.isnan(b)]
                if pair_diffs.size:
                    deltas.extend(float(d) for d in pair_diffs)

        stability = float(np.mean(deltas)) if deltas else 0.0

        return CorrelationSnapshot(
            as_of=str(pd.Timestamp(as_of).date()),
            corr=corr,
            primary_lookback=primary_lb,
            observations_used=len(window),
            pairwise_obs_counts=obs_counts,
            avg_pairwise_corr=avg_corr,
            max_abs_pairwise_corr=max_abs,
            cross_window_stability=stability,
            per_lookback_avg=per_lb_avg,
        )

    def shrunk_correlation(self, snapshot: CorrelationSnapshot, symbols: List[str]) -> pd.DataFrame:
        """Return the primary correlation matrix restricted to `symbols`,
        with shrinkage toward the identity and NaN→0 (documented, explicit).

        Shrinkage: C_shrunk = (1 - λ)·C + λ·I. This keeps the estimator
        positive-semidefinite for small candidate sets and bounds the
        influence of noisy short-history estimates. λ is experimental and
        recorded in every decision's provenance via the config hash.
        """
        sub = snapshot.corr.reindex(index=symbols, columns=symbols)
        n = len(symbols)
        filled = sub.fillna(0.0).values
        lam = self.config.shrinkage
        shrunk = (1.0 - lam) * filled + lam * np.eye(n)
        return pd.DataFrame(shrunk, index=symbols, columns=symbols)

    @staticmethod
    def _pairwise_obs_counts(window: pd.DataFrame) -> pd.DataFrame:
        cols = list(window.columns)
        counts = pd.DataFrame(np.nan, index=cols, columns=cols)
        valid_mask = window.notna()
        valid_counts = valid_mask.sum()
        for i, ci in enumerate(cols):
            for j, cj in enumerate(cols):
                if i == j:
                    counts.loc[ci, cj] = float(valid_counts[ci])
                else:
                    both = valid_mask[ci] & valid_mask[cj]
                    counts.loc[ci, cj] = float(both.sum())
        return counts
