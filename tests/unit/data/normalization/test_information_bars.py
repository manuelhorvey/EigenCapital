"""Tests for information-driven bars (volume / notional aggregation)."""

import math

import pytest

from eigencapital.data.loaders.base import RawRecord
from eigencapital.data.normalization.information_bars import (
    InformationBar,
    InformationBarError,
    NotionalBarAggregator,
    TradeTick,
    VolumeBarAggregator,
)


def _tick(ts: str, price: float, volume: int) -> TradeTick:
    return TradeTick(timestamp_utc=ts, price=price, volume=volume)


class TestTradeTick:
    """TradeTick invariants."""

    def test_valid_tick(self):
        tick = _tick("2026-01-05T09:30:01Z", 100.0, 10)
        assert tick.price == 100.0

    def test_non_positive_price_rejected(self):
        with pytest.raises(InformationBarError):
            _tick("2026-01-05T09:30:01Z", 0.0, 10)
        with pytest.raises(InformationBarError):
            _tick("2026-01-05T09:30:01Z", -5.0, 10)

    def test_nan_price_rejected(self):
        with pytest.raises(InformationBarError):
            _tick("2026-01-05T09:30:01Z", float("nan"), 10)

    def test_non_positive_volume_rejected(self):
        with pytest.raises(InformationBarError):
            _tick("2026-01-05T09:30:01Z", 100.0, 0)
        with pytest.raises(InformationBarError):
            _tick("2026-01-05T09:30:01Z", 100.0, -3)

    def test_empty_timestamp_rejected(self):
        with pytest.raises(InformationBarError):
            _tick("", 100.0, 1)

    def test_from_raw_record(self):
        record = RawRecord(
            source="test",
            instrument_id="ES",
            timestamp="2026-01-05T09:30:01Z",
            data={"price": "4500.25", "volume": "7"},
        )
        tick = TradeTick.from_raw_record(record)
        assert tick.price == pytest.approx(4500.25)
        assert tick.volume == 7

    def test_from_raw_record_size_alias(self):
        record = RawRecord(
            source="test",
            instrument_id="ES",
            timestamp="2026-01-05T09:30:01Z",
            data={"price": 100.0, "size": 4},
        )
        assert TradeTick.from_raw_record(record).volume == 4

    def test_from_raw_record_invalid_raises(self):
        record = RawRecord(
            source="test",
            instrument_id="ES",
            timestamp="2026-01-05T09:30:01Z",
            data={"price": None},
        )
        with pytest.raises(InformationBarError):
            TradeTick.from_raw_record(record)


class TestVolumeBars:
    """Volume-threshold bar construction."""

    def test_exact_threshold_closes_bars(self):
        agg = VolumeBarAggregator(instrument_id="ES", threshold_volume=100)
        ticks = [_tick(f"2026-01-05T09:{m:02d}:00Z", 100.0 + m, 50) for m in range(6)]
        bars = agg.aggregate(ticks)
        assert len(bars) == 3
        assert all(b.complete for b in bars)
        assert all(b.volume == 100 for b in bars)
        assert all(b.trade_count == 2 for b in bars)

    def test_partial_final_bar_flagged_incomplete(self):
        agg = VolumeBarAggregator(instrument_id="ES", threshold_volume=100)
        ticks = [
            _tick("2026-01-05T09:30:00Z", 100.0, 60),
            _tick("2026-01-05T09:30:01Z", 101.0, 60),
            _tick("2026-01-05T09:30:02Z", 102.0, 10),
        ]
        bars = agg.aggregate(ticks)
        assert len(bars) == 2
        assert bars[0].complete and bars[0].volume == 120
        assert not bars[1].complete and bars[1].volume == 10

    def test_ohlc_vwap_from_ticks(self):
        agg = VolumeBarAggregator(instrument_id="ES", threshold_volume=300)
        ticks = [
            _tick("2026-01-05T09:30:00Z", 100.0, 100),
            _tick("2026-01-05T09:30:01Z", 110.0, 100),
            _tick("2026-01-05T09:30:02Z", 90.0, 100),
        ]
        (bar,) = agg.aggregate(ticks)
        assert bar.open == 100.0
        assert bar.close == 90.0
        assert bar.high == 110.0
        assert bar.low == 90.0
        expected_vwap = (100 * 100 + 110 * 100 + 90 * 100) / 300
        assert bar.vwap == pytest.approx(expected_vwap)
        assert bar.notional == pytest.approx(100 * (100 + 110 + 90))
        assert low_high_ok(bar)


