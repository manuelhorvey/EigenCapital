"""Hardened-governance rerun of Campaign 7 — governance tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday import campaign7_rerun_hardened as hr
from eigencapital.research.intraday.campaign4_15m import Verdict
from eigencapital.research.intraday.campaign8_tf003_confirmation import (
    COST_ONE_WAY_ADVERSE,
    COST_ONE_WAY_BASE,
    bt_corrected,
)


# ── Governance math ─────────────────────────────────────────────────────

class TestGovernanceMath:
    def test_family_size_is_72(self):
        assert hr.FAMILY_SIZE == 72

    def test_cumulative_trials(self):
        assert hr.CUMULATIVE_TRIALS == hr.PRIOR_EVALUATIONS + 72
        assert hr.CUMULATIVE_TRIALS >= 200

    def test_family_adjust_bonferroni(self):
        # linear scaling below the cap, capped at 1 above it
        assert hr.family_adjust(0.0005) == pytest.approx(0.0005 * 72)
        assert hr.family_adjust(0.001) == pytest.approx(0.072)
        assert hr.family_adjust(0.03) == 1.0   # capped at 1
        assert hr.family_adjust(0.5) == 1.0
        assert hr.family_adjust(1.0) == 1.0

    def test_cumulative_adjust_harder_than_family(self):
        for p in [0.01, 0.03, 0.1]:
            assert hr.cumulative_adjust(p) >= hr.family_adjust(p)

    def test_tf003_raw_p_fails_family_gate(self):
        # The exact numbers from the discovery run
        assert hr.family_adjust(0.03) > 0.05, (
            "TF-003 raw p=0.03 must fail the pre-registered family gate"
        )

    def test_cumulative_downgrade_threshold_registered(self):
        # 0.05 aligns with the family gate alpha; anything above
        # 205 * 0.05 / 72 ≈ 0.1424 is unreachable and would be dead code
        assert hr.CUMULATIVE_DOWNGRADE == 0.05


class TestDowngradeRule:
    def _result(self, verdict=Verdict.SUPPORTED, p_raw=0.0005):
        r = hr.HypResult(
            hid="X", family="f", description="d", hp=1,
            gross_sharpe=1.5, net_base=1.2, net_adverse=0.9, max_dd=-0.15,
            trades=50000, wf_consistency=0.9, wf_oos_sharpe=1.0,
            degradation=0.1, permutation_p=p_raw,
        )
        return r

    def test_strong_signal_survives_both_gates(self):
        # p_raw small enough to pass even cumulative correction
        p_raw = 0.05 / hr.CUMULATIVE_TRIALS / 2
        assert hr.family_adjust(p_raw) <= 0.05
        assert hr.cumulative_adjust(p_raw) <= hr.CUMULATIVE_DOWNGRADE

    def test_passes_family_but_not_cumulative_would_be_downgraded(self):
        # find a p that passes family but fails cumulative
        p = 0.02 / 72          # p_fam ≈ 0.02 ≤ 0.05
        assert hr.family_adjust(p) <= 0.05
        assert hr.cumulative_adjust(p) > hr.CUMULATIVE_DOWNGRADE


# ── Corrected engine drives verdicts ────────────────────────────────────

class TestCorrectedVerdictIntegration:
    @pytest.fixture
    def micro_df(self):
        rng = np.random.default_rng(21)
        times = pd.date_range("2026-06-01", periods=288 * 6, freq="5min")
        n = len(times)
        ret = rng.normal(0, 3e-4, n)
        close = 1.1000 * np.exp(np.cumsum(ret))
        flow = rng.normal(0, 0.25, n).clip(-1, 1)
        return pd.DataFrame({
            "time": times,
            "n_ticks": rng.integers(20, 400, n).astype(float),
            "up_frac": (0.5 + flow / 2), "dn_frac": (0.5 - flow / 2),
            "signed_flow": flow,
            "spread_mean_bps": np.abs(rng.normal(0.8, 0.2, n)),
            "spread_max_bps": np.abs(rng.normal(1.4, 0.4, n)),
            "mid_open": close, "mid_high": close,
            "mid_low": close, "mid_close": close, "mid_ret": ret,
        })

    def test_corrected_net_le_gross_under_costs(self, micro_df):
        from eigencapital.research.intraday.campaign7_micro import SIGNALS
        sig = SIGNALS["sig_flow_fade"](micro_df)
        r = bt_corrected(micro_df, sig, hp=1, cost_one_way=COST_ONE_WAY_BASE)
        assert r.net_sharpe <= r.gross_sharpe + 1e-9
        assert r.total_cost_drag > 0
        assert r.n_flips > 0

    def test_adverse_cost_worse_than_base(self, micro_df):
        from eigencapital.research.intraday.campaign7_micro import SIGNALS
        sig = SIGNALS["sig_flow_fade"](micro_df)
        rb = bt_corrected(micro_df, sig, 1, COST_ONE_WAY_BASE)
        ra = bt_corrected(micro_df, sig, 1, COST_ONE_WAY_ADVERSE)
        assert ra.total_net_ret < rb.total_net_ret


# ── Fail-closed on missing data ─────────────────────────────────────────

class TestFailClosed:
    def test_run_empty_dir_returns_empty(self, tmp_path):
        assert hr.run(data_dir=str(tmp_path)) == []


# ── Reports smoke ───────────────────────────────────────────────────────

class TestReports:
    def test_write_reports_smoke(self, tmp_path, monkeypatch):
        monkeypatch.setattr(hr, "REPORT_MD", str(tmp_path / "rr.md"))
        monkeypatch.setattr(hr, "REPORT_JSON", str(tmp_path / "rr.json"))
        r = hr.HypResult(
            hid="TF-003", family="tick_flow", description="d", hp=1,
            gross_sharpe=1.6, net_base=0.4, net_adverse=-0.1, max_dd=-0.34,
            trades=300000, wf_consistency=1.0, wf_oos_sharpe=1.5,
            degradation=0.75, verdict=Verdict.REJECTED,
            reasons=["permutation_insignificant"],
            permutation_p=0.03, primary_failure="permutation_insignificant",
        )
        object.__setattr__(r, "_governance", {
            "p_raw": 0.03, "p_adj_family": 1.0,
            "p_adj_cumulative": 1.0, "eval_count": 72,
        })
        hr.write_reports([r])
        md = (tmp_path / "rr.md").read_text()
        assert "HARDENED GOVERNANCE" in md
        assert "TF-003 DISPOSITION" in md
        js = (tmp_path / "rr.json").read_text()
        assert "governance" in js
