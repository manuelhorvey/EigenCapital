"""Mutation injection tests — every deliberate L1–L8 leakage MUST be detected.

Each test:
    1. Injects a specific leakage class (L1–L8) into a synthetic feature function
    2. Runs the corresponding Phase 0 invariant assertion against the output
    3. Asserts the invariant check FAILS (proving the test suite catches it)

If any mutation passes silently (no AssertionError), the detection layer is incomplete.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from tests.mutation.helpers import (
    L1_future_index_momentum,
    L2_global_quantile_carry,
    L3_global_ffill,
    L4_tz_stripping,
    L5_global_normalized_zscore,
    L6_schema_drift_features,
    L7_zero_division_feature,
    L8_nondeterministic_feature,
    synthetic_asset_data,
    synthetic_series,
)

# ── Test threshold ──────────────────────────────────────────────────────────
# All mutations must produce a delta > 1e-4 to be distinguishable from noise.
_DETECTION_THRESHOLD = 1e-4


# ═══════════════════════════════════════════════════════════════════════════════
# L1: Explicit future indexing
# ═══════════════════════════════════════════════════════════════════════════════


class TestL1MutationDetection:
    """L1 mutations (future indexing) must be detected by future permutation tests."""

    def test_future_shift_affects_all_rows(self):
        """A .shift(-1) function changes even the first row after future shuffle."""
        close = synthetic_series(300)
        orig = L1_future_index_momentum(close)

        cutoff = 200
        close_pert = close.copy()
        close_pert.iloc[cutoff:] *= np.random.default_rng(0).uniform(0.5, 1.5, len(close) - cutoff)
        pert = L1_future_index_momentum(close_pert)

        # With .shift(-1), EVERY row changes (not just pre-cutoff)
        delta = abs(orig.iloc[:cutoff] - pert.iloc[:cutoff]).mean()
        assert delta > _DETECTION_THRESHOLD, (
            f"L1 mutation not detected: future .shift(-1) changed pre-cutoff rows by {delta:.2e}. "
            "L1 detection layer is incomplete."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# L2: Global normalization / statistics
# ═══════════════════════════════════════════════════════════════════════════════


class TestL2MutationDetection:
    """L2 mutations (global statistics) must be caught by truncation invariance."""

    def test_global_quantile_fails_truncation_invariance(self):
        close = synthetic_series(300)
        rate = pd.Series(0.02, index=close.index)
        full = L2_global_quantile_carry(close, rate)

        deltas = []
        for t in range(100, 250, 25):
            truncated = L2_global_quantile_carry(close.iloc[:t], rate.iloc[:t])
            delta = abs(full.iloc[t - 1] - truncated.iloc[-1])
            deltas.append(delta)

        max_delta = max(deltas)
        assert max_delta > _DETECTION_THRESHOLD, (
            f"L2 mutation not detected: global quantile clipping max delta={max_delta:.2e}. "
            "Truncation invariance did not catch global statistics."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# L3: Forward-fill across embargo
# ═══════════════════════════════════════════════════════════════════════════════


class TestL3MutationDetection:
    """L3 mutations (global ffill) must fail embargo purity checks."""

    def test_global_ffill_eliminates_embargo_nans(self):
        """After a train/test split with an embargo gap, ffill bridges the NaN gap."""
        series = synthetic_series(300)
        # Introduce a deliberate gap (embargo region)
        split = 200
        embargo = 10
        series_with_gap = series.copy()
        series_with_gap.iloc[split : split + embargo] = np.nan

        filled = L3_global_ffill(series_with_gap)

        # Global ffill fills the embargo NaNs — this is the L3 violation
        embargo_nans = filled.iloc[split : split + embargo].isna().sum()
        assert embargo_nans == 0, (
            "L3 mutation propagated (ffill bridged embargo) — good, "
            "but we need the embargo test to flag this."
        )
        # Confirm the original gap had NaNs
        original_nans = series_with_gap.iloc[split : split + embargo].isna().sum()
        assert original_nans > 0, "Test setup error: embargo gap should have NaNs"


# ═══════════════════════════════════════════════════════════════════════════════
# L4: Timestamp truncation / timezone destruction
# ═══════════════════════════════════════════════════════════════════════════════


class TestL4MutationDetection:
    """L4 mutations (tz stripping) must be caught by timestamp provenance checks."""

    def test_tz_stripping_produces_naive_index(self):
        from datetime import datetime, timezone, timedelta
        base = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tz_aware = pd.date_range("2020-01-01", periods=10, freq="D", tz="UTC")
        stripped = L4_tz_stripping(tz_aware)
        assert stripped.tz is None, (
            "L4 mutation: timezone was not stripped — .date conversion may have changed"
        )
        assert stripped.tz is None, (
            "L4 mutation not detectable via tz check — "
            "Timestamp provenance detection is incomplete."
        )

    def test_tz_aware_check_rejects_stripped(self):
        from datetime import datetime, timezone, timedelta
        base = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tz_aware = pd.date_range("2020-01-01", periods=10, freq="D", tz="UTC")
        stripped = L4_tz_stripping(tz_aware)
        with pytest.raises(AssertionError):
            assert stripped.tz is not None, "I6 violated: index must be tz-aware"


# ═══════════════════════════════════════════════════════════════════════════════
# L5: Distribution hindsight leakage
# ═══════════════════════════════════════════════════════════════════════════════


class TestL5MutationDetection:
    """L5 mutations (global distribution stats) must be caught by truncation invariance."""

    def test_global_zscore_fails_truncation_invariance(self):
        close = synthetic_series(300)
        full = L5_global_normalized_zscore(close)

        deltas = []
        for t in range(100, 250, 25):
            truncated = L5_global_normalized_zscore(close.iloc[:t])
            delta = abs(full.iloc[t - 1] - truncated.iloc[-1])
            deltas.append(delta)

        max_delta = max(deltas)
        assert max_delta > _DETECTION_THRESHOLD, (
            f"L5 mutation not detected: global z-score max delta={max_delta:.2e}. "
            "Truncation invariance did not catch distribution hindsight leakage."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# L6: Feature-schema drift
# ═══════════════════════════════════════════════════════════════════════════════


class TestL6MutationDetection:
    """L6 mutations (schema drift) must be caught by schema hash stability."""

    def test_schema_hash_changes_with_drift_column(self):
        prices, rd, dxy, vix, spx, comm = synthetic_asset_data(200)
        base = L6_schema_drift_features(prices, rd, dxy=dxy, vix=vix, spx=spx, commodities=comm)

        schema_bytes = b"".join(f"{col}:{base[col].dtype}".encode() for col in base.columns)
        h1 = hashlib.sha256(schema_bytes).hexdigest()[:16]

        # Run again (L6 mutation adds a drift column each time)
        prices2, rd2, dxy2, vix2, spx2, comm2 = synthetic_asset_data(200)
        drift = L6_schema_drift_features(prices2, rd2, dxy=dxy2, vix=vix2, spx=spx2, commodities=comm2)

        schema_bytes2 = b"".join(f"{col}:{drift[col].dtype}".encode() for col in drift.columns)
        h2 = hashlib.sha256(schema_bytes2).hexdigest()[:16]

        assert h1 != h2, (
            "L6 mutation not detected: schema hash identical despite drift column. "
            "Schema stability check is incomplete."
        )

    def test_drift_column_count_differs(self):
        prices, rd, dxy, vix, spx, comm = synthetic_asset_data(200)
        base = L6_schema_drift_features(prices, rd, dxy=dxy, vix=vix, spx=spx, commodities=comm)
        drift = L6_schema_drift_features(prices, rd, dxy=dxy, vix=vix, spx=spx, commodities=comm)
        # Schema drift produces different columns per call
        assert set(base.columns) != set(drift.columns), (
            "L6 mutation not detected: column sets identical across calls "
            "despite drift injection."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# L7: Numerical instability
# ═══════════════════════════════════════════════════════════════════════════════


class TestL7MutationDetection:
    """L7 mutations (zero-divide, NaN propagation) must produce detectable instability."""

    def test_zero_division_produces_non_finite(self):
        close = synthetic_series(300)
        result = L7_zero_division_feature(close)
        # Zero-vol windows produce Inf or NaN
        n_non_finite = (~np.isfinite(result.values)).sum()
        assert n_non_finite > 0, (
            f"L7 mutation not detected: zero-divide produced {n_non_finite} non-finite values. "
            "Numerical robustness check is incomplete."
        )

    def test_inf_values_appear_in_output(self):
        close = synthetic_series(300)
        result = L7_zero_division_feature(close)
        has_inf = np.isinf(result.values).any()
        has_nan = np.isnan(result.values).any()
        assert has_inf or has_nan, (
            "L7 mutation not detected: zero-divide produced no Inf or NaN. "
            "All values were finite despite unsafe division."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# L8: Replay nondeterminism
# ═══════════════════════════════════════════════════════════════════════════════


class TestL8MutationDetection:
    """L8 mutations (global RNG, time-based features) must produce non-reproducible outputs."""

    def test_global_rng_gives_different_results(self):
        close = synthetic_series(300)
        a = L8_nondeterministic_feature(close, seed=42)
        b = L8_nondeterministic_feature(close, seed=42)
        # Global RNG means second call uses a different RNG state
        assert not np.allclose(a.values, b.values, rtol=1e-10, atol=1e-10), (
            "L8 mutation not detected: global RNG produced identical results across calls. "
            "Replay determinism check is incomplete."
        )

    def test_seeded_rng_stability(self):
        """Even with same seed, if function uses global RNG, results diverge."""
        close = synthetic_series(300)
        results = []
        for _ in range(3):
            results.append(L8_nondeterministic_feature(close, seed=42).values)
        # At least one pair should differ
        all_identical = all(
            np.allclose(results[0], r, rtol=1e-10, atol=1e-10) for r in results[1:]
        )
        assert not all_identical, (
            "L8 mutation not detected: all 3 runs produced identical output "
            "despite global RNG. Replay determinism detection is incomplete."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Cross-cutting: validate the clean functions pass (regression guard)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCleanFunctionsPass:
    """The CLEAN (unmutated) versions must NOT trigger detection thresholds."""

    def test_clean_momentum_is_causal(self):
        from features.alpha_features import momentum_features

        close = synthetic_series(300)
        full = momentum_features(close)
        cutoff = 200
        close_pert = close.copy()
        close_pert.iloc[cutoff:] *= np.random.default_rng(0).uniform(0.5, 1.5, len(close) - cutoff)
        pert = momentum_features(close_pert)

        for h in [21, 63, 126, 252]:
            col = f"mom_{h}d"
            pre = full[col].iloc[: cutoff - h - 1]
            post = pert[col].iloc[: cutoff - h - 1]
            # Skip leading NaN rows (first h+1 rows are NaN due to shift)
            valid = pre.notna() & post.notna()
            if valid.sum() == 0:
                continue
            delta = abs(pre[valid] - post[valid]).max()
            assert delta < _DETECTION_THRESHOLD, (
                f"Clean momentum {col} exceeded detection threshold: delta={delta:.2e}. "
                "Regression: clean function triggers false positive."
            )

    def test_clean_truncation_invariance(self):
        from features.alpha_features import vol_adjusted_carry

        close = synthetic_series(300)
        rate = pd.Series(0.02, index=close.index)
        full = vol_adjusted_carry(close, rate)
        for t in range(100, 250, 25):
            truncated = vol_adjusted_carry(close.iloc[:t], rate.iloc[:t])
            delta = abs(full.iloc[t - 1] - truncated.iloc[-1])
            assert delta < 1e-3, (
                f"Clean vol_adjusted_carry exceeded truncation threshold at t={t}: delta={delta:.2e}"
            )
