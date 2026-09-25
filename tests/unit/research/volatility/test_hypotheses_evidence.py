"""Evidence accounting: Holm step-down math, fail-closed min cell,
verdict vocabulary enforcement on synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.volatility import evidence as E
from research.volatility import hypotheses as H

ALLOWED = {
    E.SUPPORTED,
    E.NOT_SUPPORTED,
    E.INCONCLUSIVE,
    E.STABLE,
    E.UNSTABLE,
    E.STRUCTURALLY_DISTINCT,
    E.STRUCTURALLY_REDUNDANT,
    E.INSUFFICIENT_DATA,
}


def test_spearman_fail_closed_below_min_cell():
    x = np.arange(5, dtype=float)
    y = np.arange(5, dtype=float)
    rho, p = E.spearman_with_p(x, y)
    assert np.isnan(rho) and np.isnan(p)


def test_spearman_perfect_negative():
    rng = np.random.default_rng(0)
    x = rng.uniform(size=50)
    y = -x
    rho, p = E.spearman_with_p(x, y)
    assert rho == pytest.approx(-1.0, abs=1e-12)
    assert p < 0.05


def test_holm_step_down_math():
    led = E.EvidenceLedger()
    # sorted p: 0.002, 0.01, 0.03, 0.04 ; m=4
    for name, p in [("d", 0.04), ("a", 0.002), ("b", 0.01), ("c", 0.03)]:
        led.record_test("fam", name, p, 0.0, E.INCONCLUSIVE)
    led.holm_correct("fam")
    t = led.hypothesis_tests["fam"]
    # Holm: p*(m-i), cumulative max
    assert t["a"]["p_holm"] == pytest.approx(0.008)
    assert t["b"]["p_holm"] == pytest.approx(0.03)
    assert t["c"]["p_holm"] == pytest.approx(0.06)  # max(0.06, 0.03)
    assert t["d"]["p_holm"] == pytest.approx(0.06)  # max(0.04, 0.06)
    # monotone in sorted order
    assert t["a"]["p_holm"] <= t["b"]["p_holm"] <= t["c"]["p_holm"]


def test_ledger_counts_and_total():
    led = E.EvidenceLedger()
    led.count("k1", 3)
    led.count("k1")
    led.count("k2", 2)
    assert led.comparisons == {"k1": 4, "k2": 2}
    assert led.total_comparisons == 6


def _strong_h1_frame(n: int = 120, seed: int = 1) -> pd.DataFrame:
    """Construct trades where low entry RV pctile => long underwater run."""
    rng = np.random.default_rng(seed)
    pct = rng.uniform(0.0, 1.0, n)
    # strictly decreasing relation + small noise (kept rank-stable)
    uw = np.round((1.0 - pct) * 20 + rng.normal(0, 0.2, n)).clip(0)
    cross = ((1.0 - pct) * 4 + rng.normal(0, 0.05, n)).clip(0)
    ttf = np.where(rng.uniform(0, 1, n) < 0.7, np.round((1.0 - pct) * 30), np.nan)
    tmfe = np.round((1.0 - pct) * 25 + rng.normal(0, 0.3, n)).clip(1)
    return pd.DataFrame(
        {
            "entry_rv_pctile": pct,
            "max_underwater_run": uw,
            "crossings_per_bar": cross / 10.0,
            "first_profit_bar": ttf,
            "time_to_mfe": tmfe,
            "mae_ret": (1.0 - pct) * 0.02,
            "mae_sigma": (1.0 - pct) * 1.0,
            "mfe_ret": pct * 0.03,
            "mfe_sigma": pct * 1.2,
            "underwater_fraction": (1.0 - pct),
            "max_underwater_run_net": uw + 1,
            "holding_bars": rng.integers(5, 30, n),
            "exit_u_ret": rng.normal(0, 0.01, n),
            "asset": rng.choice(["AUDUSD", "EURUSD"], n),
            "entry_ts": pd.date_range("2021-01-04", periods=n, freq="B").strftime("%Y-%m-%d"),
            "large_favorable": rng.random(n) > 0.5,
            "time_to_large_favorable": rng.integers(1, 20, n),
            "delayed_expansion": rng.random(n) > 0.7,
        }
    )


def test_h1_h4_synthetic_supported():
    frame = _strong_h1_frame()
    out = H.evaluate_h1_h4_pooled(frame)
    for hyp in ("H1_underwater", "H2_oscillation", "H4_time_to_mfe"):
        assert out[hyp]["rho"] < 0
        assert out[hyp]["verdict"] in ALLOWED
    # with a strong constructed effect, H1 must be SUPPORTED after Holm
    assert out["H1_underwater"]["verdict"] == E.SUPPORTED
    # verdicts carry adjusted p, never raw-only
    rec = E.LEDGER.hypothesis_tests["H1_H4_pooled_spearman"]["H1_underwater"]
    assert "p_holm" in rec


def test_h6_stable_on_constructed_sign_consistent_data():
    frame = _strong_h1_frame(n=150)
    out = H.evaluate_h6_periods(frame)
    assert out["verdict"] in {E.STABLE, E.UNSTABLE, E.INCONCLUSIVE}
    # constructed data has consistent negative signs across thirds
    assert out["verdict"] == E.STABLE


def test_h7_partial_rho_finite():
    frame = _strong_h1_frame()
    out = H.evaluate_h7_holding(frame)
    assert out["H1_underwater"]["partial_rho"] < 0


def test_falsification_battery_shapes_and_vocabulary():
    frame = _strong_h1_frame()
    h_within = H.evaluate_h_within_asset(frame)
    h5 = H.evaluate_h5_normalization(frame)
    h6 = H.evaluate_h6_periods(frame)
    h7 = H.evaluate_h7_holding(frame)
    bat = H.falsification_battery(
        frame,
        h_within,
        h5,
        h6,
        h7,
        alt_entry_vol_rhos={"H1_underwater": -0.4},
        alt_regime_rhos={"H1_underwater": -0.3},
    )
    expected = {
        "F1_within_asset",
        "F2_normalization",
        "F3_holding_period",
        "F4_strategy",
        "F5_costs",
        "F6_sessions",
        "F7_extremes",
        "F8_periods",
        "F9_estimator",
        "F10_regime_definition",
        "F11_large_move",
        "F12_cross_vs_within",
    }
    assert expected <= set(bat)
    for k in expected:
        assert bat[k]["result"] in {"survives", "fails", "inconclusive"}
    s = bat["_battery_summary"]
    assert s["n_checks"] == 12
    assert s["n_survives"] + s["n_fails"] + s["n_inconclusive"] == 12
    # F4 is declared structurally inconclusive (single strategy)
    assert bat["F4_strategy"]["result"] == "inconclusive"


def test_no_profit_never_coded_zero():
    frame = _strong_h1_frame()
    frame.loc[frame["first_profit_bar"].isna(), "first_profit_bar"] = np.nan
    out = H.evaluate_h1_h4_pooled(frame)
    # NaN excluded from ttf ranks — H3 n must be < total rows
    assert out["H3_time_to_first_profit"]["n"] < len(frame)
    assert out["H3_no_profit_rate_by_rv_quartile"]