def low_high_ok(bar: InformationBar) -> bool:
    return bar.low <= bar.vwap <= bar.high


class TestNotionalBars:
    """Notional-threshold (asset-agnostic dollar) bars."""

    def test_threshold_respected(self):
        agg = NotionalBarAggregator(instrument_id="ES", threshold_notional=10_000)
        ticks = [_tick("2026-01-05T09:30:00Z", 50.0, 150)]  # 7500
        ticks.append(_tick("2026-01-05T09:30:01Z", 60.0, 50))  # 3000 -> 10500
        bars = agg.aggregate(ticks)
        assert len(bars) == 1
        assert bars[0].complete
        assert bars[0].notional >= 10_000

    def test_volume_conservation_across_all_bars(self):
        agg = NotionalBarAggregator(instrument_id="ES", threshold_notional=5_000)
        ticks = [
            _tick("2026-01-05T09:30:00Z", 10.0, 20),  # 200
            _tick("2026-01-05T09:30:01Z", 12.0, 500),  # 6000 -> close
            _tick("2026-01-05T09:30:02Z", 11.0, 100),  # 1100
            _tick("2026-01-05T09:30:03Z", 9.0, 700),  # 6300 -> close
            _tick("2026-01-05T09:30:04Z", 15.0, 40),  # partial 600
        ]
        bars = agg.aggregate(ticks)
        total_volume = sum(b.volume for b in bars)
        total_notional = sum(b.notional for b in bars)
        expected_notional = sum(t.price * t.volume for t in ticks)
        assert total_volume == 20 + 500 + 100 + 700 + 40
        assert total_notional == pytest.approx(expected_notional)

    def test_out_of_order_ticks_raise(self):
        agg = VolumeBarAggregator(instrument_id="ES", threshold_volume=10)
        ticks = [
            _tick("2026-01-05T09:30:02Z", 100.0, 5),
            _tick("2026-01-05T09:30:00Z", 100.0, 5),
        ]
        with pytest.raises(InformationBarError, match="Out-of-order"):
            agg.aggregate(ticks)

    def test_invalid_thresholds_rejected(self):
        with pytest.raises(InformationBarError):
            VolumeBarAggregator(instrument_id="ES", threshold_volume=0)
        with pytest.raises(InformationBarError):
            NotionalBarAggregator(instrument_id="ES", threshold_notional=-1)

    def test_empty_stream_no_bars(self):
        agg = VolumeBarAggregator(instrument_id="ES", threshold_volume=10)
        assert agg.aggregate([]) == []

    def test_invalid_instrument_id_rejected(self):
        with pytest.raises(InformationBarError):
            VolumeBarAggregator(instrument_id="", threshold_volume=10)


class TestInformationBarModel:
    """InformationBar invariants and serialization."""

    def _bar(self, **overrides):
        defaults = dict(
            instrument_id="ES",
            bar_type="volume",
            threshold=100.0,
            timestamp_open_utc="2026-01-05T09:30:00Z",
            timestamp_close_utc="2026-01-05T09:31:00Z",
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            vwap=102.0,
            volume=250,
            trade_count=3,
            notional=25_500.0,
            complete=True,
        )
        defaults.update(overrides)
        return InformationBar(**defaults)

    def test_vwap_outside_range_rejected(self):
        with pytest.raises(InformationBarError):
            self._bar(vwap=200.0)

    def test_bad_bar_type_rejected(self):
        with pytest.raises(InformationBarError):
            self._bar(bar_type="time")

    def test_close_before_open_rejected(self):
        with pytest.raises(InformationBarError):
            self._bar(
                timestamp_open_utc="2026-01-05T09:31:00Z",
                timestamp_close_utc="2026-01-05T09:30:00Z",
            )

    def test_high_low_hierarchy_enforced(self):
        with pytest.raises(InformationBarError):
            self._bar(high=90.0)
        with pytest.raises(InformationBarError):
            self._bar(low=120.0)

    def test_to_dict_round_stable(self):
        d1 = self._bar().to_dict()
        d2 = InformationBar(**self._bar().to_dict()).to_dict()
        assert d1 == d2
        assert math.isfinite(d1["vwap"])
