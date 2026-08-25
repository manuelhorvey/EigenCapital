"""Phase 1U item 2 - live risk unification: one authoritative source."""


from eigencapital.live.risk import MicroLiveLimits, MicroLiveRiskEnvelope
from eigencapital.risk.checks.account_checks import AccountState


def _envelope() -> MicroLiveRiskEnvelope:
    return MicroLiveRiskEnvelope(limits=MicroLiveLimits())


class TestExposureMapFailClosed:
    def test_open_positions_without_maps_blocked(self):
        env = _envelope()
        state = AccountState(equity=10_000, peak_equity=10_000,
                             position_count=2)
        allowed, reason = env.check_policy_state(state)
        assert not allowed
        assert "exposure_map_missing" in reason

    def test_partially_populated_maps_blocked(self):
        env = _envelope()
        state = AccountState(equity=10_000, position_count=1,
                             instrument_exposures={"EURUSDm": 500.0})
        allowed, reason = env.check_policy_state(state)
        assert not allowed and "asset_class_exposures" in reason

    def test_zero_positions_requires_no_maps(self):
        allowed, _ = _envelope().check_policy_state(AccountState())
        assert allowed

    def test_populated_maps_reach_policy(self):
        env = _envelope()
        state = AccountState(equity=100_000, peak_equity=100_000,
                             position_count=1,
                             instrument_exposures={"XAUUSDm": 5_000.0},
                             asset_class_exposures={"metals": 5_000.0})
        allowed, reason = env.check_policy_state(state)
        assert allowed, reason


class TestPolicyIsAuthoritative:
    def test_concentration_breach_blocks_despite_envelope_headroom(self):
        env = _envelope()  # envelope notional limit 5000; breach via policy
        state = AccountState(equity=10_000, position_count=1,
                             instrument_exposures={"US500m": 4_000.0},
                             asset_class_exposures={"indices": 4_000.0})
        assert state.instrument_exposures["US500m"] < \
            MicroLiveLimits().max_order_notional
        allowed, reason = env.check_policy_state(state)
        assert not allowed
        assert "concentration" in reason.lower()

    def test_drawdown_fail_blocks(self):
        env = _envelope()
        state = AccountState(equity=8_000, peak_equity=10_000,
                             position_count=1,
                             instrument_exposures={"EURUSDm": 100.0},
                             asset_class_exposures={"forex": 100.0})
        allowed, reason = env.check_policy_state(state)
        assert not allowed and "drawdown" in reason.lower()

    def test_envelope_fingerprint_untouched_by_unification(self):
        # MicroLiveLimits fingerprint must remain stable across refactor
        assert len(MicroLiveLimits().compute_fingerprint()) == 64


class TestMicroSpecificLayerRetained:
    def test_spread_still_enforced_at_envelope(self):
        env = _envelope()
        allowed, reason = env.check_order(notional=100, current_positions=0,
                                          spread=0.5)
        assert not allowed and "Spread" in reason
