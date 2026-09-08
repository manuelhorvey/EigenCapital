"""Shadow selector tests (brief Section 18 — Selection and Risk)."""

from __future__ import annotations

import json

import pytest

from eigencapital.shadow.portfolio.selector import (
    HARD_CAP_REASONS,
    ShadowSelector,
    ShadowSelectorConfig,
)
from tests.unit.shadow.portfolio.helpers import make_candidate, make_returns, snapshot_for

DEFAULT_CFG = ShadowSelectorConfig()


def run_select(candidates, returns, baseline_symbols=None):
    snapshot = snapshot_for(returns)
    baseline = baseline_symbols if baseline_symbols is not None else [c.symbol for c in candidates]
    selector = ShadowSelector(DEFAULT_CFG)
    return selector.select(
        candidates,
        snapshot,
        baseline,
        cycle_id="TEST-CYCLE",
        decision_timestamp="2026-01-01T00:00:00+00:00",
        signal_date="2026-01-01",
    )


class TestSelectionLogic:
    def test_strongest_signal_correlated_with_another(self):
        """Strong signal must be retained; its correlated clone rejected;
        a weak uncorrelated diversifier may enter. The diversifier is a
        SHORT (offsets the LONG's USD leg) so the FX-exposure dimension
        does not confound the correlation test."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0},
            seed=21,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.05, rank=3),
        ]
        decision = run_select(candidates, returns)

        assert decision.status == "SELECTED"
        selected = decision.selected["symbols"]
        assert "AUDUSD" in selected  # strongest retained
        assert "EURUSD" in selected  # weak uncorrelated diversifier
        assert "AUDCHF" not in selected  # correlated clone rejected

        # Provenance: measurable rejection reason, not "less diversified".
        # AUDCHF is doubly redundant (correlated clone AND AUD-stacked), so the
        # currency hard cap or the correlation penalty may fire first — either
        # is a measurable reason.
        by_symbol = {c["symbol"]: c for c in decision.candidates}
        assert by_symbol["AUDCHF"]["rejection_reason"] in {
            "incremental_quality_non_positive",
            "no_positive_marginal_quality",
            "expected_edge_insufficient",
            "currency_concentration",
        }

        # Edge preservation: >50% of R4 gross edge retained, top signal kept.
        assert decision.edge_metrics["edge_retained_pct"] > 50.0
        assert decision.edge_metrics["top_signal_retention"] == "2/3"

    def test_all_candidates_highly_correlated(self):
        """Three identical-return high-edge candidates → 1 position."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "AUDNZD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "AUDNZD": 1.0},
            seed=22,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("AUDNZD", 0.18, rank=3),
        ]
        decision = run_select(candidates, returns)
        assert decision.status == "SELECTED"
        assert len(decision.selected["symbols"]) == 1
        assert decision.selected["symbols"] == ["AUDUSD"]

    def test_high_edge_cluster_vs_diversified(self):
        """High-edge correlated cluster must not crowd out diversification.
        Diversifiers are SHORT (FX-offsetting) so only correlation separates
        the cluster members from the diversifiers."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD", "GBPUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0},
            seed=23,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.12, rank=3),
            make_candidate("GBPUSD", -0.11, rank=4),
        ]
        decision = run_select(candidates, returns)
        selected = decision.selected["symbols"]
        # At most one member of the correlated cluster.
        assert len(set(selected) & {"AUDUSD", "AUDCHF"}) <= 1
        # Diversified names entered.
        assert "EURUSD" in selected

    def test_opposite_direction_anti_correlated_is_redundant(self):
        """LONG A + SHORT B with anti-correlated returns = the same bet.
        Direction-adjusted correlation must reject the clone even though the
        currency exposure offsets (no cap involvement)."""

        returns = make_returns(["AUDUSD", "GBPUSD"], n=300, seed=120)
        returns["GBPUSD"] = -returns["AUDUSD"].copy()  # ρ_returns = −1 exactly
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("GBPUSD", -0.19, rank=2),
        ]
        decision = run_select(candidates, returns)
        selected = decision.selected["symbols"]
        assert selected == ["AUDUSD"]
        by_symbol = {c["symbol"]: c for c in decision.candidates}
        assert by_symbol["GBPUSD"]["rejection_reason"] in {
            "incremental_quality_non_positive",
            "no_positive_marginal_quality",
            "expected_edge_insufficient",
        }
        assert by_symbol["GBPUSD"]["marginal_quality"] is not None

    def test_weak_uncorrelated_candidate_enters(self):
        """A weak uncorrelated SHORT offsets the LONG's USD leg and enters."""
        returns = make_returns(
            ["AUDUSD", "EURUSD"],
            factor_map={"AUDUSD": 1.0, "EURUSD": 0.0},
            seed=24,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("EURUSD", -0.05, rank=2),
        ]
        decision = run_select(candidates, returns)
        assert set(decision.selected["symbols"]) == {"AUDUSD", "EURUSD"}


