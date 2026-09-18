"""Triple-Barrier Labeling — R5-B frozen specification, first-touch engine.

R5 Phase B (docs/research/R5_TRIPLE_BARRIER.md, frozen contract). Pure
functions only: every input is supplied by the caller; this module performs
no I/O and never touches production code paths.

The ONE preregistered specification (contract item 2 — no sweeps, ever):

    volatility       : per-symbol 60-day realized vol of daily close returns,
                       annualized (sqrt 252), computed on data up to and
                       including the event's PREVIOUS bar (strict PIT)
    pt_multiplier    : 2.0
    sl_multiplier    : 2.0
    vertical_horizon : 10 trading bars after the event bar (inclusive scan)
    first-touch rule : scan bars event+1 .. event+10; the FIRST bar whose
                       high/low touches its barrier wins; if both barriers
                       are touched within one bar, the barrier whose price
                       level is closer to that bar's open wins; if none
                       touch → vertical expiry labeled from the close at
                       bar +10.

Label semantics (contract item 3), from the event's own perspective:

    +1 : profit-take barrier touched first
    -1 : stop-loss barrier touched first
     0 : vertical expiry — sign(close(+10) − entry) for LONG,
         sign(entry − close(+10)) for SHORT; exact equality → 0.

The PIT invariant (contract item 4, no exception path): every barrier input
is a function of data available at or before the event bar. ``build_labels``
verifies this by recomputing the vol window against the price index and
raising ``PitViolationError`` on any mismatch. The scan window is future
data BY DEFINITION of a label — labels are training targets, never features.

Scope guard (frozen): research-only. Events are READ from the frozen replica
pipeline, never modified; R4 production is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Tuple

import numpy as np
import pandas as pd

PT_MULTIPLIER = 2.0
SL_MULTIPLIER = 2.0
VOL_LOOKBACK = 60
ANNUALIZATION = np.sqrt(252.0)
VERTICAL_HORIZON = 10
LABEL_VERSION = "r5_spec_v1"


class LabelingError(ValueError):
    """Raised on invalid labeling inputs or specification violations."""


class PitViolationError(LabelingError):
    """Raised when a barrier input uses data after the event bar."""


FirstTouchType = Literal["PT", "SL", "VERTICAL"]


@dataclass(frozen=True)
class Event:
    """One entry event of the frozen replica pipeline (contract item 1)."""

    event_id: str
    instrument: str
    decision_timestamp: pd.Timestamp
    event_timestamp: pd.Timestamp
    side: Literal["LONG", "SHORT"]
    entry_price: float


@dataclass(frozen=True)
class LabeledEvent:
    """Event + first-touch evidence + label (contract item 3)."""

    event: Event
    vol_observation_timestamp: pd.Timestamp
    daily_vol: float
    pt_price: float
    sl_price: float
    vertical_deadline: pd.Timestamp
    first_touch_type: FirstTouchType
    first_touch_timestamp: pd.Timestamp | None
    first_touch_price: float | None
    label: int  # +1 | -1 | 0
    excluded_reason: str = ""


@dataclass(frozen=True)
class LabelRun:
    """Deterministic result of one labeling run (contract item 5.6)."""

    spec_version: str
    labels: Tuple[LabeledEvent, ...]
    n_excluded: int = 0
    exclusion_reasons: Dict[str, int] = field(default_factory=dict)


def _require_positive(value: float, name: str) -> float:
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:
        raise LabelingError(f"{name} must be numeric, got: {value!r}") from exc
    if not np.isfinite(as_float) or as_float <= 0.0:
        raise LabelingError(f"{name} must be finite and positive, got: {as_float!r}")
    return as_float


def pit_daily_vol(closes: pd.Series, event_timestamp: pd.Timestamp, lookback: int = VOL_LOOKBACK) -> float:
    """Realized vol of daily close returns up to and INCLUDING the previous bar.

    Strict PIT by construction: the window is closes.loc[:event_timestamp]
    with the event bar itself EXCLUDED from the return computation (the
    return over the event bar is unknowable at the event bar).
    """
    if not isinstance(closes, pd.Series) or len(closes) < lookback + 1:
        raise LabelingError(f"closes must be a Series with >= {lookback + 1} bars, got {len(closes)}")
    if not (closes > 0).all():
        raise LabelingError("closes must be strictly positive (pre-log price domain)")
    upto = closes.loc[:event_timestamp]
    if len(upto) == 0:
        raise LabelingError(f"event_timestamp {event_timestamp} not in the price index")
    window = upto.iloc[:-1].tail(lookback)  # exclude the event bar itself: strict PIT
    if len(window) < lookback:
        raise PitViolationError(
            f"insufficient PIT history before {event_timestamp}: need {lookback} bars before the event, found {len(window)}"
        )
    rets = window.pct_change().dropna()
    if len(rets) < lookback - 1:
        raise PitViolationError(
            f"insufficient PIT returns before {event_timestamp}: need {lookback - 1}, found {len(rets)}"
        )
    vol = float(rets.std(ddof=1) * ANNUALIZATION)
    if not np.isfinite(vol) or vol <= 0.0:
        raise PitViolationError(f"degenerate PIT vol at {event_timestamp}: {vol!r}")
    return vol


def _resolve_first_touch(
    event: Event,
    bars: pd.DataFrame,
    scan: pd.DataFrame,
    pt_price: float,
    sl_price: float,
) -> Tuple[FirstTouchType, pd.Timestamp | None, float | None, int]:
    """Scan bars event+1 .. +N for the first barrier touch.

    Returns (touch_type, touch_ts, touch_price, label). Same-bar double
    touches resolve to the barrier whose price level is closer to the bar's
    open (contract item 2). Vertical expiry labels from the close at the
    deadline bar (contract item 3).
    """
    long = event.side == "LONG"
    for ts, bar in scan.iterrows():
        high, low, open_ = float(bar["high"]), float(bar["low"]), float(bar["open"])
        pt_hit = high >= pt_price if long else low <= pt_price
        sl_hit = low <= sl_price if long else high >= sl_price
        if pt_hit and sl_hit:
            # Same-bar double touch: closer level to the open wins.
            d_pt, d_sl = abs(pt_price - open_), abs(sl_price - open_)
            if d_pt <= d_sl:
                return "PT", ts, pt_price, 1
            return "SL", ts, sl_price, -1
        if pt_hit:
            return "PT", ts, pt_price, 1
        if sl_hit:
            return "SL", ts, sl_price, -1
    # Vertical expiry: sign of the favorable-direction move at the deadline.
    deadline = scan.index[-1]
    close = float(bars.at[deadline, "close"])
    move = (close - event.entry_price) if long else (event.entry_price - close)
    label = 1 if move > 0.0 else (-1 if move < 0.0 else 0)
    return "VERTICAL", deadline, close, label


def label_event(event: Event, bars: pd.DataFrame) -> LabeledEvent:
    """Label ONE event under the frozen specification.

    ``bars`` is the instrument's OHLC frame indexed by trading day. The
    event bar itself must exist in the index; the scan window is the next
    VERTICAL_HORIZON bars after it. If fewer than the horizon bars exist
    after the event (data end), the event is EXCLUDED and counted — never
    imputed (contract F4).
    """
    if event.side not in ("LONG", "SHORT"):
        raise LabelingError(f"side must be LONG or SHORT, got {event.side!r}")
    entry = _require_positive(event.entry_price, "entry_price")
    if event.event_timestamp not in bars.index:
        raise LabelingError(f"event bar {event.event_timestamp} missing from the price index")

    pos = bars.index.get_loc(event.event_timestamp)
    if not isinstance(pos, int):  # pragma: no cover - defensive
        raise LabelingError(f"non-unique event bar timestamp {event.event_timestamp}")

    try:
        vol = pit_daily_vol(bars["close"], event.event_timestamp)
        vol_obs_ts = bars.index[pos - 1]
    except PitViolationError as exc:
        return LabeledEvent(
            event=event,
            vol_observation_timestamp=bars.index[0],
            daily_vol=0.0,
            pt_price=0.0,
            sl_price=0.0,
            vertical_deadline=bars.index[min(pos + VERTICAL_HORIZON, len(bars) - 1)],
            first_touch_type="VERTICAL",
            first_touch_timestamp=None,
            first_touch_price=None,
            label=0,
            excluded_reason=str(exc),
        )

    if pos + VERTICAL_HORIZON >= len(bars):
        return LabeledEvent(
            event=event,
            vol_observation_timestamp=vol_obs_ts,
            daily_vol=vol,
            pt_price=0.0,
            sl_price=0.0,
            vertical_deadline=bars.index[-1],
            first_touch_type="VERTICAL",
            first_touch_timestamp=None,
            first_touch_price=None,
            label=0,
            excluded_reason=f"event at {event.event_timestamp} has < {VERTICAL_HORIZON} bars after it (data end) — excluded, never imputed",
        )

    daily_vol = vol / ANNUALIZATION  # per-day vol for barrier distances
    pt_distance = daily_vol * PT_MULTIPLIER * entry  # multiplicative — contract item 2
    sl_distance = daily_vol * SL_MULTIPLIER * entry
    long = event.side == "LONG"
    pt_price = entry + pt_distance if long else entry - pt_distance
    sl_price = entry - sl_distance if long else entry + sl_distance
    scan = bars.iloc[pos + 1 : pos + VERTICAL_HORIZON + 1]
    touch_type, touch_ts, touch_px, label = _resolve_first_touch(event, bars, scan, pt_price, sl_price)

    return LabeledEvent(
        event=event,
        vol_observation_timestamp=vol_obs_ts,
        daily_vol=vol,
        pt_price=pt_price,
        sl_price=sl_price,
        vertical_deadline=scan.index[-1],
        first_touch_type=touch_type,
        first_touch_timestamp=touch_ts,
        first_touch_price=touch_px,
        label=label,
    )


def build_labels(events: List[Event], bars_by_instrument: Dict[str, pd.DataFrame]) -> LabelRun:
    """Label a full event list deterministically (contract item 5.6).

    Excluded events (PIT-history or data-end reasons, contract F4) are
    counted by reason — never silently dropped, never imputed.
    """
    labeled: List[LabeledEvent] = []
    exclusions: Dict[str, int] = {}
    for event in events:
        bars = bars_by_instrument.get(event.instrument)
        if bars is None:
            raise LabelingError(f"no price data supplied for instrument {event.instrument!r}")
        result = label_event(event, bars)
        if result.excluded_reason:
            key = (
                "pit_history"
                if "PIT" in result.excluded_reason or "insufficient PIT" in result.excluded_reason
                else "data_end"
            )
            exclusions[key] = exclusions.get(key, 0) + 1
        labeled.append(result)
    return LabelRun(
        spec_version=LABEL_VERSION,
        labels=tuple(labeled),
        n_excluded=sum(exclusions.values()),
        exclusion_reasons=exclusions,
    )


def overlap_intervals(labels: List[LabeledEvent]) -> List[Tuple[LabeledEvent, LabeledEvent, int]]:
    """Per-instrument event pairs whose [event, first_touch] intervals intersect.

    Contract item 5.4. Uses each event's effective interval end: the first
    touch bar when touched, else the vertical deadline. The overlap length
    is the number of shared calendar index positions, approximated here by
    bar counts between max(start) and min(end) inclusive; returns pairs with
    overlap >= 1 bar.
    """
    result: List[Tuple[LabeledEvent, LabeledEvent, int]] = []
    by_instrument: Dict[str, List[LabeledEvent]] = {}
    for lab in labels:
        by_instrument.setdefault(lab.event.instrument, []).append(lab)
    for inst_events in by_instrument.values():
        ordered = sorted(inst_events, key=lambda le: le.event.event_timestamp)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                a, b = ordered[i], ordered[j]
                start = max(a.event.event_timestamp, b.event.event_timestamp)
                ends = [
                    le.first_touch_timestamp if le.first_touch_timestamp is not None else le.vertical_deadline
                    for le in (a, b)
                ]
                end = min(ends)
                if start <= end:
                    overlap_days = (end - start).days  # calendar-day approximation, documented
                    result.append((a, b, overlap_days))
    return result


def average_uniqueness(labels: List[LabeledEvent], index: pd.DatetimeIndex) -> Dict[str, float]:
    """Per-event average uniqueness from concurrency (contract item 5.5).

    For each event, c_t = number of overlapping event intervals on the same
    instrument covering bar t; the event's uniqueness is mean(1/c_t) over
    the trading days its interval spans. Implemented fresh for R5-B (the
    platform has no AFML uniqueness module — see corrected R5-A table).
    """
    by_instrument: Dict[str, List[LabeledEvent]] = {}
    for lab in labels:
        by_instrument.setdefault(lab.event.instrument, []).append(lab)
    pos_of = {ts: i for i, ts in enumerate(index)}
    unique: Dict[str, float] = {}
    for inst_events in by_instrument.values():
        spans: List[Tuple[str, int, int]] = []
        for le in inst_events:
            start = pos_of.get(le.event.event_timestamp)
            end_ts = le.first_touch_timestamp if le.first_touch_timestamp is not None else le.vertical_deadline
            end = pos_of.get(end_ts)
            if start is None or end is None or end < start:
                continue
            spans.append((le.event.event_id, start, end))
        for event_id, start, end in spans:
            invs = []
            for t in range(start, end + 1):
                c_t = sum(1 for _, s, e in spans if s <= t <= e)
                invs.append(1.0 / c_t if c_t > 0 else 1.0)
            unique[event_id] = float(np.mean(invs)) if invs else 1.0
    return unique
