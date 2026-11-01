"""Production-function fidelity test for the frozen R4 signal (EC-AUDIT-001).

This test exercises the *actual* production implementation,
``scripts/r4_rebalance_loop.py::compute_r4_signal``, imported read-only the
same way the immutability and single-instance tests import it. No broker is
contacted and no production state is touched.

The expected weights are an independently calculated golden vector, derived
from a deliberately constructed return series rather than from the function
under test. For a return series ``r_t = m + a * (-1)^t``:

* the trailing 60-day sample standard deviation of the alternating component
  is exactly ``a * sqrt(60 / 59)``;
* annualised with ``sqrt(252)`` it becomes ``a * sqrt(60 / 59) * sqrt(252)``;
* the frozen damping factor is ``min(vol60 / 0.50, 1.0)``;
* cross-sectional rank-centred weights are ``rank_pct - 0.5``.

With six symbols the raw weights are ``-1/3, -1/6, 0, 1/6, 1/3, 1/2``. The
synthetic amplitudes below make each damping factor analytically known, so
the final weight for every symbol can be computed by hand.

If the production divisor changes from ``0.50`` to ``0.10`` (or any other
value), the 60-day window changes, the annualisation changes, the damping cap
changes, or the clip ordering changes, these assertions fail.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]

# (mean daily return, alternating amplitude) per symbol. Means are spaced far
# enough apart that the 12-1 momentum ordering is unambiguous; amplitudes are
# chosen so every 60-day damping factor is analytically known.
SPECS = {
    "CCC": (-0.006, 0.005),
    "BBB": (-0.002, 0.02),
    "EEE": (0.002, 0.01),
    "DDD": (0.006, 0.05),
    "AAA": (0.010, 0.03),
    "BTCUSD": (0.014, 0.06),
}

# Independently calculated expected final weights (forced regime, divisor 0.50).
# Derivation: vol60 = a * sqrt(60/59) * sqrt(252); scale = min(vol60/0.50, 1);
# raw weight = rank_pct - 0.5; clip to +/-0.20; BTCUSD additionally +/-0.10.
GOLDEN_WEIGHTS = {
    "CCC": -0.053361574443776,  # -1/3 * 0.1600847233
    "BBB": -0.106723148887552,  # -1/6 * 0.6403388933
    "EEE": 0.0,  # 0 * scale
    "DDD": 0.166666666666667,  # 1/6 * 1.0 (damping cap active)
    "AAA": 0.200000000000000,  # 1/3 * 0.9605083400 -> clipped at +0.20
    "BTCUSD": 0.100000000000000,  # 1/2 * 1.0 -> +0.20 clip -> BTC +0.10 clip
}

GOLDEN_DIAG = {
    "regime_on": True,
    "active_positions": 5,
    "long_count": 3,
    "short_count": 2,
}


def _load_loop_module():
    spec = importlib.util.spec_from_file_location(
        "r4_rebalance_loop_fidelity", REPO / "scripts" / "r4_rebalance_loop.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop_fidelity"] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_data(n: int = 301) -> dict[str, pd.DataFrame]:
    """Construct closes whose pct_change reproduces the intended returns exactly."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    data: dict[str, pd.DataFrame] = {}
    for sym, (mean, amp) in SPECS.items():
        returns = np.empty(n)
        returns[0] = 0.0
        for t in range(1, n):
            returns[t] = mean + amp * ((-1.0) ** t)
        close = np.empty(n)
        close[0] = 100.0
        for t in range(1, n):
            close[t] = close[t - 1] * (1.0 + returns[t])
        data[sym] = pd.DataFrame({"close": close}, index=idx)
    return data


def _independent_expected(divisor: float = 0.50) -> dict[str, float]:
    """Recompute the frozen pipeline analytically (not via the function under test)."""
    n = len(SPECS)
    annual_factor = np.sqrt(60.0 / 59.0) * np.sqrt(252.0)
    order = sorted(SPECS, key=lambda sym: SPECS[sym][0])  # ascending momentum
    out: dict[str, float] = {}
    for i, sym in enumerate(order):
        rank_pct = (i + 1) / n
        raw_weight = rank_pct - 0.5
        vol60 = SPECS[sym][1] * annual_factor
        damping = min(vol60 / divisor, 1.0)
        final = raw_weight * damping
        final = max(-0.20, min(0.20, final))
        if sym == "BTCUSD":
            final = max(-0.10, min(0.10, final))
        out[sym] = final
    return out


