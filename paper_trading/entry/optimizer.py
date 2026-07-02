import logging

from paper_trading.entry.decision import EntryAction, MarketStructureState, SignalType

logger = logging.getLogger("eigencapital.paper_trading.entry_optimizer")


class EntryOptimizer:
    """
    Phase 1: Entry Optimizer Router.
    Maps (Archetype, MarketStructureState) -> EntryAction (ENTER, DEFER, SKIP).
    Strictly deterministic routing system. No strategy logic encoded here;
    it consumes policy rules defined in Phase 4.
    """

    def __init__(self, policy_map: dict = None):
        # Default policy map (to be fully populated in Phase 4)
        self.policy_map = policy_map or {
            "MOMENTUM_IGNITION": self._momentum_ignition_policy,
            "MEAN_REVERSION": self._mean_reversion_policy,
            "BREAKOUT_TEST": self._breakout_policy,
            "VOL_EXPANSION": self._vol_expansion_policy,
        }

    def evaluate(
        self, signal: SignalType, archetype: str, structure: MarketStructureState, config: dict = None
    ) -> EntryAction:
        """
        Routes the signal to the correct policy based on its archetype.
        """
        if signal == SignalType.FLAT:
            return EntryAction.SKIP

        policy_func = self.policy_map.get(archetype, self._default_policy)

        try:
            return policy_func(signal, structure, config or {})
        except Exception as e:
            logger.error("Entry policy execution failed for %s: %s", archetype, e)
            return EntryAction.SKIP  # Fail-closed: skip entry on policy error

    def _momentum_ignition_policy(self, signal: SignalType, s: MarketStructureState, config: dict) -> EntryAction:
        """
        Policy: Defer if price is 'chasing' the high/low.
        """
        # Thresholds will eventually be moved to config
        max_pressure = config.get("mom_max_pressure", 0.90)
        min_pressure = config.get("mom_min_pressure", 0.10)

        if signal == SignalType.BUY and s.breakout_pressure > max_pressure:
            return EntryAction.DEFER
        if signal == SignalType.SELL and s.breakout_pressure < min_pressure:
            return EntryAction.DEFER

        return EntryAction.ENTER

    def _mean_reversion_policy(self, signal: SignalType, s: MarketStructureState, config: dict) -> EntryAction:
        """
        Policy: Wait for price to reach structural extremes.
        """
        extreme_high = config.get("mr_extreme_high", 0.85)
        extreme_low = config.get("mr_extreme_low", 0.15)

        if signal == SignalType.BUY and s.breakout_pressure > extreme_low:
            return EntryAction.DEFER
        if signal == SignalType.SELL and s.breakout_pressure < extreme_high:
            return EntryAction.DEFER

        return EntryAction.ENTER

    def _breakout_policy(self, signal: SignalType, s: MarketStructureState, config: dict) -> EntryAction:
        """
        Policy: Confirm breakout compression.
        """
        if s.compression_score > config.get("breakout_max_compression", 0.05):
            return EntryAction.DEFER
        return EntryAction.ENTER

    def _vol_expansion_policy(self, signal: SignalType, s: MarketStructureState, config: dict) -> EntryAction:
        return EntryAction.ENTER

    def _default_policy(self, signal: SignalType, s: MarketStructureState, config: dict) -> EntryAction:
        return EntryAction.ENTER
