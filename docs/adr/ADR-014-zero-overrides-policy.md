# ADR-014: Zero Manual Overrides Policy During Paper Trading

**Status:** Accepted

## Context

During the research phase, every manual intervention — adjusting a threshold mid-walk-forward, adding a feature to improve a specific year, changing the regime classifier parameters to fix a known misclassification — produced new failure modes elsewhere. The pattern was consistent: a change that fixed the 2022 window degraded 2023 or 2024. The research loop showed that adding complexity to hide problems delays diagnosis. The correct response to a model failure is diagnostic investigation, not surgical intervention. The paper trading phase is validation, not research — the rules must be fixed and the model must stand or fall on its own.

## Decision

Zero manual overrides during paper trading. The `monitor_all` script runs the paper trading engine without any user-configurable parameters. The engine loads the model from pickle, runs inference on fresh data, and outputs signals. No threshold adjustments, no feature additions, no parameter changes during the paper trading period. If the system triggers a halt condition (drawdown limit, validity state RED, confidence collapse), the engine stops and logs the condition — it does not ask for permission to continue. The only allowed actions are: a) stopping the engine, b) restarting the engine in its current configuration, c) rolling back to a previous model checkpoint.

## Alternatives Considered

- **Managed overrides (justified in a log):)** Creates a slippery slope — every override has a justification, but the cumulative effect is untested.
- **Parameterized override thresholds in config:** The YAML config already has per-asset halt conditions. Overriding these during paper trading defeats the purpose of having them.
- **Graceful degradation (reduce exposure instead of halt):)** This is what the validity state machine does automatically (YELLOW → 50%, RED → 0%). Manual overrides would bypass the state machine.

## Consequences

**Positive:** The paper trading results are interpretable — they reflect the model as validated, not the model as nursed through bad periods. If the system fails, the failure mode is diagnostic (what did the model miss?) rather than operational (did we override correctly?). This creates a clean boundary between research and validation.

**Negative:** If the model hits a drawdown limit and halts, the system stays halted until someone manually restarts it. A 2-day weekend gap in data could trigger RED if the model misinterprets the discontinuity. The zero-override policy increases downtime risk. If market structure changes (e.g., XLF de-lists), the engine would continue trading on a dead asset until manually stopped.

## Evidence

Every manual intervention during research produced new failure modes. The 2023 fix (replacing yield_slope with 2y_yield_delta_63, ADR-007) was the only successful manual intervention — and it succeeded because it was based on residual analysis, not a fix for a specific year. All threshold adjustments during research degraded aggregate performance. The conclusion: if the model needs manual overrides to survive, it is not ready for paper trading.
