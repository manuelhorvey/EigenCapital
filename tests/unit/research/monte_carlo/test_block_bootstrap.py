"""Unit tests for R1 Phase B3 — moving-block bootstrap diagnostic.

Covers the frozen B3 contract:
- resampler correctness: block contiguity, exact output length, truncation
- clustering preservation: block resample retains within-block adjacency
  that IID bootstrap (B2) destroys
- block_length is REQUIRED and pre-specified (no default, no search)
- contract boundary: set_invariance_expected=False, total P&L varies
- block metadata recorded (block_length, block_method, n_blocks_per_resample)
- validation, determinism, provenance refusal, historical-vs-simulated labeling
"""

import numpy as np
import pytest

from eigencapital.research.monte_carlo.block_bootstrap import (
    moving_block_sample,
    run_block_bootstrap_test,
)
from eigencapital.research.monte_carlo.bootstrap import run_bootstrap_test
from tests.unit.research.monte_carlo.test_permutation import _stream_with_pnls

CLUSTERED = [2.0, 2.0, 2.0, 2.0, -9.0, -9.0, -9.0, -9.0, 3.0, 3.0, 3.0, 3.0]


class TestMovingBlockSample:
    def test_output_length_exact(self):
        rng = np.random.default_rng(1)
        sample = moving_block_sample(CLUSTERED, block_length=4, sample_size=12, rng=rng)
        assert len(sample) == 12

    def test_truncation_to_sample_size(self):
        rng = np.random.default_rng(2)
        sample = moving_block_sample(CLUSTERED, block_length=4, sample_size=7, rng=rng)
        assert len(sample) == 7

    def test_blocks_are_contiguous_from_history(self):
        """Every output window of length L must appear in the historical sequence."""
        rng = np.random.default_rng(3)
        sample = moving_block_sample(CLUSTERED, block_length=4, sample_size=12, rng=rng)
        history = set(tuple(CLUSTERED[i : i + 4]) for i in range(len(CLUSTERED) - 3))
        for start in range(0, 12, 4):
            window = tuple(sample[start : start + 4])
            assert window in history

    def test_clustering_preserved_within_blocks(self):
        """A run of identical values survives intact inside a block (L=4)."""
        rng = np.random.default_rng(4)
        for _ in range(20):
            sample = moving_block_sample(CLUSTERED, block_length=4, sample_size=12, rng=rng)
            # some window must contain 4 consecutive identical values,
            # which IID resampling would make extremely unlikely
            has_run = any(len(set(sample[i : i + 4])) == 1 for i in range(len(sample) - 3))
            if has_run:
                break
        else:
            pytest.fail("block resampling never produced an intact within-block run")

    def test_block_length_one_reduces_to_iid(self):
        rng = np.random.default_rng(5)
        sample = moving_block_sample(CLUSTERED, block_length=1, sample_size=12, rng=rng)
        assert len(sample) == 12
        assert all(v in CLUSTERED for v in sample)

    def test_deterministic_given_same_rng_state(self):
        s1 = moving_block_sample(CLUSTERED, 4, 12, np.random.default_rng(42))
        s2 = moving_block_sample(CLUSTERED, 4, 12, np.random.default_rng(42))
        assert s1 == s2


