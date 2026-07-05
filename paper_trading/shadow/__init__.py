"""Shadow analytics engine — counterfactual SL/TP replay for online research.

Shadow replays the same market tape as live positions but with alternative
SL/TP parameters, enabling side-effect-free counterfactual analysis alongside
the live engine. Shadow engines consume immutable execution artifacts and
never share mutable state with the live engine.

Architecture::

    Live:  DynamicSLTPEngine → PositionManager → trade close (mutates capital)
    Shadow: ShadowSLTPEngine → shadow buffer   (zero side effects)

Key modules:
    engine:       ShadowSLTPEngine — counterfactual replay with alternative params
    actions:      compute_shadow_actions — drift- and risk-aware shadow decisions
    analytics:    Shadow analytics aggregation and comparison
    feedback:     Feedback loop ingestion from shadow outcomes
    learning:     Reinforcement learning from shadow replay results
    memory:       Persistent shadow state across engine restarts
"""
