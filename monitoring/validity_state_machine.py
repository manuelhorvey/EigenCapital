import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger("eigencapital.validity_state_machine")


class ValidityState(Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass
class StateTransition:
    from_state: ValidityState
    to_state: ValidityState
    timestamp: pd.Timestamp
    raw_validity: float
    smoothed_validity: float
    reason: str


class ValidityStateMachine:
    """
    Capital allocation state machine with hysteresis, temporal smoothing,
    and regime persistence lock.

    Transforms point-in-time validity scores into state-based allocation decisions
    with memory to prevent rapid flipping and unstable capital deployment.
    """

    def __init__(
        self,
        # Hysteresis bands
        green_entry_threshold: float = 0.70,
        green_exit_threshold: float = 0.60,
        yellow_entry_threshold: float = 0.45,
        yellow_exit_threshold: float = 0.40,
        red_entry_threshold: float = 0.40,
        red_exit_threshold: float = 0.50,
        # Validity inertia (exponential decay)
        inertia_alpha: float = 0.7,  # weight on current validity
        inertia_beta: float = 0.3,  # weight on previous validity
        # Regime persistence lock
        regime_lock_periods: int = 5,  # minimum periods before allowing state change
        regime_lock_window: int = 10,  # window to check for regime stability
        # Exposure allocation
        green_exposure: float = 1.0,
        yellow_exposure: float = 0.5,
        red_exposure: float = 0.0,
    ):
        # Hysteresis thresholds
        self.green_entry = green_entry_threshold
        self.green_exit = green_exit_threshold
        self.yellow_entry = yellow_entry_threshold
        self.yellow_exit = yellow_exit_threshold
        self.red_entry = red_entry_threshold
        self.red_exit = red_exit_threshold

        # Inertia parameters
        self.inertia_alpha = inertia_alpha
        self.inertia_beta = inertia_beta

        # Regime persistence parameters
        self.regime_lock_periods = regime_lock_periods
        self.regime_lock_window = regime_lock_window

        # Exposure allocation
        self.exposure_map = {
            ValidityState.GREEN: green_exposure,
            ValidityState.YELLOW: yellow_exposure,
            ValidityState.RED: red_exposure,
        }

        # State tracking
        self.current_state: ValidityState = ValidityState.YELLOW
        self.previous_smoothed_validity: float | None = None
        self.state_history: list[StateTransition] = []
        self.periods_in_current_state: int = 0
        self.last_transition_time: pd.Timestamp | None = None

    def _apply_inertia(self, raw_validity: float) -> float:
        """
        Apply exponential decay smoothing to validity score.

        validity_t = alpha * validity_t + beta * validity_{t-1}
        """
        if self.previous_smoothed_validity is None:
            smoothed = raw_validity
        else:
            smoothed = self.inertia_alpha * raw_validity + self.inertia_beta * self.previous_smoothed_validity

        self.previous_smoothed_validity = smoothed
        return smoothed

    def _check_regime_persistence_lock(
        self, proposed_state: ValidityState, recent_validity: pd.Series
    ) -> tuple[bool, str]:
        """
        Prevent rapid state flipping by checking regime persistence.

        Returns (allowed, reason) tuple.
        """
        # Allow immediate transition if same state
        if proposed_state == self.current_state:
            return True, "No state change"

        # Check minimum periods in current state
        if self.periods_in_current_state < self.regime_lock_periods:
            return (
                False,
                f"Regime lock: only {self.periods_in_current_state} periods in {self.current_state.value} "
                f"(required {self.regime_lock_periods})",
            )

        # Check stability of recent validity signal
        if len(recent_validity) >= self.regime_lock_window:
            recent_std = recent_validity.tail(self.regime_lock_window).std()
            if recent_std > 0.15:  # High volatility in validity signal
                return (False, f"Regime lock: high validity volatility (std={recent_std:.3f})")

        return True, "Regime persistence satisfied"

    def _determine_proposed_state(self, smoothed_validity: float) -> ValidityState:
        """
        Determine proposed state based on hysteresis bands.

        Entry/exit thresholds prevent oscillation around boundaries.
        """
        current = self.current_state

        if current == ValidityState.GREEN:
            # Exit GREEN only below exit threshold
            if smoothed_validity < self.green_exit:
                if smoothed_validity >= self.yellow_entry:
                    return ValidityState.YELLOW
                else:
                    return ValidityState.RED
            return ValidityState.GREEN

        elif current == ValidityState.YELLOW:
            # Can enter GREEN above entry threshold
            if smoothed_validity >= self.green_entry:
                return ValidityState.GREEN
            # Can enter RED below exit threshold
            if smoothed_validity < self.yellow_exit:
                return ValidityState.RED
            return ValidityState.YELLOW

        elif current == ValidityState.RED:
            # Exit RED only above exit threshold
            if smoothed_validity >= self.red_exit:
                if smoothed_validity >= self.green_entry:
                    return ValidityState.GREEN
                else:
                    return ValidityState.YELLOW
            return ValidityState.RED

        return ValidityState.YELLOW

    def transition(
        self, raw_validity: float, timestamp: pd.Timestamp, recent_validity: pd.Series | None = None
    ) -> dict:
        """
        Process a new validity observation and determine state transition.

        Args:
            raw_validity: Point-in-time validity score
            timestamp: Current timestamp
            recent_validity: Series of recent validity scores for persistence check

        Returns:
            Dictionary with state, exposure, and transition details
        """
        # Apply inertia smoothing
        smoothed_validity = self._apply_inertia(raw_validity)

        # Determine proposed state based on hysteresis
        proposed_state = self._determine_proposed_state(smoothed_validity)

        # Check regime persistence lock
        if recent_validity is None:
            recent_validity = pd.Series([raw_validity])

        lock_allowed, lock_reason = self._check_regime_persistence_lock(proposed_state, recent_validity)

        # Apply lock if needed
        final_state = proposed_state if lock_allowed else self.current_state
        transition_occurred = final_state != self.current_state

        # Record transition
        if transition_occurred:
            transition = StateTransition(
                from_state=self.current_state,
                to_state=final_state,
                timestamp=timestamp,
                raw_validity=raw_validity,
                smoothed_validity=smoothed_validity,
                reason=lock_reason if not lock_allowed else "Hysteresis transition",
            )
            self.state_history.append(transition)
            self.current_state = final_state
            self.periods_in_current_state = 0
            self.last_transition_time = timestamp
        else:
            self.periods_in_current_state += 1

        # Get exposure allocation
        exposure = self.exposure_map[final_state]

        return {
            "timestamp": timestamp,
            "raw_validity": raw_validity,
            "smoothed_validity": smoothed_validity,
            "state": final_state.value,
            "exposure": exposure,
            "transition_occurred": transition_occurred,
            "lock_active": not lock_allowed,
            "lock_reason": lock_reason if not lock_allowed else None,
            "periods_in_state": self.periods_in_current_state,
        }

    def process_timeline(
        self, validity_df: pd.DataFrame, validity_col: str = "validity", timestamp_col: str = "window"
    ) -> pd.DataFrame:
        """
        Process a timeline of validity scores through the state machine.

        Args:
            validity_df: DataFrame with validity scores over time
            validity_col: Column name for validity scores
            timestamp_col: Column name for timestamps

        Returns:
            DataFrame with state machine outputs
        """
        results = []
        self.reset()  # Reset state for new timeline

        for pos, (idx, row) in enumerate(validity_df.iterrows()):
            timestamp = row.get(timestamp_col, idx)
            raw_validity = row[validity_col]

            # Get recent validity for persistence check
            recent_validity = validity_df[validity_col].iloc[: pos + 1]

            result = self.transition(raw_validity, timestamp, recent_validity)
            results.append(result)

        return pd.DataFrame(results)

    def reset(self):
        """Reset state machine to initial conditions."""
        self.current_state = ValidityState.YELLOW
        self.previous_smoothed_validity = None
        self.state_history = []
        self.periods_in_current_state = 0
        self.last_transition_time = None

    def get_state_summary(self) -> dict:
        """Get summary of current state and history."""
        return {
            "current_state": self.current_state.value,
            "periods_in_state": self.periods_in_current_state,
            "last_transition_time": self.last_transition_time,
            "total_transitions": len(self.state_history),
            "transition_history": [
                {"from": t.from_state.value, "to": t.to_state.value, "timestamp": t.timestamp, "reason": t.reason}
                for t in self.state_history
            ],
        }


def compute_allocation_statistics(state_df: pd.DataFrame) -> dict:
    """
    Compute allocation statistics from state machine output.

    Args:
        state_df: Output from ValidityStateMachine.process_timeline() or timeline

    Returns:
        Dictionary with allocation statistics
    """
    if len(state_df) == 0:
        return {}

    total_periods = len(state_df)
    # Support both "state" and "era" column names
    state_col = "state" if "state" in state_df.columns else "era"
    state_counts = state_df[state_col].value_counts()

    # State distribution
    green_pct = state_counts.get("GREEN", 0) / total_periods
    yellow_pct = state_counts.get("YELLOW", 0) / total_periods
    red_pct = state_counts.get("RED", 0) / total_periods

    # Transition statistics (only if transition_occurred column exists)
    if "transition_occurred" in state_df.columns:
        transitions = state_df[state_df["transition_occurred"]]
        n_transitions = len(transitions)
    else:
        n_transitions = 0

    # Average exposure (only if exposure column exists)
    avg_exposure = state_df["exposure"].mean() if "exposure" in state_df.columns else 0.0

    # Lock activation rate (only if lock_active column exists)
    lock_rate = state_df["lock_active"].mean() if "lock_active" in state_df.columns else 0.0

    # State persistence (only if periods_in_state column exists)
    if "periods_in_state" in state_df.columns:
        avg_periods_per_state = state_df.groupby(state_col)["periods_in_state"].mean().to_dict()
    else:
        avg_periods_per_state = {}

    return {
        "total_periods": total_periods,
        "state_distribution": {
            "GREEN": green_pct,
            "YELLOW": yellow_pct,
            "RED": red_pct,
        },
        "n_transitions": n_transitions,
        "transition_rate": n_transitions / total_periods if total_periods > 0 else 0,
        "average_exposure": avg_exposure,
        "lock_activation_rate": lock_rate,
        "average_periods_per_state": avg_periods_per_state,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Test with synthetic validity data
    np.random.seed(42)

    # Create synthetic validity timeline with regime shifts
    periods = 100
    validity_scores = []

    # Regime 1: High validity (GREEN)
    validity_scores.extend([0.75 + np.random.normal(0, 0.05) for _ in range(30)])

    # Regime 2: Declining validity (transition)
    validity_scores.extend([0.65 - i * 0.01 + np.random.normal(0, 0.03) for i in range(20)])

    # Regime 3: Low validity (RED)
    validity_scores.extend([0.35 + np.random.normal(0, 0.04) for _ in range(25)])

    # Regime 4: Recovery (transition back)
    validity_scores.extend([0.45 + i * 0.015 + np.random.normal(0, 0.03) for i in range(25)])

    # Clip to valid range
    validity_scores = np.clip(validity_scores, 0, 1)

    # Create DataFrame
    dates = pd.date_range(start="2020-01-01", periods=periods, freq="D")
    df = pd.DataFrame(
        {
            "window": dates,
            "validity": validity_scores,
        }
    )

    # Run state machine
    sm = ValidityStateMachine(
        green_entry_threshold=0.70,
        green_exit_threshold=0.60,
        yellow_entry_threshold=0.45,
        yellow_exit_threshold=0.40,
        regime_lock_periods=3,
    )

    results = sm.process_timeline(df)

    logger.info("\n%s", "=" * 50)
    logger.info("VALIDITY STATE MACHINE OUTPUT")
    logger.info("%s", "=" * 50)
    logger.info(
        "\n%s",
        results[["timestamp", "raw_validity", "smoothed_validity", "state", "exposure", "lock_active"]]
        .round(4)
        .to_string(index=False),
    )

    logger.info("\n%s", "=" * 50)
    logger.info("ALLOCATION STATISTICS")
    logger.info("%s", "=" * 50)
    stats = compute_allocation_statistics(results)
    for key, value in stats.items():
        if isinstance(value, dict):
            logger.info("\n%s:", key)
            for k, v in value.items():
                logger.info("  %s: %.4f", k, v)
        else:
            logger.info("%s: %s", key, value)

    logger.info("\n%s", "=" * 50)
    logger.info("STATE SUMMARY")
    logger.info("%s", "=" * 50)
    summary = sm.get_state_summary()
    for key, value in summary.items():
        if key == "transition_history":
            logger.info("\n%s:", key)
            for t in value:
                logger.info("  %s -> %s at %s: %s", t["from"], t["to"], t["timestamp"], t["reason"])
        else:
            logger.info("%s: %s", key, value)