class TestContractBoundary:
    def test_block_length_required(self):
        s = _stream_with_pnls(CLUSTERED)
        with pytest.raises(TypeError):
            run_block_bootstrap_test(s, n_resamples=10, seed=1)  # type: ignore[call-arg]

    def test_block_metadata_recorded(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=4, n_resamples=50, seed=1)
        assert result.block_length == 4
        assert result.block_method == "moving_block"
        assert result.n_blocks_per_resample == 3  # 12 trades / L=4
        d = result.to_dict()
        assert d["block_length"] == 4 and d["block_method"] == "moving_block"

    def test_set_invariance_expected_false(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=4, n_resamples=50, seed=1)
        assert result.set_invariance_expected is False
        assert len(set(result.distributions["total_pnl"])) > 1

    def test_sample_size_respected(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=3, n_resamples=20, seed=1, sample_size=17)
        assert result.sample_size == 17
        assert result.n_blocks_per_resample == 6  # ceil(17/3)

    def test_b3_shows_wider_dd_tail_than_b2_on_clustered_losses(self):
        """On loss-clustered data, preserving clusters must matter vs IID.

        With blocks of length 4 over CLUSTERED, a resample can draw multiple
        -9 blocks consecutively, producing drawdowns IID resampling rarely
        reaches. We compare tail quantiles, not eyeballed paths.
        """
        s = _stream_with_pnls(CLUSTERED)
        b2 = run_bootstrap_test(s, n_resamples=400, seed=31)
        b3 = run_block_bootstrap_test(s, block_length=4, n_resamples=400, seed=31)
        b2_q95 = b2.quantiles["max_drawdown"]["q0.95"]
        b3_q95 = b3.quantiles["max_drawdown"]["q0.95"]
        assert b3_q95 > b2_q95


class TestValidation:
    def test_block_length_bounds_enforced(self):
        s = _stream_with_pnls(CLUSTERED)
        with pytest.raises(Exception, match="block_length"):
            run_block_bootstrap_test(s, block_length=0, n_resamples=10, seed=1)
        with pytest.raises(Exception, match="block_length"):
            run_block_bootstrap_test(s, block_length=13, n_resamples=10, seed=1)

    def test_invalid_args_rejected(self):
        s = _stream_with_pnls(CLUSTERED)
        with pytest.raises(Exception, match="n_resamples"):
            run_block_bootstrap_test(s, block_length=4, n_resamples=0, seed=1)
        with pytest.raises(Exception, match="quantiles"):
            run_block_bootstrap_test(s, block_length=4, n_resamples=10, seed=1, quantiles=(1.5,))

    def test_tampered_stream_refused(self):
        from eigencapital.research.monte_carlo.schema import (
            TradeRecord,
            TradeStream,
            TradeStreamError,
        )

        s = _stream_with_pnls(CLUSTERED)
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
                    realized_pnl=t.realized_pnl + 1.0,
                    return_r=t.return_r,
                    costs_paid=t.costs_paid,
                    metadata=t.metadata,
                )
                for t in s.trades
            ),
            provenance_hash=s.provenance_hash,
        )
        with pytest.raises(TradeStreamError, match="provenance"):
            run_block_bootstrap_test(tampered, block_length=4, n_resamples=10, seed=1)


class TestBehaviorAndLabeling:
    def test_seed_determinism(self):
        s = _stream_with_pnls(CLUSTERED)
        r1 = run_block_bootstrap_test(s, block_length=4, n_resamples=100, seed=42)
        r2 = run_block_bootstrap_test(s, block_length=4, n_resamples=100, seed=42)
        assert r1.distributions == r2.distributions
        assert r1.quantiles == r2.quantiles
        assert r1.historical.percentile == r2.historical.percentile

    def test_percentiles_within_unit_interval(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=4, n_resamples=300, seed=11)
        for metric, pct in result.historical.percentile.items():
            assert 0.0 <= pct <= 1.0, metric

    def test_never_recovered_preserved(self):
        s = _stream_with_pnls([10.0, -20.0, 5.0, 8.0, 2.0, 1.0])
        result = run_block_bootstrap_test(s, block_length=2, n_resamples=300, seed=19)
        nones = sum(1 for v in result.distributions["recovery_time"] if v is None)
        if nones:
            assert result.quantiles["recovery_time"]["n_never_recovered"] == float(nones)

    def test_serialization_labels_historical_vs_simulated(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=4, n_resamples=50, seed=9)
        d = result.to_dict()
        assert d["method"] == "moving_block_bootstrap"
        assert "historical" in d and "simulated_distributions" in d
        assert "NOT a forecast" in d["methodological_rule"]
        assert "percentile_in_simulated_distribution" in d["historical"]

    def test_seed_recorded(self):
        s = _stream_with_pnls(CLUSTERED)
        result = run_block_bootstrap_test(s, block_length=4, n_resamples=10, seed=77)
        assert result.seed == 77