class TestEmptyAndDegenerate:
    def test_no_candidates(self):
        decision = run_select([], make_returns(["AUDUSD"], n=100, seed=25))
        assert decision.status == "NO_CANDIDATES"

    def test_all_candidates_infeasible(self):
        returns = make_returns(["AUDUSD", "EURUSD"], seed=26)
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1, feasible=False),
            make_candidate("EURUSD", -0.19, rank=2, feasible=False),
        ]
        decision = run_select(candidates, returns)
        assert decision.status == "NO_CANDIDATES"

    def test_fewer_candidates_than_target_n(self):
        """1 candidate → SELECTED with 1 (never forced up to N)."""
        returns = make_returns(["AUDUSD"], n=100, seed=27)
        candidates = [make_candidate("AUDUSD", 0.20, rank=1)]
        decision = run_select(candidates, returns)
        assert decision.status == "SELECTED"
        assert decision.selected["symbols"] == ["AUDUSD"]

    def test_no_portfolio_when_edge_insufficient(self):
        """Weak signals must yield NO_PORTFOLIO, not a forced portfolio."""
        returns = make_returns(["AUDUSD", "EURUSD"], seed=28)
        candidates = [
            make_candidate("AUDUSD", 0.01, rank=1),
            make_candidate("EURUSD", -0.01, rank=2),
        ]
        decision = run_select(candidates, returns)
        assert decision.status == "NO_PORTFOLIO"
        assert "expected_edge_insufficient" in decision.status_reason
        assert decision.selected["symbols"] == []


