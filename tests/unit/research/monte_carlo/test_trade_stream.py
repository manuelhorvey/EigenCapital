"""Unit tests for the R1 Phase A trade-stream schema, persistence and adapter.

Covers the "boring first commit" contract from the R1 handoff:
- deterministic canonical round-trip (save → load → identical provenance)
- deterministic serialization (byte-identical files for identical content)
- strict invariants (contiguity, monotonic exits, closed trades, finiteness)
- tamper detection at load time
- conservative BacktestResults fill_events pairing
"""

import json
from pathlib import Path

import pytest

from eigencapital.research.monte_carlo.adapter import backtest_results_to_trade_stream
from eigencapital.research.monte_carlo.persistence import (
    load_trade_stream,
    save_trade_stream,
)
from eigencapital.research.monte_carlo.schema import (
    TradeRecord,
    TradeStream,
    TradeStreamError,
)


def _make_trade(trade_index: int = 1, pnl: float = 100.0, **overrides) -> TradeRecord:
    defaults = dict(
        trade_index=trade_index,
        instrument="EURUSD",
        entry_timestamp=f"2026-01-0{max(1, trade_index)}T10:00:00Z",
        exit_timestamp=f"2026-01-0{max(1, trade_index)}T15:00:00Z",
        side="LONG",
        realized_pnl=pnl,
        return_r=None,
        costs_paid=2.5,
        metadata={},
    )
    defaults.update(overrides)
    return TradeRecord(**defaults)


def _make_stream(n_trades: int = 3, **overrides) -> TradeStream:
    trades = tuple(_make_trade(trade_index=i, pnl=100.0 * i) for i in range(1, n_trades + 1))
    defaults = dict(
        stream_id="TS-R4-DAILY-0001",
        experiment_id="EXP-000001",
        strategy_id="R4",
        strategy_version="v4.0",
        dataset_id="fx_daily",
        dataset_version="2026.09",
        git_commit="0b297a9",
        cost_model_id="realistic_v1",
        cost_model_version="v1",
        trades=trades,
    )
    defaults.update(overrides)
    return TradeStream(**defaults)


def _make_fills(n_trades: int = 2, commission: float = 1.0, fees: float = 0.5):
    """Alternating BUY/SELL fill events like BacktestResults.fill_events."""
    fills = []
    for i in range(1, n_trades + 1):
        day = max(1, i)
        fills.append(
            {
                "timestamp": f"2026-02-0{day}T10:00:00Z",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 1.1000 + i,
                "commission": commission,
                "fees": fees,
            }
        )
        fills.append(
            {
                "timestamp": f"2026-02-0{day}T16:00:00Z",
                "side": "SELL",
                "quantity": 1.0,
                "fill_price": 1.1050 + i,
                "commission": commission,
                "fees": fees,
            }
        )
    return fills


class TestTradeRecord:
    def test_creation_and_defaults(self):
        t = _make_trade()
        assert t.trade_index == 1
        assert t.side == "LONG"
        assert t.return_r is None

    def test_side_must_be_valid(self):
        with pytest.raises(TradeStreamError, match="side"):
            _make_trade(side="FLAT")

    def test_entry_must_not_precede_exit(self):
        with pytest.raises(TradeStreamError, match="entry_timestamp"):
            _make_trade(entry_timestamp="2026-01-02T00:00:00Z", exit_timestamp="2026-01-01T00:00:00Z")

    def test_timestamps_must_be_iso8601(self):
        with pytest.raises(TradeStreamError, match="ISO-8601"):
            _make_trade(entry_timestamp="20260101")

    def test_costs_non_negative(self):
        with pytest.raises(TradeStreamError, match="costs_paid"):
            _make_trade(costs_paid=-1.0)

    def test_pnl_must_be_finite(self):
        with pytest.raises(TradeStreamError, match="finite"):
            _make_trade(pnl=float("nan"))

    def test_strict_from_dict_rejects_unknown_keys(self):
        d = _make_trade().to_dict()
        d["bogus"] = 1
        with pytest.raises(TradeStreamError, match="unknown TradeRecord field"):
            TradeRecord.from_dict(d)

    def test_strict_from_dict_requires_all_keys(self):
        d = _make_trade().to_dict()
        del d["costs_paid"]
        with pytest.raises(TradeStreamError, match="missing TradeRecord field"):
            TradeRecord.from_dict(d)


