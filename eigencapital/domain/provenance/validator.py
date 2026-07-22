"""ProvenanceValidator — M2 validation suite for Decision Provenance.

Enforces schema invariants, cross-context consistency, value-range
constraints, and referential integrity across the six provenance
contexts.  Designed to be called:

1. After capture — validate before persisting (guard).
2. In tests — verify round-trip fidelity.
3. Batch audit — scan historical records for data quality issues.

Usage::

    from eigencapital.domain.provenance.validator import (
        ProvenanceValidator,
        ValidationResult,
    )

    validator = ProvenanceValidator()
    result = validator.validate(provenance)
    if not result.is_valid:
        for issue in result.errors:
            logger.error("PROVENANCE VALIDATION: %s", issue)
        for issue in result.warnings:
            logger.warning("PROVENANCE WARNING: %s", issue)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from eigencapital.domain.provenance import PROVENANCE_SCHEMA_VERSION
from eigencapital.domain.provenance.decision_provenance import DecisionProvenance
from eigencapital.domain.provenance.feature_context import FeatureContext
from eigencapital.domain.provenance.market_context import MarketContext
from eigencapital.domain.provenance.model_context import ModelContext
from eigencapital.domain.provenance.portfolio_context import PortfolioContext
from eigencapital.domain.provenance.execution_context import ExecutionContext as ProvenanceExecutionContext
from eigencapital.domain.provenance.decision_trace import DecisionTrace


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def all_issues(self) -> list[ValidationIssue]:
        return self.errors + self.warnings

    def _e(self, field: str, msg: str) -> None:
        self.errors.append(ValidationIssue(field, msg, severity="error"))

    def _w(self, field: str, msg: str) -> None:
        self.warnings.append(ValidationIssue(field, msg, severity="warning"))

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def __bool__(self) -> bool:
        return self.is_valid


class ProvenanceValidator:
    """Validates DecisionProvenance records against schema and domain rules.

    Every rule is isolated in its own method so subclasses can override
    individual checks without copying the entire suite.
    """

    def __init__(self, strict: bool = False):
        self.strict = strict

    def validate(self, provenance: DecisionProvenance) -> ValidationResult:
        r = ValidationResult()
        self._check_identity(provenance, r)
        self._check_schema_version(provenance, r)
        self._check_market_context(provenance, r)
        self._check_feature_context(provenance, r)
        self._check_model_context(provenance, r)
        self._check_portfolio_context(provenance, r)
        self._check_execution_context(provenance, r)
        self._check_decision_trace(provenance, r)
        self._check_cross_context_consistency(provenance, r)
        return r

    # ── Identity ─────────────────────────────────────────────────────

    def _check_identity(self, p: DecisionProvenance, r: ValidationResult) -> None:
        if not p.decision_id or not p.decision_id.decision_id:
            r._e("decision_id.decision_id", "must be a non-empty string")
        if not p.decision_id or not p.decision_id.lineage_id:
            r._e("decision_id.lineage_id", "must be a non-empty string")
        if p.cycle_id < 0:
            r._e("cycle_id", f"must be >= 0, got {p.cycle_id}")
        if not p.asset:
            r._e("asset", "must be a non-empty string")
        if not p.decision_timestamp:
            r._e("decision_timestamp", "must be a non-empty ISO string")

    def _check_schema_version(self, p: DecisionProvenance, r: ValidationResult) -> None:
        if p.schema_version < 1:
            r._e("schema_version", f"must be >= 1, got {p.schema_version}")
        if p.schema_version > PROVENANCE_SCHEMA_VERSION:
            r._w("schema_version", f"ahead of current version ({p.schema_version} > {PROVENANCE_SCHEMA_VERSION}) — forward compat mode")

    # ── MarketContext ────────────────────────────────────────────────

    def _check_market_context(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.market
        if ctx is None:
            if self.strict:
                r._e("market", "market context is required in strict mode")
            return

        if ctx.close_price is None or (isinstance(ctx.close_price, float) and ctx.close_price <= 0):
            r._e("market.close_price", f"must be > 0, got {ctx.close_price}")
        if ctx.spread_bps is not None and (ctx.spread_bps < 0 or ctx.spread_bps > 1000):
            r._w("market.spread_bps", f"suspicious value (0-1000 expected, got {ctx.spread_bps})")
        if ctx.n_bars < 0:
            r._w("market.n_bars", f"cannot be negative, got {ctx.n_bars}")

    # ── FeatureContext ───────────────────────────────────────────────

    def _check_feature_context(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.features
        if ctx is None:
            if self.strict:
                r._e("features", "feature context is required in strict mode")
            return

        if not ctx.feature_hash:
            r._w("features.feature_hash", "empty feature hash")
        if ctx.n_features < 0:
            r._e("features.n_features", f"must be >= 0, got {ctx.n_features}")
        if ctx.feature_vector and ctx.n_features != len(ctx.feature_vector):
            r._w("features.n_features", f"declared {ctx.n_features} but vector has {len(ctx.feature_vector)} entries")

    # ── ModelContext ─────────────────────────────────────────────────

    def _check_model_context(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.model
        if ctx is None:
            if self.strict:
                r._e("model", "model context is required in strict mode")
            return

        if not ctx.model_hash:
            r._w("model.model_hash", "empty model hash")

        prob_sum = ctx.prob_long + ctx.prob_short + ctx.prob_neutral
        if abs(prob_sum - 1.0) > 0.02:
            r._w("model.probabilities", f"sum {prob_sum:.4f} deviates from 1.0 by more than 0.02")

        if ctx.calibrated_confidence is not None and (ctx.calibrated_confidence < 0 or ctx.calibrated_confidence > 1.0):
            r._w("model.calibrated_confidence", f"must be in [0,1], got {ctx.calibrated_confidence}")

        if ctx.calibration_ece is not None and (ctx.calibration_ece < 0 or ctx.calibration_ece > 1.0):
            r._w("model.calibration_ece", f"must be in [0,1], got {ctx.calibration_ece}")

    # ── PortfolioContext ─────────────────────────────────────────────

    def _check_portfolio_context(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.portfolio
        if ctx is None:
            if self.strict:
                r._e("portfolio", "portfolio context is required in strict mode")
            return

        if ctx.total_equity < 0:
            r._e("portfolio.total_equity", f"must be >= 0, got {ctx.total_equity}")
        if ctx.drawdown_pct < -1.0 or ctx.drawdown_pct > 0.0:
            r._e("portfolio.drawdown_pct", f"must be in [-1.0, 0.0], got {ctx.drawdown_pct}")
        if ctx.open_position_count < 0:
            r._e("portfolio.open_position_count", f"must be >= 0, got {ctx.open_position_count}")
        if ctx.gross_exposure < 0:
            r._e("portfolio.gross_exposure", f"must be >= 0, got {ctx.gross_exposure}")
        if len(ctx.positions) != ctx.open_position_count:
            r._w("portfolio.positions", f"declared {ctx.open_position_count} but got {len(ctx.positions)} position snapshots")

        admitted_count = len(ctx.positions)
        if admitted_count > 0 and ctx.net_exposure == 0 and ctx.gross_exposure > 0:
            r._w("portfolio.net_exposure", "zero net with non-zero gross — potentially perfectly hedged or unbalanced")

    # ── ExecutionContext ─────────────────────────────────────────────

    def _check_execution_context(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.runtime
        if ctx is None:
            if self.strict:
                r._e("runtime", "execution context is required in strict mode")
            return

        if ctx.cycle_id < 0:
            r._e("runtime.cycle_id", f"must be >= 0, got {ctx.cycle_id}")
        if ctx.halt_ratio < 0 or ctx.halt_ratio > 1.0:
            r._e("runtime.halt_ratio", f"must be in [0,1], got {ctx.halt_ratio}")
        if ctx.exposure_multiplier < 0 or ctx.exposure_multiplier > 2.0:
            r._w("runtime.exposure_multiplier", f"unusual range [0-2] expected, got {ctx.exposure_multiplier}")
        if ctx.n_assets < 0:
            r._e("runtime.n_assets", f"must be >= 0, got {ctx.n_assets}")
        if ctx.n_healthy < 0:
            r._e("runtime.n_healthy", f"must be >= 0, got {ctx.n_healthy}")
        if ctx.n_halted < 0:
            r._e("runtime.n_halted", f"must be >= 0, got {ctx.n_halted}")
        if ctx.n_healthy + ctx.n_halted > ctx.n_assets and ctx.n_assets > 0:
            r._w("runtime.health_counts", f"healthy+halted ({ctx.n_healthy}+{ctx.n_halted}) exceeds n_assets ({ctx.n_assets})")

    # ── DecisionTrace ────────────────────────────────────────────────

    def _check_decision_trace(self, p: DecisionProvenance, r: ValidationResult) -> None:
        ctx = p.decision
        if ctx is None:
            if self.strict:
                r._e("decision", "decision trace is required in strict mode")
            return

        if not ctx.final_signal:
            r._e("decision.final_signal", "must be a non-empty string")
        valid_signals = {"BUY", "SELL", "HOLD", "FLAT", "NONE", "suppressed"}
        if ctx.final_signal.upper() not in {s.upper() for s in valid_signals}:
            r._w("decision.final_signal", f"unexpected signal '{ctx.final_signal}'")

        passed = sum(1 for v in ctx.gates_trace.values() if v is True)
        if ctx.n_gates_passed != passed and not self.strict:
            r._w("decision.n_gates_passed", f"declared {ctx.n_gates_passed} but gates_trace shows {passed}")
        if ctx.n_gates_blocked != len(ctx.gates_blocked):
            r._w("decision.n_gates_blocked", f"declared {ctx.n_gates_blocked} but gates_blocked has {len(ctx.gates_blocked)}")

    # ── Cross-context consistency ───────────────────────────────────

    def _check_cross_context_consistency(self, p: DecisionProvenance, r: ValidationResult) -> None:
        if p.market and p.market.asset and p.market.asset != p.asset:
            r._e("cross_context.asset", f"market asset '{p.market.asset}' != provenance asset '{p.asset}'")

        if p.runtime and p.runtime.cycle_id != p.cycle_id:
            r._w("cross_context.cycle_id", f"runtime cycle_id {p.runtime.cycle_id} != provenance cycle_id {p.cycle_id}")

        if p.portfolio and p.runtime:
            if abs(p.portfolio.drawdown_pct - p.runtime.drawdown_pct) > 0.001:
                r._w("cross_context.drawdown_pct", f"portfolio ({p.portfolio.drawdown_pct}) != runtime ({p.runtime.drawdown_pct})")

        if p.features and p.features.feature_hash:
            if p.decision and hasattr(p.decision, "gates_trace") and "feature_hash" in p.decision.gates_trace:
                pass

    @classmethod
    def validate_batch(cls, records: list[DecisionProvenance], strict: bool = False) -> ValidationResult:
        validator = cls(strict=strict)
        combined = ValidationResult()
        for record in records:
            combined.merge(validator.validate(record))
        return combined
