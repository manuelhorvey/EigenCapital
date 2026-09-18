"""Unit tests for R1 Phase B4 — combined evidence report.

Covers the frozen B4 contract:
- aggregation only: no new resampling, no pass/fail thresholds
- the six frozen questions answered (percentiles, widths, stability,
  dependence effect)
- three-label structure (observed path / diagnostic distributions /
  interpretation) present in structure AND markdown
- wording guard: experiment-percentiles, never future probabilities
- prominent B3 block metadata in the artifact
- determinism, provenance refusal, historical-metrics consistency check
"""

import pytest

from eigencapital.research.monte_carlo.block_bootstrap import run_block_bootstrap_test
from eigencapital.research.monte_carlo.bootstrap import run_bootstrap_test
from eigencapital.research.monte_carlo.evidence import (
    EvidenceReport,
    build_evidence_report,
    render_markdown,
)
from eigencapital.research.monte_carlo.permutation import run_permutation_test
from eigencapital.research.monte_carlo.schema import (
    TradeRecord,
    TradeStream,
    TradeStreamError,
)
from tests.unit.research.monte_carlo.test_permutation import _stream_with_pnls

CLUSTERED = [2.0, 2.0, 2.0, 2.0, -9.0, -9.0, -9.0, -9.0, 3.0, 3.0, 3.0, 3.0]


def _build_all(stream):
    """Run all three diagnostics with fixed seeds on one stream."""
    b1 = run_permutation_test(stream, n_permutations=200, seed=42)
    b2 = run_bootstrap_test(stream, n_resamples=200, seed=42)
    b3 = run_block_bootstrap_test(stream, block_length=4, n_resamples=200, seed=42)
    return b1, b2, b3


def _report(**overrides) -> EvidenceReport:
    s = _stream_with_pnls(CLUSTERED)
    b1, b2, b3 = _build_all(s)
    kwargs = dict(stream=s, permutation=b1, bootstrap=b2, block_bootstrap=b3)
    kwargs.update(overrides)
    return build_evidence_report(**kwargs)


class TestAggregationOnly:
    def test_six_questions_answered_in_artifact(self):
        report = _report()
        d = report.to_dict()
        # per-metric percentiles within each distribution (Q1-Q3)
        for metric, comp in d["resampled_diagnostic_distributions"].items():
            assert set(comp["percentile_in_experiment"]) == {"B1", "B2", "B3"}
            assert "quantiles" in comp  # Q4 widths derivable
            assert "width_ratio_vs_b2" in comp
        assert isinstance(report.stable_metrics, list)  # Q5
        assert isinstance(report.dependence_changed, list)  # Q6
        # the dependence effect is explicitly quantified per metric
        assert any("dependence" in k or "delta" in k for k in d["resampled_diagnostic_distributions"]["max_drawdown"])

    def test_no_pass_fail_verdict_field(self):
        d = _report().to_dict()
        blob = str(d).lower()
        assert "pass" not in blob and "fail" not in blob and "verdict" not in blob

    def test_determinism(self):
        d1 = _report().to_dict()
        d2 = _report().to_dict()
        assert d1 == d2


class TestThreeLabels:
    def test_labels_in_structure(self):
        d = _report().to_dict()
        assert "observed_historical_path" in d
        assert "resampled_diagnostic_distributions" in d
        assert "interpretation" in d

    def test_labels_in_markdown(self):
        md = render_markdown(_report())
        assert "OBSERVED HISTORICAL PATH" in md
        assert "RESAMPLED DIAGNOSTIC DISTRIBUTION" in md
        assert "INTERPRETATION" in md

    def test_markdown_percentile_wording_is_experiment_relative(self):
        md = render_markdown(_report())
        assert "percentile of the B1/B2/B3 resampled" in md
        assert "probability that future" in md  # appears in the guard as the INCORRECT example
        assert "Incorrect:" in md and "Correct:" in md

    def test_interpretation_lines_use_experiment_wording(self):
        report = _report()
        assert any("lies at the" in line and "percentile" in line for line in report.interpretation)
        assert any("probability" not in line or "None is a probability" in line for line in report.interpretation)


class TestBlockMetadataProminence:
    def test_block_metadata_in_artifact(self):
        d = _report().to_dict()
        b3 = d["resampling_config"]["B3"]
        assert b3["block_length_prespecified"] == 4
        assert b3["block_method"] == "moving_block"
        assert b3["blocks_per_resample"] == 3
        assert "pre-specified" in b3["block_length_note"]

    def test_block_metadata_prominent_in_markdown(self):
        md = render_markdown(_report())
        assert "Block length: 4 (pre-specified)" in md
        assert "moving_block" in md
        assert "Blocks per resample: 3" in md