class TestTradeStream:
    def test_provenance_hash_deterministic(self):
        s1 = _make_stream()
        s2 = _make_stream()
        assert s1.provenance_hash == s2.provenance_hash
        assert len(s1.provenance_hash) == 64

    def test_hash_changes_with_content(self):
        s1 = _make_stream()
        s2 = _make_stream(trades=tuple(_make_trade(trade_index=i, pnl=1.0) for i in range(1, 4)))
        assert s1.provenance_hash != s2.provenance_hash

    def test_indices_must_be_contiguous_in_order(self):
        trades = (_make_trade(trade_index=2), _make_trade(trade_index=1))
        with pytest.raises(TradeStreamError, match="contiguous"):
            _make_stream(trades=trades)

    def test_exit_timestamps_monotonic(self):
        trades = (
            _make_trade(trade_index=1, exit_timestamp="2026-01-05T00:00:00Z"),
            _make_trade(trade_index=2, exit_timestamp="2026-01-03T00:00:00Z"),
        )
        with pytest.raises(TradeStreamError, match="monotonic"):
            _make_stream(trades=trades)

    def test_empty_stream_rejected(self):
        with pytest.raises(TradeStreamError, match="non-empty"):
            _make_stream(trades=())

    def test_identity_fields_required(self):
        with pytest.raises(TradeStreamError, match="stream_id"):
            _make_stream(stream_id="")

    def test_verify_provenance_hash(self):
        s = _make_stream()
        assert s.verify_provenance_hash(s.provenance_hash)
        assert not s.verify_provenance_hash("0" * 64)

    def test_round_trip_via_dict(self):
        s = _make_stream()
        s2 = TradeStream.from_dict(s.to_dict())
        assert s2 == s
        assert s2.provenance_hash == s.provenance_hash


