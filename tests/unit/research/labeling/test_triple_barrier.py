"""Unit tests for R5 Phase B — triple-barrier labeling engine.

Covers the frozen R5 contract (docs/research/R5_TRIPLE_BARRIER.md):
- hand-computed first-touch resolution: PT first, SL first, same-bar double
  touch tie rule, vertical expiry (+1 / −1 / exact-equality 0), SHORT-side
  mirroring, multiplicative barrier distances (entry ± m · daily_vol · entry)
- the event bar itself is never scanned (scan starts at event+1)
- strict PIT vol: window excludes the event bar; violations exclude-and-count,
  never impute
- determinism: two identical runs are byte-identical (contract item 5.6)
- overlap pairing and average-uniqueness math against hand-computed values
- exclusions are counted by reason, never silently dropped (contract F4)

Vol fixture: 60 closes before the event bar with 58 zero returns and one
jump of r·sqrt(59) → std(returns, ddof=1) = r EXACTLY, so r = 0.10/sqrt(252)
gives an annualized PIT vol of exactly 10% at every event bar.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import pytest

from eigencapital.research.labeling import (
    ANNUALIZATION,
    Event,
    LabelingError,
    PitViolationError,
    average_uniqueness,
    build_labels,
    label_event,
    overlap_intervals,
    pit_daily_vol,
)

R_DAILY = 0.10 / math.sqrt(252.0)  # exact daily std target
EVENT_BAR = 60  # first bar with a full 60-close PIT window before it


def _vol_frame(n_after: int, closes_after: List[float] | None = None) -> pd.DataFrame:
    """OHLC frame whose PIT vol at bar EVENT_BAR is exactly 10% annualized.

    Bars 0..59: the PIT window — 58 flat closes, two closes at 100·(1+j)
    where j = R_DAILY·√59. The window's 59 returns are [0]*57 + [j, 0],
    whose std (ddof=1) is EXACTLY R_DAILY. Bar EVENT_BAR (=60) is the event
    bar; ``n_after`` bars follow it. Default flat tail keeps every bar's
    [low, high] = [99, 101] strictly inside the ±2·daily_vol·entry barriers
    (≈ [98.74, 101.26]) so nothing touches accidentally.
    """
    jump = R_DAILY * math.sqrt(59.0)
    pre = [100.0] * 58 + [100.0 * (1.0 + jump)] * 2  # exactly 60 pre-closes
    event_close = 100.0
    tail = closes_after if closes_after is not None else [100.0] * n_after
    closes = pre + [event_close] + list(tail)
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    arr = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": arr, "high": arr * 1.01, "low": arr * 0.99, "close": arr}, index=idx)


def _long_event(frame: pd.DataFrame, bar: int = EVENT_BAR, entry: float = 100.0, eid: str = "E1") -> Event:
    return Event(
        event_id=eid,
        instrument="TEST",
        decision_timestamp=frame.index[bar - 1],
        event_timestamp=frame.index[bar],
        side="LONG",
        entry_price=entry,
    )


def _barrier_prices(entry: float, daily_vol: float) -> Tuple[float, float]:
    dist = daily_vol * 2.0 * entry
    return entry + dist, entry - dist


# ── PIT vol ──────────────────────────────────────────────────────────────────


def test_pit_vol_value_is_hand_computed() -> None:
    frame = _vol_frame(6)
    vol = pit_daily_vol(frame["close"], frame.index[EVENT_BAR])
    assert math.isclose(vol, 0.10, rel_tol=1e-9)


def test_pit_vol_uses_only_data_before_the_event_bar() -> None:
    frame = _vol_frame(6)
    # Perturb everything AT and AFTER the event bar; the vol must not move.
    vol_before = pit_daily_vol(frame["close"], frame.index[EVENT_BAR])
    frame.iloc[EVENT_BAR:, :] = frame.iloc[EVENT_BAR:, :] * 3.0
    vol_after = pit_daily_vol(frame["close"], frame.index[EVENT_BAR])
    assert math.isclose(vol_before, vol_after, rel_tol=1e-12)


def test_pit_vol_raises_on_insufficient_history() -> None:
    frame = _vol_frame(6)
    with pytest.raises((PitViolationError, LabelingError)):
        pit_daily_vol(frame["close"], frame.index[5])


def test_flat_history_is_degenerate_and_refused() -> None:
    closes = [100.0] * 62
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    frame = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}, index=idx)
    with pytest.raises(PitViolationError, match="degenerate"):
        pit_daily_vol(frame["close"], idx[EVENT_BAR])


# ── First-touch resolution (LONG) ────────────────────────────────────────────


def test_long_pt_touched_first() -> None:
    frame = _vol_frame(12)
    pt, _sl = _barrier_prices(100.0, R_DAILY)
    frame.iloc[EVENT_BAR + 2, frame.columns.get_loc("high")] = pt  # touch PT at +2
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "PT"
    assert lab.first_touch_timestamp == frame.index[EVENT_BAR + 2]
    assert lab.label == 1
    assert lab.vol_observation_timestamp == frame.index[EVENT_BAR - 1]


def test_long_sl_touched_first() -> None:
    frame = _vol_frame(12)
    _pt, sl = _barrier_prices(100.0, R_DAILY)
    frame.iloc[EVENT_BAR + 1, frame.columns.get_loc("low")] = sl  # touch SL at +1
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "SL"
    assert lab.first_touch_timestamp == frame.index[EVENT_BAR + 1]
    assert lab.label == -1


def test_long_same_bar_double_touch_closer_to_open_wins() -> None:
    pt, sl = _barrier_prices(100.0, R_DAILY)
    span = pt - sl

    frame = _vol_frame(12)
    frame.iloc[EVENT_BAR + 3, frame.columns.get_loc("high")] = pt
    frame.iloc[EVENT_BAR + 3, frame.columns.get_loc("low")] = sl
    frame.iloc[EVENT_BAR + 3, frame.columns.get_loc("open")] = sl + 0.05 * span  # nearer SL
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "SL"
    assert lab.label == -1

    frame2 = _vol_frame(12)
    frame2.iloc[EVENT_BAR + 3, frame2.columns.get_loc("high")] = pt
    frame2.iloc[EVENT_BAR + 3, frame2.columns.get_loc("low")] = sl
    frame2.iloc[EVENT_BAR + 3, frame2.columns.get_loc("open")] = pt - 0.05 * span  # nearer PT
    lab2 = label_event(_long_event(frame2), frame2)
    assert lab2.first_touch_type == "PT"
    assert lab2.label == 1


def test_long_vertical_expiry_positive() -> None:
    # 9 gentle tail bars (highs 101.101 < PT 101.26, lows > SL) then +10 close
    # at 100.2 > entry → favorable vertical expiry, no touch anywhere.
    tail = [100.1] * 9 + [100.2]
    frame = _vol_frame(10, closes_after=tail)
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "VERTICAL"
    assert lab.vertical_deadline == frame.index[EVENT_BAR + 10]
    assert lab.label == 1


def test_vertical_expiry_exact_equality_labels_zero() -> None:
    frame = _vol_frame(12)  # flat tail: close(+10) == entry exactly
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "VERTICAL"
    assert lab.label == 0


def test_event_bar_itself_is_never_scanned() -> None:
    frame = _vol_frame(12)
    pt, _sl = _barrier_prices(100.0, R_DAILY)
    frame.iloc[EVENT_BAR, frame.columns.get_loc("high")] = pt  # PT "touched" ON the event bar
    lab = label_event(_long_event(frame), frame)
    assert lab.first_touch_type == "VERTICAL"  # event-bar touch ignored
    assert lab.label == 0


# ── SHORT mirroring ──────────────────────────────────────────────────────────


def test_short_sl_is_above_entry_and_mirrors() -> None:
    frame = _vol_frame(12)
    dist = R_DAILY * 2.0 * 100.0
    short_event = Event("S1", "TEST", frame.index[EVENT_BAR - 1], frame.index[EVENT_BAR], "SHORT", 100.0)

    frame.iloc[EVENT_BAR + 1, frame.columns.get_loc("high")] = 100.0 + dist  # SHORT SL above entry
    lab = label_event(short_event, frame)
    assert lab.pt_price < 100.0 < lab.sl_price  # mirrored geometry
    assert lab.first_touch_type == "SL"
    assert lab.label == -1

    frame2 = _vol_frame(10, closes_after=[100.1] * 9 + [100.2])
    lab2 = label_event(
        Event("S2", "TEST", frame2.index[EVENT_BAR - 1], frame2.index[EVENT_BAR], "SHORT", 100.0),
        frame2,
    )
    assert lab2.first_touch_type == "VERTICAL"
    assert lab2.label == -1  # close(+10) ABOVE entry is unfavorable for SHORT


# ── Determinism, exclusions, batching ────────────────────────────────────────


def test_determinism_byte_identical() -> None:
    frame = _vol_frame(12)
    events = [_long_event(frame)]
    r1, r2 = build_labels(events, {"TEST": frame}), build_labels(events, {"TEST": frame})
    assert r1 == r2
    assert repr(r1) == repr(r2)


def test_insufficient_history_is_excluded_and_counted_not_imputed() -> None:
    frame = _vol_frame(12)
    early = Event("E0", "TEST", frame.index[1], frame.index[2], "LONG", 100.0)
    run = build_labels([early], {"TEST": frame})
    assert run.n_excluded == 1
    assert run.exclusion_reasons.get("pit_history") == 1
    lab = run.labels[0]
    assert lab.excluded_reason != ""
    assert lab.first_touch_timestamp is None


def test_data_end_is_excluded_and_counted() -> None:
    frame = _vol_frame(3)  # only 3 bars after the event bar
    run = build_labels([_long_event(frame)], {"TEST": frame})
    assert run.n_excluded == 1
    assert run.exclusion_reasons.get("data_end") == 1


def test_unknown_instrument_raises() -> None:
    frame = _vol_frame(12)
    with pytest.raises(LabelingError, match="no price data"):
        build_labels([_long_event(frame)], {"OTHER": frame})


def test_multiplicative_barriers_match_ledger_formula() -> None:
    frame = _vol_frame(12)
    lab = label_event(_long_event(frame), frame)
    assert math.isclose(lab.pt_price, 100.0 * (1.0 + 2.0 * R_DAILY), rel_tol=1e-9)
    assert math.isclose(lab.sl_price, 100.0 * (1.0 - 2.0 * R_DAILY), rel_tol=1e-9)


def test_stored_vol_is_annualized_and_barriers_use_the_deflated_value() -> None:
    frame = _vol_frame(12)
    lab = label_event(_long_event(frame), frame)
    assert math.isclose(lab.daily_vol, 0.10, rel_tol=1e-9)  # stored annualized
    assert math.isclose(lab.pt_price - 100.0, (0.10 / ANNUALIZATION) * 2.0 * 100.0, rel_tol=1e-9)


# ── Overlap + uniqueness (hand-computed) ─────────────────────────────────────


def _overlap_fixture() -> Tuple[List[Event], pd.DatetimeIndex, Dict[str, pd.DataFrame]]:
    frame = _vol_frame(30)  # bars 61..90 after the event bar
    ev_a = _long_event(frame, EVENT_BAR, 100.0, "A")  # interval 60..70 (vertical)
    ev_b = _long_event(frame, EVENT_BAR + 5, 100.0, "B")  # interval 65..75, inside A's span
    ev_c = _long_event(frame, EVENT_BAR + 16, 100.0, "C")  # interval 76..86, after both
    return [ev_a, ev_b, ev_c], frame.index, {"TEST": frame}


def test_overlap_pairs_only_intersecting_intervals() -> None:
    events, _index, bars = _overlap_fixture()
    run = build_labels(events, bars)
    pairs = overlap_intervals(list(run.labels))
    paired_ids = {frozenset((a.event.event_id, b.event.event_id)) for a, b, _ in pairs}
    assert frozenset(("A", "B")) in paired_ids  # B starts inside A's interval
    assert frozenset(("A", "C")) not in paired_ids
    assert frozenset(("B", "C")) not in paired_ids


def test_average_uniqueness_hand_computed() -> None:
    events, index, bars = _overlap_fixture()
    run = build_labels(events, bars)
    uniq = average_uniqueness(list(run.labels), index)
    # A: bars 60..70 → 5 alone (60–64) + 6 shared with B (65–70)
    assert math.isclose(uniq["A"], (5 * 1.0 + 6 * 0.5) / 11.0, rel_tol=1e-6)
    # B: bars 65..75 → 6 shared with A (65–70) + 5 alone (71–75)
    assert math.isclose(uniq["B"], (6 * 0.5 + 5 * 1.0) / 11.0, rel_tol=1e-6)
    # C: alone for its whole interval
    assert math.isclose(uniq["C"], 1.0, rel_tol=1e-6)


def test_uniqueness_degenerate_single_event_is_one() -> None:
    frame = _vol_frame(12)
    run = build_labels([_long_event(frame)], {"TEST": frame})
    uniq = average_uniqueness(list(run.labels), frame.index)
    assert math.isclose(uniq["E1"], 1.0, rel_tol=1e-9)