class TestQuestions5And6:
    def test_dependence_effect_sorted_by_delta(self):
        """On the clustered stream, dependence should widen the DD tail (B3>B2)."""
        report = _report()
        dd = next(c for c in report.comparisons if c.metric == "max_drawdown")
        assert dd.dependence_delta_q95 > 0
        if len(report.dependence_changed) > 1:
            # deltas in the order the report lists the metrics (sorted by delta)
            deltas_in_listed_order = [
                next(c.dependence_delta_q95 for c in report.comparisons if c.metric == metric)
                for metric in report.dependence_changed
            ]
            assert deltas_in_listed_order == sorted(deltas_in_listed_order, reverse=True)
            assert report.dependence_changed[0] == "max_drawdown"

    def test_stability_classification(self):
        report = _report()
        for metric in report.stable_metrics:
            comp = next(c for c in report.comparisons if c.metric == metric)
            spread = max(comp.percentiles.values()) - min(comp.percentiles.values())
            assert spread <= report.resampling_config["stability_tolerance"]

    def test_tolerance_parameters_recorded(self):
        d = _report(stability_tolerance=0.3, dependence_tolerance=0.01).to_dict()
        assert d["resampling_config"]["stability_tolerance"] == 0.3
        assert d["resampling_config"]["dependence_tolerance"] == 0.01


class TestScopeAndGuards:
    def test_scope_statement_describes_stream_not_strategy(self):
        d = _report().to_dict()
        scope = d["stream_scope"]
        assert scope["stream_id"] == "TS-R4-D1-0001-000001" or "TS-" in scope["stream_id"]
        assert "NOT a claim" in scope["scope_statement"]
        assert scope["n_trades"] == len(CLUSTERED)
        assert scope["period"]["first_entry"] == CLUSTERED[0] or "2026-01-01" in str(scope["period"])

    def test_stream_scope_carries_provenance(self):
        d = _report().to_dict()
        assert len(d["stream_scope"]["provenance_hash"]) == 64

    def test_tampered_stream_refused(self):
        s = _stream_with_pnls(CLUSTERED)
        b1, b2, b3 = _build_all(s)
        tampered = TradeStream(
            stream_id=s.stream_id,
            experiment_id=s.experiment_id,
            strategy_id=s.strategy_id,
            strategy_version=s.strategy_version,
            dataset_id=s.dataset_id,
            dataset_version=s.dataset_version,
            git_commit=s.git_commit,
            cost_model_id=s.cost_model_id,
            cost_model_version=s.cost_model_version,
            trades=tuple(
                TradeRecord(
                    trade_index=t.trade_index,
                    instrument=t.instrument,
                    entry_timestamp=t.entry_timestamp,
                    exit_timestamp=t.exit_timestamp,
                    side=t.side,
                    realized_pnl=t.realized_pnl + 9.0,
                    return_r=t.return_r,
                    costs_paid=t.costs_paid,
                    metadata=t.metadata,
                )
                for t in s.trades
            ),
            provenance_hash=s.provenance_hash,
        )
        with pytest.raises(TradeStreamError, match="provenance"):
            build_evidence_report(stream=tampered, permutation=b1, bootstrap=b2, block_bootstrap=b3)

    def test_mismatched_diagnostics_refused(self):
        s = _stream_with_pnls(CLUSTERED)
        s_other = _stream_with_pnls([1.0, -1.0, 2.0, -2.0, 0.5, -0.5, 3.0, -3.0, 2.0, 2.0, -1.0, -1.0])
        b1, b2, _ = _build_all(s)
        _, _, b3_other = _build_all(s_other)
        with pytest.raises(TradeStreamError, match="disagree"):
            build_evidence_report(stream=s, permutation=b1, bootstrap=b2, block_bootstrap=b3_other)

    def test_methodological_rule_present(self):
        d = _report().to_dict()
        assert "does NOT produce a probability" in d["methodological_rule"]
        md = render_markdown(_report())
        assert "Methodological rule" in md


class TestMarkdownAuditability:
    def test_markdown_renders_comparison_table(self):
        md = render_markdown(_report())
        assert "| Metric |" in md
        assert "max_drawdown" in md
        assert "total_pnl" in md

    def test_markdown_shows_resampling_config(self):
        md = render_markdown(_report())
        assert "trade_sequence_permutation" in md
        assert "iid_bootstrap_with_replacement" in md
        assert "seed=42" in md
