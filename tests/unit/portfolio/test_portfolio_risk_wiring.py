"""P1-A regression tests — Portfolio risk-policy wiring.

Proves the deterministic construction path mandated by the forensic review:

    LiveRiskConfig
        → RiskPolicy.from_live_config()
        → EigenRiskEngine(policy=...)
        → Portfolio(risk_engine=...)

and that the old silent fallback — Portfolio() → EigenRiskEngine() → the
research/institution RiskPolicy() profile — can no longer appear.
"""

import pytest

from eigencapital.config import LiveRiskConfig
from eigencapital.core.models.strategy_intent import Horizon, StrategyIntent
from eigencapital.portfolio.portfolio import Portfolio
from eigencapital.risk.checks.account_checks import AccountState
from eigencapital.risk.engine import EigenRiskEngine
from eigencapital.risk.policy import RiskPolicy


def _intent(instrument_id: str = "ES", direction: int = 1) -> StrategyIntent:
    return StrategyIntent(
        strategy_id="trend_v1",
        strategy_version="v1.0.0",
        instrument_id=instrument_id,
        timestamp_utc="2025-01-01T10:00:00Z",
        direction=direction,
        target_risk=0.05,
        horizon=Horizon.SWING,
        strategy_config_hash="config_hash_123",
        strategy_artifact_hash="artifact_hash_456",
    )


class TestFromLiveConfig:
    """Live configuration must produce the expected EigenRisk policy (A1)."""

    def test_mapping_from_live_config_fields(self):
        cfg = LiveRiskConfig(
            max_concurrent_positions=6,
            max_position_notional=1_750.0,
            max_per_position_loss_pct=0.08,
            max_account_drawdown_pct=0.07,
            max_daily_loss=180.0,
            min_equity=3_500.0,
        )
        policy = RiskPolicy.from_live_config(cfg)

        assert policy.max_position_count == 6
        assert policy.max_position_notional == 1_750.0
        assert policy.max_position_risk_pct == pytest.approx(8.0)
        assert policy.max_drawdown_pct == pytest.approx(7.0)
        assert policy.daily_loss_limit == 180.0
        assert policy.min_equity == 3_500.0

    def test_live_policy_differs_from_research_defaults(self):
        """A live-derived policy must NOT equal the bare RiskPolicy() profile."""
        live = RiskPolicy.from_live_config(LiveRiskConfig())
        research = RiskPolicy()

        # Discriminating fields: research is institution-sized ($50k min equity,
        # $500k position notional, $5k daily loss); live is retail-sized.
        assert live.min_equity == 4_000.0 and research.min_equity == 50_000.0
        assert live.daily_loss_limit == 250.0 and research.daily_loss_limit == 5_000.0
        assert live.max_position_notional == 2_500.0
        assert live != research


class TestPortfolioUsesInjectedPolicy:
    """Portfolio must use the injected engine's policy for decisions."""

    def _portfolio_with_live_policy(self, cfg: LiveRiskConfig | None = None) -> Portfolio:
        policy = RiskPolicy.from_live_config(cfg or LiveRiskConfig())
        return Portfolio(risk_engine=EigenRiskEngine(policy=policy))

    def test_live_daily_loss_limit_blocks_larger_daily_pnl(self):
        """daily_pnl -$1,000 is within research limits but breaches the live $250 limit."""
        live = self._portfolio_with_live_policy()
        # Preserve a -$1000 daily P&L through update_account_state (it carries
        # the account_state.daily_pnl forward).
        live.state.account_state = AccountState(
            equity=100_000.0,
            peak_equity=100_000.0,
            daily_pnl=-1_000.0,
            weekly_pnl=0.0,
            gross_exposure=0.0,
            net_exposure=0.0,
            position_count=0,
        )
        decision = live.process_intents([_intent()])
        assert decision.risk_decisions[0].decision == "REJECTED"

    def test_research_daily_loss_limit_allows_same_pnl(self):
        """Same -$1,000 daily P&L is APPROVED under the explicit research profile."""
        research = Portfolio(risk_engine=EigenRiskEngine(policy=RiskPolicy()))
        research.state.account_state = AccountState(
            equity=100_000.0,
            peak_equity=100_000.0,
            daily_pnl=-1_000.0,
            weekly_pnl=0.0,
            gross_exposure=0.0,
            net_exposure=0.0,
            position_count=0,
        )
        decision = research.process_intents([_intent()])
        assert decision.risk_decisions[0].decision == "APPROVED"

    def test_injected_engine_is_used_directly(self):
        """Portfolio must hold and evaluate with exactly the injected engine."""
        policy = RiskPolicy.from_live_config(LiveRiskConfig(max_daily_loss=99.0))
        engine = EigenRiskEngine(policy=policy)
        portfolio = Portfolio(risk_engine=engine)
        assert portfolio.risk_engine is engine

        portfolio.state.account_state = AccountState(
            equity=100_000.0,
            peak_equity=100_000.0,
            daily_pnl=-150.0,
            weekly_pnl=0.0,
            gross_exposure=0.0,
            net_exposure=0.0,
            position_count=0,
        )
        decision = portfolio.process_intents([_intent()])
        assert decision.risk_decisions[0].decision == "REJECTED"


class TestNoSilentResearchDefault:
    """A research-default policy must never appear without an explicit choice."""

    def test_portfolio_without_engine_raises(self):
        with pytest.raises(TypeError):
            Portfolio()  # type: ignore[call-arg]

    def test_research_profile_is_an_explicit_choice(self):
        """Passing EigenRiskEngine() is allowed — it is now an explicit decision."""
        portfolio = Portfolio(risk_engine=EigenRiskEngine())
        assert portfolio.risk_engine.policy == RiskPolicy()
