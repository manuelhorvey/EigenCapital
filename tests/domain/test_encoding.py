"""Tests for eigencapital.domain.encoding — custom JSON encoder."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pytest

from eigencapital.domain.encoding import EigenCapitalJSONEncoder, eigencapital_json_dumps


class TestEigenCapitalJSONEncoder:
    """Cover all known types and the graceful fallback."""

    def test_datetime_serializes_to_iso(self):
        dt = datetime(2026, 7, 6, 20, 46, 37, tzinfo=timezone.utc)
        result = json.dumps({"ts": dt}, cls=EigenCapitalJSONEncoder)
        assert '"ts": "2026-07-06T20:46:37+00:00"' in result

    def test_date_serializes_to_iso(self):
        d = date(2026, 7, 6)
        result = json.dumps({"d": d}, cls=EigenCapitalJSONEncoder)
        assert '"d": "2026-07-06"' in result

    @pytest.mark.parametrize("val", [Decimal("10.5"), Decimal("0"), Decimal("-3.14159")])
    def test_decimal_serializes_to_float(self, val):
        result = json.dumps({"v": val}, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert isinstance(parsed["v"], float)
        assert parsed["v"] == float(val)

    @pytest.mark.parametrize(
        "val, expected_type",
        [
            (np.int8(42), int),
            (np.int16(42), int),
            (np.int32(42), int),
            (np.int64(42), int),
            (np.uint8(42), int),
            (np.float16(3.14), float),
            (np.float32(3.14), float),
            (np.float64(3.14), float),
            (np.bool_(True), bool),
            (np.bool_(False), bool),
        ],
    )
    def test_numpy_scalar_serializes(self, val, expected_type):
        result = json.dumps({"v": val}, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert isinstance(parsed["v"], expected_type)

    def test_numpy_ndarray_serializes_to_list(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = json.dumps({"v": arr}, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert parsed["v"] == [1.0, 2.0, 3.0]

    def test_numpy_2d_ndarray(self):
        arr = np.array([[1, 2], [3, 4]])
        result = json.dumps({"v": arr}, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert parsed["v"] == [[1, 2], [3, 4]]

    def test_nested_mixed_structure(self):
        """Trade-log-like structure with datetime and Decimal in nested dicts."""
        obj = {
            "asset": "EURUSD",
            "entry_date": datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc),
            "exit_date": datetime(2026, 7, 6, 14, 30, 0, tzinfo=timezone.utc),
            "pnl": Decimal("1.5"),
            "confidence": np.float64(0.85),
            "feature_importance": np.array([0.1, 0.2, 0.3]),
            "is_valid": np.bool_(True),
        }
        result = json.dumps(obj, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert parsed["asset"] == "EURUSD"
        assert parsed["entry_date"] == "2026-07-06T12:00:00+00:00"
        assert parsed["exit_date"] == "2026-07-06T14:30:00+00:00"
        assert parsed["pnl"] == 1.5
        assert parsed["confidence"] == 0.85
        assert parsed["feature_importance"] == [0.1, 0.2, 0.3]
        assert parsed["is_valid"] is True

    def test_unknown_type_falls_back_to_str(self):
        """Any non-handled type should be stringified instead of crashing."""

        class _Custom:
            def __str__(self):
                return "custom_fallback"

        obj = {"v": _Custom()}
        result = json.dumps(obj, cls=EigenCapitalJSONEncoder)
        assert '"v": "custom_fallback"' in result

    def test_none_handled_normally(self):
        result = json.dumps({"v": None}, cls=EigenCapitalJSONEncoder)
        assert '"v": null' in result

    def test_list_of_mixed_types(self):
        """Simulation snapshot trade_log structure."""
        logs = [
            {"exit_date": datetime(2026, 7, 6, 20, 46, 37, tzinfo=timezone.utc), "pnl": 0.5},
            {"exit_date": datetime(2026, 7, 6, 21, 0, 0, tzinfo=timezone.utc), "pnl": -0.3},
        ]
        result = json.dumps(logs, cls=EigenCapitalJSONEncoder)
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["exit_date"] == "2026-07-06T20:46:37+00:00"
        assert parsed[1]["exit_date"] == "2026-07-06T21:00:00+00:00"

    def test_naive_datetime(self):
        """Naive datetimes (no tzinfo) should also serialize."""
        dt = datetime(2026, 7, 6, 20, 46, 37)
        result = json.dumps({"ts": dt}, cls=EigenCapitalJSONEncoder)
        assert '"ts": "2026-07-06T20:46:37"' in result


class TestEigencapitalJsonDumps:
    """Convenience wrapper function."""

    def test_basic_usage(self):
        data = {"hello": "world"}
        result = eigencapital_json_dumps(data)
        parsed = json.loads(result)
        assert parsed["hello"] == "world"

    def test_accepts_kwargs(self):
        result = eigencapital_json_dumps({"a": 1}, indent=4)
        assert result.startswith("{\n    ")

    def test_with_datetime(self):
        dt = datetime(2026, 7, 6, tzinfo=timezone.utc)
        result = eigencapital_json_dumps({"ts": dt})
        assert json.loads(result)["ts"] == "2026-07-06T00:00:00+00:00"

    def test_with_decimal(self):
        result = eigencapital_json_dumps({"v": Decimal("2.5")})
        assert json.loads(result)["v"] == 2.5

    def test_with_numpy(self):
        result = eigencapital_json_dumps({"v": np.float64(3.14)})
        assert json.loads(result)["v"] == 3.14

    def test_fallback_stringifies_unknown(self):
        class _X:
            def __str__(self):
                return "fallback"

        result = eigencapital_json_dumps({"v": _X()})
        assert json.loads(result)["v"] == "fallback"
