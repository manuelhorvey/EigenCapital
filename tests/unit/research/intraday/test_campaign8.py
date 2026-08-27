"""Campaign 8 — TF-003 confirmation tests. Stage-A engine locks come FIRST."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.intraday import campaign8_tf003_confirmation as c8
from eigencapital.research.intraday.campaign7_micro import SIGNALS

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tiny_df() -> pd.DataFrame:
    """Hand-checkable 4-bar series: close [100,100,110,110]."""
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-06-01", periods=4, freq="5min"),
            "mid_close": [100.0, 100.0, 110.0, 110.0],
        }
    )


@pytest.fixture
def micro_df() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    times = pd.date_range("2026-06-01 00:00", periods=288 * 10, freq="5min")
    n = len(times)
    ret = rng.normal(0, 3e-4, n)
    close = 1.1000 * np.exp(np.cumsum(ret))
    flow = rng.normal(0, 0.25, n).clip(-1, 1)
    return pd.DataFrame(
        {
            "time": times,
            "n_ticks": rng.integers(20, 400, n).astype(float),
            "up_frac": (0.5 + flow / 2),
            "dn_frac": (0.5 - flow / 2),
            "signed_flow": flow,
            "spread_mean_bps": np.abs(rng.normal(0.8, 0.2, n)),
            "spread_max_bps": np.abs(rng.normal(1.4, 0.4, n)),
            "mid_open": close,
            "mid_high": close,
            "mid_low": close,
            "mid_close": close,
            "mid_ret": ret,
        }
    )


# ═══════════════════════════════════════════════════════════════════════
# STAGE A LOCKS — the corrected engine must satisfy these before any run
# ═══════════════════════════════════════════════════════════════════════


class TestStageAEngineLocks:
    def test_flip_accounting_hand_computed(self, tiny_df):
        """close=[100,100,110,110]; sig=[+1,-1,-1,-1]
        → pos=[0,+1,-1,-1]; fwd ret=[0,+10%,0,nan]
        → flips=[0,1,2,0] (3 flips); net total = 10% − 3c."""
        sig = pd.Series([1.0, -1.0, -1.0, -1.0], index=tiny_df.index)
        c = 0.001
        r = c8.bt_corrected(tiny_df, sig, hp=1, cost_one_way=c)
        assert r.n_flips == 3
        assert r.total_gross_ret == pytest.approx(0.10)
        assert r.total_net_ret == pytest.approx(0.10 - 3 * c)

    def test_zero_cost_equals_gross(self, tiny_df):
        sig = pd.Series([1.0, -1.0, -1.0, -1.0], index=tiny_df.index)
        r0 = c8.bt_corrected(tiny_df, sig, hp=1, cost_one_way=0.0)
        assert r0.total_net_ret == pytest.approx(r0.total_gross_ret)

    def test_costs_monotonically_reduce_net(self, micro_df):
        sig = SIGNALS["sig_flow_fade"](micro_df)
        nets = [c8.bt_corrected(micro_df, sig, hp=1, cost_one_way=c).net_sharpe for c in [0.0, 0.0001, 0.00065]]
        assert nets[0] >= nets[1] >= nets[2]

    def test_extreme_cost_makes_any_signal_negative_total(self, micro_df):
        sig = SIGNALS["sig_flow_fade"](micro_df)
        r = c8.bt_corrected(
            micro_df,
            sig,
            hp=1,
            cost_one_way=micro_df["mid_ret"].std() * 10,
        )
        assert r.total_net_ret < 0

    def test_perfect_foresight_survives_small_cost_only_if_edge_big(self, micro_df):
        foresight = np.sign(micro_df["mid_close"].shift(-1) - micro_df["mid_close"]).fillna(0)
        small = c8.bt_corrected(micro_df, foresight, 1, 0.000001)
        huge = c8.bt_corrected(micro_df, foresight, 1, 0.001)
        assert small.net_sharpe > 5.0
        # Realistic retail flip cost (10bps/flip): even FORESIGHT goes net-negative
        assert huge.total_net_ret < 0
        assert huge.net_sharpe < small.net_sharpe

    def test_dd_computed_on_net_series(self, tiny_df):
        sig = pd.Series([1.0, 1.0, 1.0, 1.0], index=tiny_df.index)
        r = c8.bt_corrected(tiny_df, sig, hp=1, cost_one_way=0.05)
        # entry cost drags the net path at or below its gross high-water mark
        assert r.max_dd <= 0.0
        assert r.worst_bar <= 0.0

    def test_exposure_metric(self, tiny_df):
        sig = pd.Series([0.0, 1.0, -1.0, -1.0], index=tiny_df.index)
        r = c8.bt_corrected(tiny_df, sig, hp=1, cost_one_way=0.0)
        # pos = [0, 0, +1, -1] → nonzero on 2 of 4 bars
        assert r.exposure == pytest.approx(0.5)

    def test_engine_locked_constants_match_conventions(self):
        assert pytest.approx(13 / 2 / 10000) == c8.COST_ONE_WAY_BASE
        assert pytest.approx(22 / 2 / 10000) == c8.COST_ONE_WAY_ADVERSE
        assert c8.PRIMARY_HID == "TF-003"
        assert c8.PRIMARY_HP == 1


# ═══════════════════════════════════════════════════════════════════════
# GATE LOGIC — fail-closed
# ═══════════════════════════════════════════════════════════════════════


def _mk_full(**over):
    base = dict(
        gross_sharpe=1.6,
        net_sharpe=1.0,
        total_gross_ret=0.5,
        total_net_ret=0.4,
        total_cost_drag=0.1,
        n_flips=10000,
        exposure=0.9,
        max_dd=-0.15,
        worst_bar=-0.002,
        avg_cost_per_flip_bps=6.5,
    )
    base.update(over)
    return c8.NetResult(**base)


class TestGates:
    def test_all_pass_no_failures(self):
        syms = {s: _mk_full(net_sharpe=0.8) for s in c8.UNIVERSE}
        sessions = {s: 1.0 for s in ["asian", "london", "overlap", "new_york", "off_hours"]}
        failed, passed = c8._gate_check(_mk_full(), 0.8, 0.02, syms, sessions)
        assert not failed and len(passed) >= 6

    def test_weak_sharpe_fails(self):
        failed, _ = c8._gate_check(
            _mk_full(net_sharpe=0.1),
            0.8,
            0.02,
            {s: _mk_full() for s in c8.UNIVERSE},
            {s: 1.0 for s in ["asian", "london", "overlap", "new_york", "off_hours"]},
        )
        assert any("net_sharpe" in g for g in failed)

    def test_dd_gate_enforced_on_corrected_result(self):
        failed, _ = c8._gate_check(
            _mk_full(max_dd=-0.34),
            0.8,
            0.02,
            {s: _mk_full() for s in c8.UNIVERSE},
            {s: 1.0 for s in ["asian", "london", "overlap", "new_york", "off_hours"]},
        )
        assert any("max_dd" in g for g in failed)

    def test_instrument_breadth_gate(self):
        syms = {s: _mk_full(net_sharpe=(0.8 if i < 4 else -0.5)) for i, s in enumerate(c8.UNIVERSE)}
        failed, _ = c8._gate_check(
            _mk_full(),
            0.8,
            0.02,
            syms,
            {s: 1.0 for s in ["asian", "london", "overlap", "new_york", "off_hours"]},
        )
        assert any("instruments positive" in g for g in failed)

    def test_session_floor_gate(self):
        sessions = {"asian": 1.0, "london": 1.2, "overlap": -0.9, "new_york": 1.0, "off_hours": 0.8}
        failed, _ = c8._gate_check(
            _mk_full(),
            0.8,
            0.02,
            {s: _mk_full() for s in c8.UNIVERSE},
            sessions,
        )
        assert any("sessions below floor" in g for g in failed)


class TestConfirmationVerdict:
    def test_run_fail_closed_without_data(self, tmp_path):
        rep = c8.run(data_dir=str(tmp_path))
        assert rep.verdict == "INCONCLUSIVE"


# ── Reports smoke ───────────────────────────────────────────────────────


class TestReports:
    def test_write_reports_smoke(self, tmp_path, monkeypatch):
        monkeypatch.setattr(c8, "REPORT_MD", str(tmp_path / "c8.md"))
        monkeypatch.setattr(c8, "REPORT_JSON", str(tmp_path / "c8.json"))
        rep = c8.ConfirmationReport(
            verdict="NOT_CONFIRMED",
            failed_gates=["max_dd -34.5% ≤ -25%"],
            passed_gates=["permutation p 0.030 ≤ 0.05"],
            full_window=_mk_full().__dict__ | {"anchor": "EURUSDm"},
            holdout=_mk_full().__dict__,
            per_instrument={s: _mk_full().__dict__ for s in list(c8.UNIVERSE)[:2]},
        )
        c8.write_reports(rep)
        md = (tmp_path / "c8.md").read_text()
        assert "CAMPAIGN 8" in md
        assert "NOT_CONFIRMED" in md
        assert "HONEST LIMITATIONS" in md
        js = (tmp_path / "c8.json").read_text()
        assert "verdict" in js