class TestRiskControls:
    def test_currency_hard_cap(self):
        """Four AUD pairs (uncorrelated returns) → max one AUD leg."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "AUDNZD", "AUDCAD"],
            factor_map={},
            seed=29,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("AUDNZD", 0.18, rank=3),
            make_candidate("AUDCAD", 0.17, rank=4),
        ]
        decision = run_select(candidates, returns)
        aud_legs = [s for s in decision.selected["symbols"] if s.startswith("AUD")]
        assert len(aud_legs) <= 1
        rejected = {c["symbol"]: c["rejection_reason"] for c in decision.candidates}
        assert any(r == "currency_concentration" for r in rejected.values() if r)

    def test_risk_metrics_reported(self):
        returns = make_returns(
            ["AUDUSD", "EURUSD"],
            factor_map={"AUDUSD": 1.0, "EURUSD": 0.0},
            seed=30,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("EURUSD", -0.19, rank=2),
        ]
        decision = run_select(candidates, returns)
        assert set(decision.selected["symbols"]) == {"AUDUSD", "EURUSD"}
        m = decision.selected["metrics"]
        assert m["herfindahl"] > 0
        assert m["effective_positions"] > 0
        assert m["diversification_ratio"] > 0
        assert m["expected_drawdown_proxy"] > 0
        # Offsetting FX net edge should be small vs gross.
        assert abs(decision.selected["metrics"]["net_edge"]) < decision.selected["metrics"]["gross_edge"]

    def test_quality_by_n_curve(self):
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD", "GBPUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0},
            seed=31,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.12, rank=3),
            make_candidate("GBPUSD", -0.11, rank=4),
        ]
        decision = run_select(candidates, returns)
        q = decision.quality_by_n
        assert 0 in q and len(q) >= 3  # P_0, P_1, ... at least
        # Monotone non-decreasing up to the peak (greedy accepts only Δ>0).
        keys = sorted(q.keys())
        vals = [q[k] for k in keys]
        assert vals == sorted(vals)

    def test_insufficient_history_conservative(self):
        """Candidates without vol history use the documented conservative vol."""
        returns = make_returns(["AUDUSD", "EURUSD"], n=100, seed=32)
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1, vol=None, history_sufficient=False),
            make_candidate("EURUSD", -0.19, rank=2),
        ]
        decision = run_select(candidates, returns)
        assert decision.status == "SELECTED"


class TestDeterminism:
    def test_same_inputs_same_portfolio(self):
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD", "GBPUSD", "USDJPY", "NZDUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0},
            seed=33,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", 0.12, rank=3),
            make_candidate("GBPUSD", 0.11, rank=4),
            make_candidate("USDJPY", 0.10, rank=5),
            make_candidate("NZDUSD", -0.09, rank=6),
        ]
        d1 = run_select(candidates, returns)
        d2 = run_select(candidates, returns)
        assert d1.selected["symbols"] == d2.selected["symbols"]
        assert json.dumps(d1.to_dict(), sort_keys=True, default=str) == json.dumps(
            d2.to_dict(), sort_keys=True, default=str
        )

    def test_config_hash_deterministic_and_sensitive(self):
        h1 = ShadowSelectorConfig().config_hash()
        h2 = ShadowSelectorConfig().config_hash()
        assert h1 == h2
        h3 = ShadowSelectorConfig(lambda_correlation=0.9).config_hash()
        assert h3 != h1

    def test_selector_version_recorded(self):
        returns = make_returns(["AUDUSD", "EURUSD"], seed=34)
        candidates = [make_candidate("AUDUSD", 0.20, rank=1)]
        decision = run_select(candidates, returns)
        assert decision.selector_version.startswith("r4s-shadow-selector")
        assert len(decision.config_hash) == 64

    def test_regime_context_recorded(self):
        returns = make_returns(["AUDUSD", "EURUSD"], seed=35)
        candidates = [make_candidate("AUDUSD", 0.20, rank=1)]
        selector = ShadowSelector(DEFAULT_CFG)
        decision = selector.select(
            candidates,
            snapshot_for(returns),
            ["AUDUSD"],
            cycle_id="C",
            decision_timestamp="t",
            signal_date="d",
            regime={"regime_on": True, "vol_now": 0.05, "vol_median": 0.10, "vol_ratio": 0.5},
        )
        assert decision.regime["vol_ratio"] == 0.5
        assert decision.regime["regime_on"] is True


class TestDiagnosticEvidence:
    def test_chain_by_n_nested_and_consistent(self):
        """P_n must be a prefix of P_{n+1} and quality must match quality_by_n."""
        returns = make_returns(
            ["AUDUSD", "EURUSD", "GBPUSD"],
            factor_map={"AUDUSD": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0},
            seed=36,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("EURUSD", -0.12, rank=2),
            make_candidate("GBPUSD", -0.11, rank=3),
        ]
        decision = run_select(candidates, returns)
        chain = decision.chain_by_n
        keys = sorted(chain.keys())
        assert keys[0] == 0
        for n in keys[1:]:
            prev = set(chain[n - 1]["symbols"])
            cur = set(chain[n]["symbols"])
            assert prev <= cur, f"P_{n - 1} not a prefix of P_{n}"
            assert chain[n]["quality"] == pytest.approx(decision.quality_by_n[n], abs=1e-6)
            assert "metrics" in chain[n]
            assert chain[n]["metrics"]["gross_edge"] > 0

    def test_marginal_components_decompose_quality_delta(self):
        """For every evaluated candidate, component deltas must sum to Δquality."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0},
            seed=37,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.05, rank=3),
        ]
        decision = run_select(candidates, returns)
        checked = 0
        for c in decision.candidates:
            comps = c.get("marginal_components")
            if comps is None:
                continue
            rebuilt = (
                comps["edge_delta"]
                - comps["vol_penalty_delta"]
                - comps["corr_penalty_delta"]
                - comps["ccy_penalty_delta"]
                - comps["factor_penalty_delta"]
            )
            assert rebuilt == pytest.approx(comps["quality_delta"], abs=1e-8)
            if c.get("marginal_quality") is not None:
                assert comps["quality_delta"] == pytest.approx(c["marginal_quality"], abs=1e-8)
            checked += 1
        assert checked >= 2

    def test_dominant_rejection_classification(self):
        """Rejected candidates carry a measurable dominant reason; selected
        candidates carry none."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD", "GBPUSD"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0},
            seed=38,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.12, rank=3),
            make_candidate("GBPUSD", -0.11, rank=4),
        ]
        decision = run_select(candidates, returns)
        allowed = {
            "high_correlation",
            "volatility_penalty",
            "currency_concentration",
            "factor_concentration",
            "weak_edge",
            "portfolio_capacity",
            "asset_class_concentration",
        }
        for c in decision.candidates:
            if c["symbol"] in decision.selected["symbols"]:
                assert c["dominant_rejection"] is None
            else:
                assert c["dominant_rejection"] in allowed, c

    def test_rejection_reason_reflects_final_state_not_early_trial(self):
        """Regression (R4-S 2026-09-08): a candidate that tripped a hard cap
        in an EARLY greedy trial (e.g. {XAUUSD, AUDUSD} → 84% safe_haven) must
        not carry that label if the FINAL portfolio no longer violates. The
        recorded reason must match a recomputation against the final selected
        weights — otherwise lost-edge attribution mischarges the name."""
        returns = make_returns(
            ["XAUUSD", "USTEC", "AUDUSD", "EURUSD"],
            factor_map={"XAUUSD": 1.0, "USTEC": 1.0, "AUDUSD": 1.0, "EURUSD": 0.0},
            seed=401,
        )
        candidates = [
            make_candidate("XAUUSD", 0.25, rank=1),  # safe_haven — dominates early trials
            make_candidate("USTEC", 0.24, rank=2),  # equity_beta
            make_candidate("AUDUSD", 0.05, rank=3),  # commodity — stale-label risk
            make_candidate("EURUSD", -0.10, rank=4),  # diversifier
        ]
        decision = run_select(candidates, returns)
        exposure = ShadowSelectorConfig().exposure_config()
        final_weights = decision.selected["weights"]
        selected_set = set(decision.selected["symbols"])
        clean_rejected = 0
        for c in decision.candidates:
            if c["symbol"] in selected_set:
                continue
            hard = exposure.final_state_rejection(final_weights, c["symbol"], c["weight"])
            recorded = c["rejection_reason"]
            if hard is not None:
                assert recorded == hard, (c["symbol"], recorded, hard)
            else:
                # Final state is clean — a hard-cap label would be stale.
                assert recorded not in HARD_CAP_REASONS, (c["symbol"], recorded)
                clean_rejected += 1
        assert clean_rejected >= 1  # at least one clean-final-state rejection exercised

    def test_lost_edge_attributable_to_dominant_reason(self):
        """Sum of |w| over R4-only names grouped by dominant reason must equal
        the edge discarded (edge_metrics['candidate_edge_discarded_pct'])."""
        returns = make_returns(
            ["AUDUSD", "AUDCHF", "EURUSD", "GBPUSD", "USDJPY"],
            factor_map={"AUDUSD": 1.0, "AUDCHF": 1.0, "EURUSD": 0.0, "GBPUSD": 0.0, "USDJPY": 0.0},
            seed=39,
        )
        candidates = [
            make_candidate("AUDUSD", 0.20, rank=1),
            make_candidate("AUDCHF", 0.19, rank=2),
            make_candidate("EURUSD", -0.12, rank=3),
            make_candidate("GBPUSD", -0.11, rank=4),
            make_candidate("USDJPY", -0.10, rank=5),
        ]
        decision = run_select(candidates, returns)
        r4_gross = decision.baseline["metrics"]["gross_edge"]
        baseline_set = set(decision.baseline["symbols"])
        selected_set = set(decision.selected["symbols"])
        lost = 0.0
        for c in decision.candidates:
            if c["symbol"] in baseline_set and c["symbol"] not in selected_set:
                lost += abs(c["weight"])
                assert c["dominant_rejection"] is not None
        assert lost == pytest.approx(r4_gross - decision.selected["metrics"]["gross_edge"], abs=1e-6)