class TestPersistence:
    def test_save_load_round_trip(self, tmp_path: Path):
        s = _make_stream()
        path = tmp_path / "streams" / "TS-R4-DAILY-0001.json"
        written = save_trade_stream(s, path)
        assert written == path
        loaded = load_trade_stream(path)
        assert loaded == s
        assert loaded.provenance_hash == s.provenance_hash

    def test_serialization_is_deterministic(self, tmp_path: Path):
        s = _make_stream()
        p1 = save_trade_stream(s, tmp_path / "a.json")
        p2 = save_trade_stream(_make_stream(), tmp_path / "b.json")
        assert p1.read_bytes() == p2.read_bytes()

    def test_tamper_detection_value_edit(self, tmp_path: Path):
        s = _make_stream()
        path = save_trade_stream(s, tmp_path / "s.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["trades"][0]["realized_pnl"] = 999999.0
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TradeStreamError, match="provenance hash mismatch"):
            load_trade_stream(path)

    def test_tamper_detection_trade_removal(self, tmp_path: Path):
        s = _make_stream(n_trades=3)
        path = save_trade_stream(s, tmp_path / "s.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["trades"] = data["trades"][:2]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TradeStreamError):
            load_trade_stream(path)

    def test_tamper_detection_trade_reorder(self, tmp_path: Path):
        s = _make_stream(n_trades=3)
        path = save_trade_stream(s, tmp_path / "s.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["trades"] = list(reversed(data["trades"]))
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TradeStreamError):
            load_trade_stream(path)

    def test_malformed_json_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(TradeStreamError, match="unreadable"):
            load_trade_stream(path)

    def test_missing_file_rejected(self, tmp_path: Path):
        with pytest.raises(TradeStreamError, match="not found"):
            load_trade_stream(tmp_path / "nope.json")

    def test_save_refuses_hash_mismatch(self, tmp_path: Path):
        s = _make_stream()
        tampered = TradeStream(
            stream_id=s.stream_id,
            experiment_id=s.experiment_id,
            strategy_id=s.strategy_id,
            strategy_version=s.strategy_version,
            dataset_id=s.dataset_id,
            dataset_version=s.dataset_version,
            git_commit=s.git_commit,
            cost_model_id=s.cost_model_id,
            cost_model_version=s.cost_model_version,
            trades=s.trades,
            provenance_hash="f" * 64,
        )
        with pytest.raises(TradeStreamError, match="refusing to save"):
            save_trade_stream(tampered, tmp_path / "s.json")


class TestAdapter:
    def test_basic_pairing(self):
        fills = _make_fills(n_trades=2)
        stream = backtest_results_to_trade_stream(
            fills,
            per_trade_pnl=[150.0, -50.0],
            stream_id="TS-TEST",
            experiment_id="EXP-000001",
            strategy_id="R4",
            strategy_version="v4.0",
            dataset_id="fx_daily",
            dataset_version="2026.09",
            instrument="EURUSD",
        )
        assert len(stream.trades) == 2
        assert stream.trades[0].side == "LONG"
        assert stream.trades[0].realized_pnl == 150.0
        assert stream.trades[1].realized_pnl == -50.0
        # default costs = commission + fees on both fills
        assert stream.trades[0].costs_paid == pytest.approx(2 * (1.0 + 0.5))
        assert stream.provenance_hash  # computed on construction

    def test_short_pairing(self):
        fills = [
            {
                "timestamp": "2026-03-01T10:00:00Z",
                "side": "SELL",
                "quantity": 1.0,
                "fill_price": 1.2,
                "commission": 1.0,
                "fees": 0.0,
            },
            {
                "timestamp": "2026-03-01T16:00:00Z",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 1.19,
                "commission": 1.0,
                "fees": 0.0,
            },
        ]
        stream = backtest_results_to_trade_stream(
            fills,
            per_trade_pnl=[10.0],
            stream_id="TS-TEST",
            experiment_id="E",
            strategy_id="R4",
            strategy_version="v4.0",
            dataset_id="d",
            dataset_version="1",
            instrument="EURUSD",
        )
        assert stream.trades[0].side == "SHORT"

    def test_odd_fills_rejected(self):
        fills = _make_fills(n_trades=1) + [_make_fills(n_trades=1)[0]]
        with pytest.raises(TradeStreamError, match="odd length"):
            backtest_results_to_trade_stream(
                fills,
                [0.0],
                stream_id="T",
                experiment_id="E",
                strategy_id="R4",
                strategy_version="v",
                dataset_id="d",
                dataset_version="1",
            )

    def test_unmatched_trailing_fill_rejected(self):
        fills = _make_fills(n_trades=1)
        fills = fills[:-1]  # drop the closing SELL
        with pytest.raises(TradeStreamError, match=r"odd length|unmatched"):
            backtest_results_to_trade_stream(
                fills,
                [],
                stream_id="T",
                experiment_id="E",
                strategy_id="R4",
                strategy_version="v",
                dataset_id="d",
                dataset_version="1",
            )

    def test_pyramiding_rejected(self):
        fills = [
            {
                "timestamp": "2026-03-01T10:00:00Z",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 1.1,
                "commission": 0.0,
                "fees": 0.0,
            },
            {
                "timestamp": "2026-03-01T11:00:00Z",
                "side": "BUY",
                "quantity": 1.0,
                "fill_price": 1.1,
                "commission": 0.0,
                "fees": 0.0,
            },
            {
                "timestamp": "2026-03-01T16:00:00Z",
                "side": "SELL",
                "quantity": 1.0,
                "fill_price": 1.2,
                "commission": 0.0,
                "fees": 0.0,
            },
            {
                "timestamp": "2026-03-01T17:00:00Z",
                "side": "SELL",
                "quantity": 1.0,
                "fill_price": 1.2,
                "commission": 0.0,
                "fees": 0.0,
            },
        ]
        with pytest.raises(TradeStreamError, match=r"pyramiding|round-trip is open"):
            backtest_results_to_trade_stream(
                fills,
                [1.0, 1.0],
                stream_id="T",
                experiment_id="E",
                strategy_id="R4",
                strategy_version="v",
                dataset_id="d",
                dataset_version="1",
                instrument="EURUSD",
            )

    def test_pnl_length_mismatch_rejected(self):
        with pytest.raises(TradeStreamError, match="per_trade_pnl length"):
            backtest_results_to_trade_stream(
                _make_fills(n_trades=2),
                [1.0],
                stream_id="T",
                experiment_id="E",
                strategy_id="R4",
                strategy_version="v",
                dataset_id="d",
                dataset_version="1",
            )

    def test_missing_instrument_rejected(self):
        with pytest.raises(TradeStreamError, match="instrument"):
            backtest_results_to_trade_stream(
                _make_fills(n_trades=1),
                [10.0],
                stream_id="T",
                experiment_id="E",
                strategy_id="R4",
                strategy_version="v",
                dataset_id="d",
                dataset_version="1",
            )

    def test_explicit_costs_override(self):
        stream = backtest_results_to_trade_stream(
            _make_fills(n_trades=1),
            per_trade_pnl=[10.0],
            per_trade_costs=[7.5],
            stream_id="T",
            experiment_id="E",
            strategy_id="R4",
            strategy_version="v",
            dataset_id="d",
            dataset_version="1",
            instrument="EURUSD",
        )
        assert stream.trades[0].costs_paid == 7.5

    def test_full_round_trip_from_fills(self, tmp_path: Path):
        fills = _make_fills(n_trades=3)
        stream = backtest_results_to_trade_stream(
            fills,
            per_trade_pnl=[10.0, -5.0, 20.0],
            stream_id="TS-RT",
            experiment_id="EXP-000001",
            strategy_id="R4",
            strategy_version="v4.0",
            dataset_id="fx_daily",
            dataset_version="2026.09",
            instrument="EURUSD",
            git_commit="0b297a9",
        )
        path = save_trade_stream(stream, tmp_path / "rt.json")
        loaded = load_trade_stream(path)
        assert loaded == stream
        assert [t.realized_pnl for t in loaded.trades] == [10.0, -5.0, 20.0]
