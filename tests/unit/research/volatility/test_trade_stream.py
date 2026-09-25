"""PIT replay invariants: no same-day lookahead, determinism, pairing."""

from __future__ import annotations

import pandas as pd
import pytest

from research.volatility import config as C
from research.volatility import trade_stream as TS


@pytest.fixture(scope="module")
def population():
    # CI checkouts have no data/ snapshot; the frozen exporter exits with
    # SystemExit when fewer than 2 symbols have local history. Skip there —
    # with the snapshot present, replay failures are real test failures.
    if not C.FROZEN_MANIFEST.exists():
        pytest.skip(f"local D1 snapshot not present (CI): {C.FROZEN_MANIFEST}")
    try:
        return TS.replay_pit_population()
    except SystemExit as exc:
        pytest.skip(f"insufficient local D1 history for replay: {exc}")


def test_population_count_and_symbols(population):
    trades, prov = population
    assert len(trades) == 1311
    assert prov["population"] == "PIT_R4_D1_REPLAY_V1"
    assert sorted(prov["n_by_symbol"]) == sorted(C.TRADE_SYMBOLS)


def test_no_lookahead_entry_strictly_after_signal(population):
    trades, _ = population
    for t in trades:
        assert t.entry_ts > t.signal_date, (
            f"trade {t.trade_id}: entry {t.entry_ts} not strictly after signal {t.signal_date}"
        )
        assert t.exit_ts >= t.entry_ts


def test_determinism_two_replays_identical(population):
    import math

    trades_a, _ = population
    trades_b, prov_b = TS.replay_pit_population()
    assert len(trades_b) == len(trades_a)
    for a, b in zip(trades_a, trades_b):
        assert a == b
        assert math.isfinite(a.entry_px) and math.isfinite(a.exit_px)
    assert prov_b["n_by_symbol"]


def test_costs_and_pnl_consistency(population):
    import math

    trades, _ = population
    for t in trades:
        assert math.isfinite(t.entry_px) and math.isfinite(t.exit_px)
        assert t.entry_px > 0 and t.exit_px > 0
        expected_costs = 2.0 * TS.C.R4_COST_ONE_WAY * abs(t.weight)
        assert t.costs == pytest.approx(expected_costs, rel=1e-12)
        gross = t.weight * (t.exit_px / t.entry_px - 1.0)
        assert t.net_pnl == pytest.approx(gross - t.costs, rel=1e-12, abs=1e-15)


def test_trade_ids_are_contiguous_after_sort(population):
    trades, _ = population
    ids = [t.trade_id for t in trades]
    assert ids == list(range(1, len(trades) + 1))
    exits = [t.exit_ts for t in trades]
    assert exits == sorted(exits)


def test_strict_next_day_helper():
    idx = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-05"])
    # same-day date -> next row (strict)
    assert TS._next_day_strict(idx, pd.Timestamp("2024-01-03")) == pd.Timestamp("2024-01-05")
    # weekend date -> first bar after it
    assert TS._next_day_strict(idx, pd.Timestamp("2024-01-04")) == pd.Timestamp("2024-01-05")
    # beyond end -> None
    assert TS._next_day_strict(idx, pd.Timestamp("2024-02-01")) is None