class TestFrozenConstants:
    def test_frozen_signal_constants(self):
        loop = _load_loop_module()
        assert loop.LOOKBACK == 252
        assert loop.SKIP == 21
        assert loop.RISK_LOOKBACK == 20
        assert loop.VOL_LOOKBACK == 60

    def test_vol_target_is_separate_and_unconsumed_by_signal(self):
        # The 0.10 annual target is a separate concept; it is not the divisor.
        loop = _load_loop_module()
        assert pytest.approx(0.10) == loop.VOL_TARGET
        latest, _, _ = loop.compute_r4_signal(_build_data(), force_regime=True)
        # Actual weights match the 0.50 divisor, not the 0.10 target.
        expected_050 = _independent_expected(divisor=0.50)
        for sym, value in expected_050.items():
            assert float(latest[sym]) == pytest.approx(value, abs=1e-9)


class TestGoldenVector:
    def test_forced_regime_golden_weights(self):
        loop = _load_loop_module()
        latest, diag, _ = loop.compute_r4_signal(_build_data(), force_regime=True)

        for key, value in GOLDEN_DIAG.items():
            assert diag[key] == value

        for sym, expected in GOLDEN_WEIGHTS.items():
            assert float(latest[sym]) == pytest.approx(expected, abs=1e-9), sym

    def test_matches_independent_formula(self):
        loop = _load_loop_module()
        latest, _, _ = loop.compute_r4_signal(_build_data(), force_regime=True)
        expected = _independent_expected(divisor=0.50)
        for sym, value in expected.items():
            assert float(latest[sym]) == pytest.approx(value, abs=1e-9), sym

    def test_divisor_is_fifty_percent_not_ten_percent(self):
        """Pin the divisor: a 0.10 implementation cannot satisfy this test."""
        loop = _load_loop_module()
        latest, _, _ = loop.compute_r4_signal(_build_data(), force_regime=True)

        expected_050 = _independent_expected(divisor=0.50)
        expected_010 = _independent_expected(divisor=0.10)

        # Matches the frozen 0.50 divisor.
        for sym, value in expected_050.items():
            assert float(latest[sym]) == pytest.approx(value, abs=1e-9), sym

        # And is demonstrably different from the unwired 0.10 target.
        for sym in ("CCC", "BBB"):
            assert abs(float(latest[sym]) - expected_010[sym]) > 1e-3, sym

    def test_damping_cap_and_clip_bounds(self):
        loop = _load_loop_module()
        latest, _, _ = loop.compute_r4_signal(_build_data(), force_regime=True)

        # Portfolio clip +/-0.20 is active on the highest raw weight.
        assert float(latest["AAA"]) == pytest.approx(0.20, abs=1e-12)
        # Damping cap of 1.0 is active: DDD would be ~0.267 (then clipped) without it.
        assert float(latest["DDD"]) == pytest.approx(1.0 / 6.0, abs=1e-12)
        assert float(latest["DDD"]) < 0.20
        # BTC-specific clip +/-0.10 is tighter than the portfolio clip.
        assert float(latest["BTCUSD"]) == pytest.approx(0.10, abs=1e-12)
        # Every weight respects the portfolio bound.
        assert all(abs(float(v)) <= 0.20 + 1e-12 for v in latest.values)

    def test_long_short_symmetry(self):
        loop = _load_loop_module()
        latest, diag, _ = loop.compute_r4_signal(_build_data(), force_regime=True)

        assert float(latest["CCC"]) < 0
        assert float(latest["BBB"]) < 0
        assert float(latest["DDD"]) > 0
        assert float(latest["AAA"]) > 0
        assert float(latest["BTCUSD"]) > 0
        assert diag["long_count"] == 3
        assert diag["short_count"] == 2

    def test_deterministic_output(self):
        loop = _load_loop_module()
        data = _build_data()
        first, diag_first, returns_first = loop.compute_r4_signal(data, force_regime=True)
        second, diag_second, returns_second = loop.compute_r4_signal(data, force_regime=True)
        assert diag_first == diag_second
        assert np.array_equal(first.values, second.values)
        assert np.array_equal(returns_first.values, returns_second.values)


class TestRegimeGating:
    def test_natural_regime_predicate(self):
        loop = _load_loop_module()
        latest, diag, returns_df = loop.compute_r4_signal(_build_data(), force_regime=False)

        avg_vol = returns_df.rolling(loop.RISK_LOOKBACK).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()
        expected_on = bool(avg_vol.iloc[-1] < risk_median.iloc[-1])

        assert diag["regime_on"] is expected_on

    def test_regime_off_gates_all_positions(self):
        # Stationary alternating vol sits at the expanding median, so the strict
        # "<" predicate is false and the regime filter gates the last row to zero.
        loop = _load_loop_module()
        latest, diag, _ = loop.compute_r4_signal(_build_data(), force_regime=False)
        assert diag["regime_on"] is False
        assert np.allclose(latest.values, 0.0, atol=1e-12)

    def test_force_regime_bypasses_filter(self):
        loop = _load_loop_module()
        latest, diag, _ = loop.compute_r4_signal(_build_data(), force_regime=True)
        assert diag["regime_on"] is True
        assert np.any(np.abs(latest.values) > 1e-6)
