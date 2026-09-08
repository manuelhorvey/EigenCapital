"""R4-S shadow portfolio selector.

Design (research brief Section 8): the selector maximizes expected portfolio
quality while controlling redundant risk. It is NOT a correlation filter:
"remove correlated instruments, take 4-6" is explicitly rejected here.

Objective:
    quality(P) = gross_edge(P)
               - λ_risk · vol_annual(P)
               - λ_corr · corr_redundancy(P)
               - λ_ccy · max(0, max_currency_share − 0.5)
               - λ_fac · max(0, max_factor_share − 0.5)

where corr_redundancy(P) = Σ over positions of
    max(0, max DIRECTION-ADJUSTED pairwise correlation with the rest of P − 0.5).

Why redundancy instead of average correlation: the average pairwise
correlation saturates once the portfolio is already correlated, so adding a
third identical copy stops changing it and the penalty vanishes. The
redundancy term is linear in the number of correlated positions — each copy
of an already-held exposure pays again — which is exactly the stacking
behavior this experiment is designed to detect. Direction adjustment means
LONG A + SHORT B with anti-correlated returns is seen as the same economic
bet, not as "diversified". HHI is reported as a concentration metric but
deliberately NOT an objective term: rewarding lower HHI would reward "more
positions" for their own sake, which the brief explicitly warns against.

DIAGNOSTIC EVIDENCE (v0.2.0 — no behavior change, additive fields only):
    * chain_by_n — the composition, quality, and metrics of every greedy
      prefix P_1..P_k, so edge-by-size and the risk/edge frontier can be
      studied without re-running the selector.
    * marginal_components — for every candidate evaluated, the decomposition
      of its marginal Δquality into edge and each penalty term.
    * dominant_rejection — a single measurable reason per rejected candidate
      (high_correlation / volatility_penalty / currency_concentration /
      factor_concentration / weak_edge / portfolio_capacity / ...).
    * regime — caller-supplied market-regime context (vol_now, vol_median)
      recorded verbatim for regime-interaction analysis.

EDGE PROXY: the only expected-edge quantity R4 exposes is the signal weight
itself (cross-sectionally ranked, vol-scaled, clipped momentum). We document
`gross_edge = Σ|w|` as the edge proxy. It is a relative score, not a return
forecast — this is recorded in every decision's provenance.

HYPERPARAMETERS: all lambdas are experimental, configuration-driven, hashed
into the decision record, and isolated from frozen R4 configuration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd

from eigencapital.shadow.portfolio.correlation import CorrelationSnapshot
from eigencapital.shadow.portfolio.exposure import ExposureModel
from eigencapital.shadow.portfolio.metrics import PortfolioMetrics, compute_portfolio_metrics

SHADOW_SELECTOR_VERSION = "r4s-shadow-selector-0.2.1"

MIN_SIGNAL_WEIGHT = 0.005  # matches the frozen R4 activation threshold |w| > 0.005
UNKNOWN_VOL_ANNUAL = 0.15  # conservative default when a candidate lacks vol history

# Hard-cap violation codes. Rejection labels are only trusted when they come
# from a FINAL-state evaluation (R4-S 2026-09-08: a cap tripped in an early
# greedy trial must not stick once the final portfolio no longer violates).
HARD_CAP_REASONS = {"currency_concentration", "factor_concentration", "asset_class_concentration"}


def _corr_redundancy(
    weights: Dict[str, float],
    corr: pd.DataFrame,
    threshold: float,
) -> float:
    """Sum over positions of their excess DIRECTION-ADJUSTED co-movement.

    What matters for portfolio risk is the co-movement of POSITIONS:
        ρ_position(a, b) = sign(w_a) · sign(w_b) · ρ_returns(a, b).
    A LONG AUDUSD plus a SHORT GBPUSD whose returns are anti-correlated is
    the SAME bet — it must be penalized exactly like two correlated longs.
    Each position contributes max(0, max ρ_position with the rest − threshold),
    so N redundant copies pay N·excess and stacking is always penalized again.
    Missing correlations (NaN) contribute nothing (unknown ≠ redundant).
    """
    symbols = [s for s in weights if weights[s] != 0.0 and s in corr.index]
    if len(symbols) < 2:
        return 0.0
    redundancy = 0.0
    for s in symbols:
        sign_s = 1.0 if weights[s] > 0 else -1.0
        best = 0.0
        for t in symbols:
            if t == s:
                continue
            rho = corr.loc[s, t]
            if pd.isna(rho):
                continue
            sign_t = 1.0 if weights[t] > 0 else -1.0
            pos_rho = float(rho) * sign_s * sign_t
            best = max(best, pos_rho)
        redundancy += max(0.0, best - threshold)
    return redundancy


def _classify_dominant_rejection(cand: ShadowCandidate) -> str | None:
    """Reduce a rejection to one measurable dominant reason (diagnostics).

    Priority:
      1. Hard-cap violations (currency/factor/asset-class concentration).
      2. Portfolio capacity (max positions reached / universe exhausted).
      3. Quality-based: the largest positive penalty component; if the
         candidate's edge is dominated by the combined penalty burden
         (< 50% of total penalties), classify as weak_edge.
    """
    r = cand.rejection_reason
    if r is None:
        return None
    if r in HARD_CAP_REASONS:
        return r
    if r in {"max_positions_reached", "candidate_universe_empty_or_infeasible"}:
        return "portfolio_capacity"
    comps = cand.marginal_components or {}
    edge = comps.get("edge_delta", 0.0)
    penalties = {
        "high_correlation": max(0.0, comps.get("corr_penalty_delta", 0.0)),
        "volatility_penalty": max(0.0, comps.get("vol_penalty_delta", 0.0)),
        "currency_concentration": max(0.0, comps.get("ccy_penalty_delta", 0.0)),
        "factor_concentration": max(0.0, comps.get("factor_penalty_delta", 0.0)),
    }
    total = sum(penalties.values())
    if total <= 1e-12 or edge <= 1e-12:
        return "weak_edge"
    if edge < 0.5 * total:
        return "weak_edge"
    return max(penalties, key=lambda k: penalties[k])


@dataclass
class ShadowCandidate:
    """One R4 candidate as seen by the shadow selector.

    Fields are read from the frozen R4 signal/selection pipeline. Nothing
    here can influence R4 itself. This is a WORKING record: the selector
    fills in `rejection_reason` / `marginal_quality` / `marginal_components`
    / `dominant_rejection` during construction; the finalized state is
    snapshotted into the ShadowDecision record.
    """

    symbol: str
    weight: float  # signed R4 signal weight (the edge proxy)
    direction: str  # "LONG" | "SHORT"
    asset_class: str
    factor_group: str
    feasible: bool
    r4_rank: int  # 1 = strongest |w| in R4's own ordering
    annualized_vol: float | None = None
    history_sufficient: bool = True
    min_lot_cost: float | None = None
    rejection_reason: str | None = None
    marginal_quality: float | None = None
    marginal_components: Dict[str, float] | None = None
    dominant_rejection: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "weight": round(self.weight, 6),
            "direction": self.direction,
            "asset_class": self.asset_class,
            "factor_group": self.factor_group,
            "feasible": self.feasible,
            "r4_rank": self.r4_rank,
            "annualized_vol": round(self.annualized_vol, 6) if self.annualized_vol is not None else None,
            "history_sufficient": self.history_sufficient,
            "min_lot_cost": self.min_lot_cost,
            "rejection_reason": self.rejection_reason,
            "marginal_quality": round(self.marginal_quality, 8) if self.marginal_quality is not None else None,
            "marginal_components": self.marginal_components,
            "dominant_rejection": self.dominant_rejection,
        }


@dataclass(frozen=True)
class ShadowSelectorConfig:
    """Experimental selector hyperparameters (Section 8 of the brief)."""

    max_positions: int = 8
    min_weight: float = MIN_SIGNAL_WEIGHT
    lambda_risk: float = 1.0
    lambda_correlation: float = 0.5
    lambda_currency: float = 0.1
    lambda_factor: float = 0.1
    min_positive_marginal: float = 1e-9
    correlation_cluster_threshold: float = 0.7
    unknown_vol_annual: float = UNKNOWN_VOL_ANNUAL
    # Excess thresholds: only redundancy ABOVE these levels is penalized.
    correlation_excess_threshold: float = 0.5
    currency_excess_threshold: float = 0.5
    factor_excess_threshold: float = 0.5
    # Hard exposure caps (disqualifying backstop; soft λ penalties above).
    # max_asset_class_pct is 1.0 (effectively disabled): the production
    # universe is FX-dominated, so an all-FX portfolio is normal and asset-
    # class share is not a redundancy signal here — currency/factor/correlation
    # penalties carry the concentration weight instead.
    max_currency_exposure_pct: float = 0.80
    max_factor_group_pct: float = 0.80
    max_asset_class_pct: float = 1.0

    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "max_positions": self.max_positions,
                "min_weight": self.min_weight,
                "lambda_risk": self.lambda_risk,
                "lambda_correlation": self.lambda_correlation,
                "lambda_currency": self.lambda_currency,
                "lambda_factor": self.lambda_factor,
                "min_positive_marginal": self.min_positive_marginal,
                "correlation_cluster_threshold": self.correlation_cluster_threshold,
                "unknown_vol_annual": self.unknown_vol_annual,
                "correlation_excess_threshold": self.correlation_excess_threshold,
                "currency_excess_threshold": self.currency_excess_threshold,
                "factor_excess_threshold": self.factor_excess_threshold,
                "max_currency_exposure_pct": self.max_currency_exposure_pct,
                "max_factor_group_pct": self.max_factor_group_pct,
                "max_asset_class_pct": self.max_asset_class_pct,
            },
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def exposure_config(self) -> ExposureModel:
        from eigencapital.shadow.portfolio.exposure import ExposureModelConfig

        return ExposureModel(
            ExposureModelConfig(
                max_currency_exposure_pct=self.max_currency_exposure_pct,
                max_factor_group_pct=self.max_factor_group_pct,
                max_asset_class_pct=self.max_asset_class_pct,
            )
        )


@dataclass
class ShadowDecision:
    """Complete shadow decision record for one R4 cycle."""

    cycle_id: str
    decision_timestamp: str
    signal_date: str
    status: str  # SELECTED | NO_PORTFOLIO | NO_CANDIDATES
    status_reason: str
    candidates: List[Dict[str, Any]]
    baseline: Dict[str, Any]  # {symbols, weights, metrics}
    selected: Dict[str, Any]  # {symbols, weights, metrics}
    quality_by_n: Dict[int, float]
    chain_by_n: Dict[int, Dict[str, Any]]  # every greedy prefix + its metrics
    edge_metrics: Dict[str, Any]
    correlation: Dict[str, Any]
    regime: Dict[str, Any]
    selector_version: str
    config_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "decision_timestamp": self.decision_timestamp,
            "signal_date": self.signal_date,
            "status": self.status,
            "status_reason": self.status_reason,
            "candidates": self.candidates,
            "baseline": self.baseline,
            "selected": self.selected,
            "quality_by_n": {str(k): round(v, 6) for k, v in self.quality_by_n.items()},
            "chain_by_n": {str(k): v for k, v in self.chain_by_n.items()},
            "edge_metrics": self.edge_metrics,
            "correlation": self.correlation,
            "regime": self.regime,
            "selector_version": self.selector_version,
            "config_hash": self.config_hash,
        }


class ShadowSelector:
    """Deterministic, exposure-aware portfolio constructor (shadow-only)."""

    def __init__(self, config: ShadowSelectorConfig | None = None) -> None:
        self.config = config or ShadowSelectorConfig()
        self._exposure = self.config.exposure_config()

    # ── quality / metrics helpers ─────────────────────────────────────
    def _quality_components(
        self,
        weights: Dict[str, float],
        snapshot: CorrelationSnapshot | None,
        vol: Dict[str, float],
    ) -> Tuple[Dict[str, float], PortfolioMetrics]:
        """Raw objective components for a portfolio + its full metrics."""
        if not weights:
            metrics = compute_portfolio_metrics({}, vol, pd.DataFrame(), {})
            return {"edge": 0.0, "vol": 0.0, "corr_redundancy": 0.0, "ccy_excess": 0.0, "factor_excess": 0.0}, metrics
        corr = snapshot.corr if snapshot is not None else pd.DataFrame()
        summary = self._exposure.concentration_summary(weights)
        metrics = compute_portfolio_metrics(weights, vol, corr, summary)
        max_ccy = summary["max_currency_exposure"]["pct"]
        max_fx = summary["max_cluster_exposure"]["pct"]
        components = {
            "edge": metrics.gross_edge,
            "vol": metrics.portfolio_vol_annual,
            "corr_redundancy": _corr_redundancy(weights, corr, self.config.correlation_excess_threshold),
            "ccy_excess": max(0.0, max_ccy - self.config.currency_excess_threshold),
            "factor_excess": max(0.0, max_fx - self.config.factor_excess_threshold),
        }
        return components, metrics

    def _quality(
        self,
        weights: Dict[str, float],
        snapshot: CorrelationSnapshot | None,
        vol: Dict[str, float],
    ) -> Tuple[float, PortfolioMetrics]:
        components, metrics = self._quality_components(weights, snapshot, vol)
        q = (
            components["edge"]
            - self.config.lambda_risk * components["vol"]
            - self.config.lambda_correlation * components["corr_redundancy"]
            - self.config.lambda_currency * components["ccy_excess"]
            - self.config.lambda_factor * components["factor_excess"]
        )
        return float(q), metrics

    def select(
        self,
        candidates: List[ShadowCandidate],
        snapshot: CorrelationSnapshot | None,
        baseline_symbols: List[str],
        cycle_id: str = "",
        decision_timestamp: str = "",
        signal_date: str = "",
        regime: Dict[str, Any] | None = None,
    ) -> ShadowDecision:
        """Run the greedy selection over the frozen R4 candidate universe.

        Args:
            candidates: full candidate universe (exactly what R4 produced).
            snapshot: correlation evidence, or None when history is missing.
            baseline_symbols: R4's own selection (top-N by |w|) — recorded
                as the untouched control group.
            regime: caller-supplied regime context (e.g. vol_now/vol_median),
                recorded verbatim for regime-interaction diagnostics.
        """
        # Deterministic ordering: |weight| desc, then symbol asc (ties).
        feasible = [c for c in candidates if c.feasible and abs(c.weight) >= self.config.min_weight]
        feasible.sort(key=lambda c: (-abs(c.weight), c.symbol))
        remaining = {c.symbol: c for c in feasible}
        all_candidates = sorted(candidates, key=lambda c: (c.r4_rank, c.symbol))

        vol: Dict[str, float] = {}
        for c in all_candidates:
            if c.annualized_vol is not None and c.annualized_vol > 0:
                vol[c.symbol] = c.annualized_vol
            else:
                vol[c.symbol] = self.config.unknown_vol_annual

        if not feasible:
            decision = self._build_decision(
                candidates=all_candidates,
                snapshot=snapshot,
                baseline_symbols=baseline_symbols,
                selected_symbols=[],
                status="NO_CANDIDATES",
                status_reason="candidate_universe_empty_or_infeasible",
                quality_by_n={},
                chain_by_n={},
                cycle_id=cycle_id,
                decision_timestamp=decision_timestamp,
                signal_date=signal_date,
                regime=regime or {},
                vol=vol,
            )
            return decision

        # Greedy chain
        selected: List[str] = []
        selected_weights: Dict[str, float] = {}
        quality_by_n: Dict[int, float] = {}
        chain_by_n: Dict[int, Dict[str, Any]] = {}
        components_prev, metrics_prev = self._quality_components({}, snapshot, vol)
        quality_0 = (
            components_prev["edge"]
            - self.config.lambda_risk * components_prev["vol"]
            - self.config.lambda_correlation * components_prev["corr_redundancy"]
            - self.config.lambda_currency * components_prev["ccy_excess"]
            - self.config.lambda_factor * components_prev["factor_excess"]
        )
        quality_by_n[0] = float(quality_0)
        chain_by_n[0] = {
            "symbols": [],
            "quality": round(float(quality_0), 6),
            "metrics": metrics_prev.to_dict(),
        }
        stop_reason = "max_positions_reached"

        for step in range(self.config.max_positions):
            best_sym: str | None = None
            best_delta: float | None = None
            best_quality: float | None = None
            best_metrics: PortfolioMetrics | None = None
            marginal: Dict[str, float] = {}

            for sym in sorted(remaining, key=lambda s: (-abs(remaining[s].weight), s)):
                cand = remaining[sym]
                trial = dict(selected_weights)
                trial[sym] = cand.weight
                violations = self._exposure.violates(trial)
                if violations:
                    cand.rejection_reason = violations[0]  # hard constraint
                    cand.marginal_quality = None
                    continue
                components_trial, metrics_trial = self._quality_components(trial, snapshot, vol)
                comps = {
                    "edge_delta": round(components_trial["edge"] - components_prev["edge"], 8),
                    "vol_penalty_delta": round(
                        self.config.lambda_risk * (components_trial["vol"] - components_prev["vol"]), 8
                    ),
                    "corr_penalty_delta": round(
                        self.config.lambda_correlation
                        * (components_trial["corr_redundancy"] - components_prev["corr_redundancy"]),
                        8,
                    ),
                    "ccy_penalty_delta": round(
                        self.config.lambda_currency * (components_trial["ccy_excess"] - components_prev["ccy_excess"]),
                        8,
                    ),
                    "factor_penalty_delta": round(
                        self.config.lambda_factor
                        * (components_trial["factor_excess"] - components_prev["factor_excess"]),
                        8,
                    ),
                }
                comps["quality_delta"] = round(
                    comps["edge_delta"]
                    - comps["vol_penalty_delta"]
                    - comps["corr_penalty_delta"]
                    - comps["ccy_penalty_delta"]
                    - comps["factor_penalty_delta"],
                    8,
                )
                delta = comps["quality_delta"]
                marginal[sym] = delta
                if cand.marginal_components is None:
                    cand.marginal_components = comps
                if best_delta is None or delta > best_delta + 1e-15:
                    best_delta = delta
                    best_quality = (
                        components_trial["edge"]
                        - self.config.lambda_risk * components_trial["vol"]
                        - self.config.lambda_correlation * components_trial["corr_redundancy"]
                        - self.config.lambda_currency * components_trial["ccy_excess"]
                        - self.config.lambda_factor * components_trial["factor_excess"]
                    )
                    best_metrics = metrics_trial
                    best_sym = sym

            # Record marginal quality for every candidate that had one.
            for sym, d in marginal.items():
                if remaining[sym].marginal_quality is None:
                    remaining[sym].marginal_quality = d

            if best_sym is None or best_delta is None or best_delta <= self.config.min_positive_marginal:
                stop_reason = "expected_edge_insufficient" if best_sym is None else "no_positive_marginal_quality"
                # The best (or only) candidate failed to improve quality —
                # expose WHY rather than hiding it.
                if best_sym is not None:
                    remaining[best_sym].rejection_reason = "incremental_quality_non_positive"
                break

            assert best_sym is not None and best_quality is not None and best_metrics is not None
            chosen = remaining.pop(best_sym)
            chosen.rejection_reason = None
            selected.append(best_sym)
            selected_weights[best_sym] = chosen.weight
            components_prev, metrics_prev = self._quality_components(selected_weights, snapshot, vol)
            quality_by_n[step + 1] = best_quality
            chain_by_n[step + 1] = {
                "symbols": list(selected),
                "quality": round(best_quality, 6),
                "metrics": best_metrics.to_dict(),
            }

        # Candidates left over because the loop ended early or max hit.
        # R4-S 2026-09-08: rejection labels must reflect the FINAL portfolio,
        # not an early greedy trial. A candidate that tripped a hard cap in a
        # 2-name trial (e.g. {XAUUSD, AUDUSD} → 84% safe_haven) may not violate
        # at all against the final selection — carrying that label forward
        # misattributes the exclusion (AUDUSD was recorded factor_concentration
        # while no final-state trial violated). Recompute every leftover
        # candidate's hard-cap status against the FINAL selected weights;
        # hard-cap labels survive only when the final state actually violates,
        # otherwise the honest reason is the greedy stop condition.
        for sym, cand in remaining.items():
            hard = self._exposure.final_state_rejection(selected_weights, sym, cand.weight)
            if hard is not None:
                cand.rejection_reason = hard
            elif cand.rejection_reason is None or cand.rejection_reason in HARD_CAP_REASONS:
                cand.rejection_reason = stop_reason

        # Finalize dominant rejection classification.
        for cand in all_candidates:
            cand.dominant_rejection = _classify_dominant_rejection(cand)

        status = "SELECTED"
        status_reason = f"greedy_marginal_quality_stop:{stop_reason}"
        if not selected:
            status = "NO_PORTFOLIO"
            status_reason = f"expected_edge_insufficient:{stop_reason}"

        return self._build_decision(
            candidates=all_candidates,
            snapshot=snapshot,
            baseline_symbols=baseline_symbols,
            selected_symbols=selected,
            status=status,
            status_reason=status_reason,
            quality_by_n=quality_by_n,
            chain_by_n=chain_by_n,
            cycle_id=cycle_id,
            decision_timestamp=decision_timestamp,
            signal_date=signal_date,
            regime=regime or {},
            vol=vol,
        )

    # ── decision assembly ─────────────────────────────────────────────
    def _build_decision(
        self,
        candidates: List[ShadowCandidate],
        snapshot: CorrelationSnapshot | None,
        baseline_symbols: List[str],
        selected_symbols: List[str],
        status: str,
        status_reason: str,
        quality_by_n: Dict[int, float],
        chain_by_n: Dict[int, Dict[str, Any]],
        cycle_id: str,
        decision_timestamp: str,
        signal_date: str,
        regime: Dict[str, Any],
        vol: Dict[str, float],
    ) -> ShadowDecision:
        weights_by_sym = {c.symbol: c.weight for c in candidates}

        # Baseline = frozen R4 selection, measured with the same calculator.
        baseline_syms = [s for s in baseline_symbols if s in weights_by_sym]
        baseline_weights = {s: weights_by_sym[s] for s in baseline_syms}
        baseline_metrics = self._metrics_for(baseline_weights, snapshot, vol)

        selected_weights = {s: weights_by_sym[s] for s in selected_symbols}
        selected_metrics = self._metrics_for(selected_weights, snapshot, vol)

        # Edge retention vs the frozen R4 control group.
        r4_gross = baseline_metrics.gross_edge
        shadow_gross = selected_metrics.gross_edge
        top_k = min(5, len(baseline_syms))
        r4_top = set(baseline_syms[:top_k]) if top_k else set()
        shadow_set = set(selected_symbols)
        retained_top = len(r4_top & shadow_set)
        edge_metrics = {
            "r4_gross_edge": round(r4_gross, 6),
            "shadow_gross_edge": round(shadow_gross, 6),
            "edge_retained_pct": round(100.0 * shadow_gross / r4_gross, 2) if r4_gross > 0 else None,
            "candidate_edge_discarded_pct": round(100.0 * (r4_gross - shadow_gross) / r4_gross, 2)
            if r4_gross > 0
            else None,
            "top_signal_retention": f"{retained_top}/{top_k}",
            "r4_top_signals": sorted(r4_top),
        }

        return ShadowDecision(
            cycle_id=cycle_id,
            decision_timestamp=decision_timestamp,
            signal_date=signal_date,
            status=status,
            status_reason=status_reason,
            candidates=[c.to_dict() for c in candidates],
            baseline={"symbols": baseline_syms, "weights": baseline_weights, "metrics": baseline_metrics.to_dict()},
            selected={
                "symbols": selected_symbols,
                "weights": selected_weights,
                "metrics": selected_metrics.to_dict(),
            },
            quality_by_n=quality_by_n,
            chain_by_n=chain_by_n,
            edge_metrics=edge_metrics,
            correlation=snapshot.to_dict() if snapshot else {"as_of": signal_date, "available": False},
            regime=regime,
            selector_version=SHADOW_SELECTOR_VERSION,
            config_hash=self.config.config_hash(),
        )

    def _metrics_for(
        self,
        weights: Dict[str, float],
        snapshot: CorrelationSnapshot | None,
        vol: Dict[str, float],
    ) -> PortfolioMetrics:
        if not weights:
            return compute_portfolio_metrics({}, vol, pd.DataFrame(), {})
        corr = snapshot.corr if snapshot is not None else pd.DataFrame()
        summary = self._exposure.concentration_summary(weights)
        return compute_portfolio_metrics(weights, vol, corr, summary)
