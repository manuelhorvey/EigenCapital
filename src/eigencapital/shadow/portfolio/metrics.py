"""Portfolio metrics shared by the frozen R4 baseline and shadow portfolios.

Every metric here is computed identically for both portfolios so the
comparison in each shadow decision is apples-to-apples.

Risk model:
    portfolio_variance = w' Σ w,  Σ_ij = corr_ij · σ_i · σ_j
    with w = signed R4 signal weights, σ = annualized vol of the candidate.
    This is the same weight space the frozen R4 signal uses (±0.20 clips),
    so metrics are comparable across baseline and shadow without inventing
    account-level quantities (no equity, no lot sizing here).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import numpy as np
import pandas as pd

EXPECTED_DRAWDOWN_SIGMA = 2.0  # documented 2σ annual drawdown proxy (experimental)


@dataclass
class PortfolioMetrics:
    """Risk / edge / exposure metrics for one portfolio construction."""

    # Edge (R4 signal weight space)
    gross_edge: float  # Σ|w|
    net_edge: float  # Σw
    long_count: int
    short_count: int

    # Risk
    portfolio_vol_annual: float  # sqrt(w'Σw) annualized (weight space)
    avg_pairwise_corr: float
    max_abs_pairwise_corr: float
    herfindahl: float  # on |w| normalized to sum 1
    effective_positions: float  # 1/HHI
    diversification_ratio: float  # Σ|w|σ / portfolio_vol
    expected_drawdown_proxy: float  # 2σ portfolio vol (documented proxy)
    max_corr_cluster_share: float  # largest high-corr cluster share of gross

    # Risk concentration (marginal contribution to portfolio variance)
    risk_contribution_hhi: float = 0.0  # HHI over per-asset variance shares
    max_risk_contribution_share: float = 0.0  # largest single-asset variance share
    effective_risk_contributors: float = 0.0  # 1/HHI over variance shares

    # Exposure (from ExposureModel)
    exposure: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gross_edge": round(self.gross_edge, 6),
            "net_edge": round(self.net_edge, 6),
            "long_count": self.long_count,
            "short_count": self.short_count,
            "portfolio_vol_annual": round(self.portfolio_vol_annual, 6),
            "avg_pairwise_corr": round(self.avg_pairwise_corr, 6),
            "max_abs_pairwise_corr": round(self.max_abs_pairwise_corr, 6),
            "herfindahl": round(self.herfindahl, 6),
            "effective_positions": round(self.effective_positions, 4),
            "diversification_ratio": round(self.diversification_ratio, 4),
            "expected_drawdown_proxy": round(self.expected_drawdown_proxy, 6),
            "max_corr_cluster_share": round(self.max_corr_cluster_share, 6),
            "risk_contribution_hhi": round(self.risk_contribution_hhi, 6),
            "max_risk_contribution_share": round(self.max_risk_contribution_share, 6),
            "effective_risk_contributors": round(self.effective_risk_contributors, 4),
            "exposure": self.exposure,
        }


def _pairwise_corr_stats(corr: pd.DataFrame) -> tuple[float, float]:
    n = corr.shape[0]
    if n < 2:
        return 0.0, 0.0
    values = corr.values
    mask = ~np.eye(n, dtype=bool) & ~np.isnan(values)
    if not mask.any():
        return 0.0, 0.0
    off = values[mask]
    return float(np.mean(off)), float(np.max(np.abs(off)))


def _max_corr_cluster_share(weights: Dict[str, float], corr: pd.DataFrame, threshold: float = 0.7) -> float:
    """Union-find clusters on |corr| >= threshold; report largest cluster's
    share of gross |weight|. Identical-return series land in one cluster."""
    symbols = [s for s in weights if s in corr.index]
    if len(symbols) < 2:
        return 1.0 if len(symbols) == 1 else 0.0
    parent = {s: s for s in symbols}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            a, b = symbols[i], symbols[j]
            c = corr.loc[a, b]
            if not np.isnan(c) and abs(c) >= threshold:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra

    clusters: Dict[str, float] = {}
    for s in symbols:
        clusters[find(s)] = clusters.get(find(s), 0.0) + abs(weights[s])
    gross = sum(abs(weights[s]) for s in symbols)
    if gross <= 0:
        return 0.0
    return max(clusters.values()) / gross


def compute_portfolio_metrics(
    weights: Dict[str, float],
    vol: Dict[str, float],
    corr: pd.DataFrame,
    exposure_summary: Dict[str, Any],
) -> PortfolioMetrics:
    """Compute the full metric set for one portfolio.

    Args:
        weights: symbol → signed weight (R4 signal weight space).
        vol: symbol → annualized volatility (from correlation snapshot).
        corr: primary correlation matrix (may contain extra columns).
        exposure_summary: output of ExposureModel.concentration_summary.
    """
    symbols = [s for s in weights if weights[s] != 0.0]
    gross = sum(abs(w) for w in weights.values())
    net = sum(weights.values())
    long_count = sum(1 for w in weights.values() if w > 0)
    short_count = sum(1 for w in weights.values() if w < 0)

    # Portfolio variance via w'Σw
    present = [s for s in symbols if s in corr.index and s in vol]
    if present:
        sub = corr.loc[present, present].fillna(0.0)
        w_vec = np.array([weights[s] for s in present], dtype=float)
        v_vec = np.array([vol[s] for s in present], dtype=float)
        sigma = sub.values * np.outer(v_vec, v_vec)
        var = float(w_vec @ sigma @ w_vec)
        portfolio_vol = np.sqrt(max(var, 0.0))
    else:
        portfolio_vol = 0.0

    # Pairwise correlation stats over the restricted matrix
    avg_corr, max_corr = _pairwise_corr_stats(corr.reindex(index=present, columns=present)) if present else (0.0, 0.0)

    # HHI on normalized |w|
    if gross > 0:
        norm = np.array([abs(weights[s]) / gross for s in symbols])
        hhi = float(norm @ norm)
        eff_pos = 1.0 / hhi if hhi > 0 else 0.0
    else:
        hhi, eff_pos = 0.0, 0.0

    # Diversification ratio: Σ|w_i|σ_i / σ_p
    weighted_vol = sum(abs(weights[s]) * vol.get(s, 0.0) for s in symbols)
    div_ratio = weighted_vol / portfolio_vol if portfolio_vol > 0 else (1.0 if len(symbols) == 1 else 0.0)

    # Marginal risk contribution: share of portfolio variance attributable to
    # each asset. c_i = w_i · (Σw)_i and Σ_i c_i = w'Σw = variance, so the
    # normalized shares sum to 1. Concentration (HHI / max share) answers
    # "how many independent risk bets is this portfolio really making?" — the
    # weight-space HHI above counts positions, but correlated positions share
    # risk, so risk-contribution concentration is the tighter diagnostic.
    rc_hhi, rc_max, rc_eff = 0.0, 0.0, 0.0
    if present and portfolio_vol > 1e-12:
        contrib = w_vec * (sigma @ w_vec)
        total = float(contrib.sum())
        if total > 1e-12:
            shares = contrib / total
            shares = np.clip(shares, 0.0, None)  # PSD Σ keeps these non-negative
            rc_hhi = float(shares @ shares)
            rc_max = float(shares.max())
            rc_eff = 1.0 / rc_hhi if rc_hhi > 0 else 0.0

    return PortfolioMetrics(
        gross_edge=gross,
        net_edge=net,
        long_count=long_count,
        short_count=short_count,
        portfolio_vol_annual=portfolio_vol,
        avg_pairwise_corr=avg_corr,
        max_abs_pairwise_corr=max_corr,
        herfindahl=hhi,
        effective_positions=eff_pos,
        diversification_ratio=div_ratio,
        expected_drawdown_proxy=EXPECTED_DRAWDOWN_SIGMA * portfolio_vol,
        max_corr_cluster_share=_max_corr_cluster_share(weights, corr),
        risk_contribution_hhi=rc_hhi,
        max_risk_contribution_share=rc_max,
        effective_risk_contributors=rc_eff,
        exposure=exposure_summary,
    )
