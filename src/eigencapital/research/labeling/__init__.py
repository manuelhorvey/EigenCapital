"""EigenCapital research package: label-quality research (R5 triple barrier).

Research-only. Events are read from the frozen replica pipeline; R4
production, the risk engine, and execution are untouched.
"""

from eigencapital.research.labeling.triple_barrier import (
    ANNUALIZATION,
    LABEL_VERSION,
    PT_MULTIPLIER,
    SL_MULTIPLIER,
    VERTICAL_HORIZON,
    VOL_LOOKBACK,
    Event,
    FirstTouchType,
    LabeledEvent,
    LabelingError,
    LabelRun,
    PitViolationError,
    average_uniqueness,
    build_labels,
    label_event,
    overlap_intervals,
    pit_daily_vol,
)

__all__ = [
    "ANNUALIZATION",
    "LABEL_VERSION",
    "PT_MULTIPLIER",
    "SL_MULTIPLIER",
    "VERTICAL_HORIZON",
    "VOL_LOOKBACK",
    "Event",
    "FirstTouchType",
    "LabeledEvent",
    "LabelingError",
    "LabelRun",
    "PitViolationError",
    "average_uniqueness",
    "build_labels",
    "label_event",
    "overlap_intervals",
    "pit_daily_vol",
]
