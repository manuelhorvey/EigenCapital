"""Incremental Alpha Testing — evaluates whether new strategies improve existing portfolio.

Every new candidate is evaluated twice:
1. Absolute test: Does the new strategy make money?
2. Incremental test: Does adding it to the existing portfolio improve the portfolio?

The second is ultimately more important.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple


@dataclass(frozen=True)
class PortfolioBaseline:
    """Baseline portfolio metrics for incremental comparison."""
    portfolio_id: str
    sharpe: float
    sortino: float
    max_drawdown: float
    cagr: float
    volatility: float
    turnover: float
    tail_risk: float  # CVaR or similar
    constituents: tuple  # tuple of hypothesis IDs
    fingerprint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_id": self.portfolio_id,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "cagr": self.cagr,
            "volatility": self.volatility,
            "turnover": self.turnover,
            "tail_risk": self.tail_risk,
            "constituents": list(self.constituents),
        }


@dataclass(frozen=True)
class IncrementalTestResult:
    """Result of an incremental alpha test."""
    hypothesis_id: str
    candidate_standalone_sharpe: float
    candidate_standalone_drawdown: float
    candidate_turnover: float
    correlation_with_existing: float
    # Portfolio deltas (positive = improvement)
    sharpe_delta: float
    sortino_delta: float
    drawdown_delta: float  # negative = lower drawdown = improvement
    turnover_delta: float
    tail_risk_delta: float
    # Verdict
    incremental_value: bool
    diversification_value: bool
    recommendation: str  # ADD, REJECT, CONDITIONAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "candidate_standalone_sharpe": self.candidate_standalone_sharpe,
            "candidate_standalone_drawdown": self.candidate_standalone_drawdown,
            "candidate_turnover": self.candidate_turnover,
            "correlation_with_existing": self.correlation_with_existing,
            "sharpe_delta": self.sharpe_delta,
            "sortino_delta": self.sortino_delta,
            "drawdown_delta": self.drawdown_delta,
            "turnover_delta": self.turnover_delta,
            "tail_risk_delta": self.tail_risk_delta,
            "incremental_value": self.incremental_value,
            "diversification_value": self.diversification_value,
            "recommendation": self.recommendation,
        }

    def compute_fingerprint(self) -> str:
        data = self.to_dict()
        payload = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class IncrementalAlphaTester:
    """Evaluates whether new alpha candidates improve the existing portfolio."""

    def __init__(self) -> None:
        self._results: List[IncrementalTestResult] = []
        self._baselines: Dict[str, PortfolioBaseline] = {}

    def set_baseline(self, baseline: PortfolioBaseline) -> None:
        """Set the current portfolio baseline for comparison."""
        self._baselines[baseline.portfolio_id] = baseline

    def evaluate(
        self,
        hypothesis_id: str,
        candidate_sharpe: float,
        candidate_drawdown: float,
        candidate_turnover: float,
        correlation_with_existing: float,
        portfolio_with_candidate: Dict[str, float],
        portfolio_id: str = "current",
    ) -> IncrementalTestResult:
        """Evaluate whether a candidate improves the existing portfolio.

        Args:
            hypothesis_id: candidate hypothesis
            candidate_sharpe: standalone Sharpe of candidate
            candidate_drawdown: standalone max drawdown
            candidate_turnover: standalone turnover
            correlation_with_existing: correlation with existing portfolio returns
            portfolio_with_candidate: portfolio metrics WITH candidate added
                (sharpe, sortino, max_drawdown, turnover, tail_risk)
            portfolio_id: which baseline to compare against

        Returns:
            IncrementalTestResult
        """
        baseline = self._baselines.get(portfolio_id)
        if baseline is None:
            baseline = PortfolioBaseline(
                portfolio_id=portfolio_id,
                sharpe=0.0, sortino=0.0, max_drawdown=0.0,
                cagr=0.0, volatility=0.0, turnover=0.0, tail_risk=0.0,
                constituents=(),
            )

        sharpe_delta = portfolio_with_candidate.get("sharpe", 0.0) - baseline.sharpe
        sortino_delta = portfolio_with_candidate.get("sortino", 0.0) - baseline.sortino
        drawdown_delta = portfolio_with_candidate.get("max_drawdown", 0.0) - baseline.max_drawdown
        turnover_delta = portfolio_with_candidate.get("turnover", 0.0) - baseline.turnover
        tail_risk_delta = portfolio_with_candidate.get("tail_risk", 0.0) - baseline.tail_risk

        incremental_value = (
            sharpe_delta > 0.01  # at least 1% Sharpe improvement
            and drawdown_delta <= 0.05  # drawdown doesn't increase more than 5%
        )

        diversification_value = (
            correlation_with_existing < 0.7
            and (sharpe_delta > 0 or drawdown_delta < -0.01)
        )

        # Recommendation
        # High correlation (>0.9) with no meaningful diversification → REJECT regardless
        if correlation_with_existing >= 0.9 and not diversification_value:
            recommendation = "REJECT"
        elif incremental_value and diversification_value:
            recommendation = "ADD"
        elif incremental_value or (diversification_value and sharpe_delta > -0.05):
            recommendation = "CONDITIONAL"
        else:
            recommendation = "REJECT"

        result = IncrementalTestResult(
            hypothesis_id=hypothesis_id,
            candidate_standalone_sharpe=candidate_sharpe,
            candidate_standalone_drawdown=candidate_drawdown,
            candidate_turnover=candidate_turnover,
            correlation_with_existing=correlation_with_existing,
            sharpe_delta=sharpe_delta,
            sortino_delta=sortino_delta,
            drawdown_delta=drawdown_delta,
            turnover_delta=turnover_delta,
            tail_risk_delta=tail_risk_delta,
            incremental_value=incremental_value,
            diversification_value=diversification_value,
            recommendation=recommendation,
        )
        self._results.append(result)
        return result

    def get_results(self) -> List[IncrementalTestResult]:
        return list(self._results)

    def get_additions(self) -> List[IncrementalTestResult]:
        return [r for r in self._results if r.recommendation == "ADD"]

    def get_rejections(self) -> List[IncrementalTestResult]:
        return [r for r in self._results if r.recommendation == "REJECT"]
