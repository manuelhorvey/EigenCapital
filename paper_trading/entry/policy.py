import logging

from paper_trading.entry.decision import (
    EntryAction,
    MarketStructureState,
    PolicyDecision,
    TPGeometry,
    TradeDecision,
)
from paper_trading.entry.deferred_entry import DeferredEntry

logger = logging.getLogger("eigencapital.paper_trading.execution_policy")


class BasePolicy:
    """Base class for archetype-specific routing policies."""

    @staticmethod
    def route(
        action: EntryAction,
        decision: TradeDecision,
        archetype: str,
        structure: MarketStructureState,
        tp_geo: TPGeometry | None,
        deferred: DeferredEntry | None,
    ) -> PolicyDecision:
        # Default implementation: strictly follow the pre-decided action
        return PolicyDecision(
            action=action,
            entry_plan=deferred if action == EntryAction.DEFER else None,
            exit_plan=tp_geo if action == EntryAction.ENTER else None,
            reason=f"Standard routing for {archetype}: {action}",
            archetype=archetype,
            metadata={"source": "BasePolicy"},
        )


class MomentumPolicy(BasePolicy):
    """Routing for Momentum Ignition."""

    @staticmethod
    def route(action, decision, archetype, structure, tp_geo, deferred):
        reason = f"Momentum routing: {action}"
        if action == EntryAction.DEFER:
            reason = f"Momentum ignition deferred (Structural Pressure: {structure.breakout_pressure})"

        return PolicyDecision(
            action=action,
            entry_plan=deferred if action == EntryAction.DEFER else None,
            exit_plan=tp_geo if action == EntryAction.ENTER else None,
            reason=reason,
            archetype=archetype,
            metadata={"source": "MomentumPolicy", "convexity": tp_geo.convexity_score if tp_geo else None},
        )


class ExecutionPolicyLayer:
    """
    Phase 4: Execution Policy Layer Switchboard.
    A deterministic routing compiler over already-frozen decisions.
    Boringly deterministic traffic controller.
    """

    POLICY_MAP = {
        "MOMENTUM_IGNITION": MomentumPolicy,
        "MEAN_REVERSION": BasePolicy,
        "BREAKOUT_TEST": BasePolicy,
        "TREND_PULLBACK": BasePolicy,
        "VOL_EXPANSION": BasePolicy,
        "UNKNOWN": BasePolicy,
    }

    def handle(
        self,
        action: EntryAction,
        decision: TradeDecision,
        archetype: str,
        structure: MarketStructureState,
        tp_geo: TPGeometry | None = None,
        deferred: DeferredEntry | None = None,
    ) -> PolicyDecision:
        """
        Routes artifacts into the final immutable execution plan.
        """
        # 1. Resolve Policy
        policy_cls = self.POLICY_MAP.get(archetype.upper(), BasePolicy)

        # 2. Compile Decision
        try:
            return policy_cls.route(action, decision, archetype, structure, tp_geo, deferred)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as e:
            logger.error("Policy routing failed for %s: %s", archetype, e)
            # Emergency Fallback: strictly follow action with no frills
            return PolicyDecision(
                action=action,
                entry_plan=deferred if action == EntryAction.DEFER else None,
                exit_plan=tp_geo if action == EntryAction.ENTER else None,
                reason=f"Emergency fallback routing for {archetype}",
                archetype=archetype,
                metadata={"emergency": True},
            )
