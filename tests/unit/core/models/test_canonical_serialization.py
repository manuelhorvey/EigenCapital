"""Unit tests for canonical serialization utility.

Tests deterministic sorting, JSON output, hashing per Correction #9:
- sorted keys
- UTF-8
- explicit null handling
- ISO-8601 UTC timestamps
- stable enum representation
- normalized floating-point representation
- no unordered dict dependence
"""

import json

from eigencapital.core.models.canonical_serialization import (
    canonical_hash,
    canonical_hash_hex,
    canonical_json,
    canonical_sort,
)


def test_canonical_sort_nested_dict():
    """Test that keys are sorted at every level recursively."""
    data = {
        "z": {"c": 1, "a": 2},
        "a": {"m": 3, "b": 4},
    }
    result = canonical_sort(data)
    keys = list(result.keys())
    assert keys == ["a", "z"]
    assert list(result["a"].keys()) == ["b", "m"]
    assert list(result["z"].keys()) == ["a", "c"]


def test_canonical_sort_preserves_values():
    """Test that values are preserved unchanged."""
    data = {"b": 42, "a": "hello", "c": None, "d": 3.14}
    result = canonical_sort(data)
    assert result["a"] == "hello"
    assert result["b"] == 42
    assert result["c"] is None
    assert result["d"] == 3.14


def test_canonical_sort_lists_unchanged():
    """Test that lists are kept in order."""
    data = {"b": [3, 1, 2], "a": [1, 2, 3]}
    result = canonical_sort(data)
    assert result["a"] == [1, 2, 3]
    assert result["b"] == [3, 1, 2]


def test_canonical_sort_preserves_none():
    """EXPLICIT NULL HANDLING: None values included, not omitted."""
    data = {"a": None, "b": 1}
    result = canonical_sort(data)
    assert result["a"] is None
    # When serialized, None becomes JSON null
    j = canonical_json(data)
    assert "null" in j


def test_canonical_json_deterministic():
    """Test that canonical_json produces identical output for same data."""
    data = {"z": 1, "a": 2, "m": {"c": 3, "a": 1}}
    j1 = canonical_json(data)
    j2 = canonical_json(data)
    assert j1 == j2


def test_canonical_json_sorted_keys():
    """Test that JSON output has sorted keys."""
    data = {"z": 1, "a": 2}
    j = canonical_json(data)
    parsed = json.loads(j)
    assert list(parsed.keys()) == ["a", "z"]


def test_canonical_hash_deterministic():
    """Test that canonical_hash produces identical output for same data."""
    data = {"b": 1, "a": 2}
    h1 = canonical_hash(data)
    h2 = canonical_hash(data)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_canonical_hash_order_independent():
    """Test that hash is the same regardless of dict key order."""
    data1 = {"a": 1, "b": 2, "c": 3}
    data2 = {"c": 3, "a": 1, "b": 2}
    assert canonical_hash(data1) == canonical_hash(data2)


def test_canonical_hash_rejects_nan():
    """Test that NaN causes an error in canonical_json (allow_nan=False)."""
    data = {"a": float("nan")}
    try:
        canonical_json(data)
        raise AssertionError("Should reject NaN in JSON serialization")
    except ValueError:
        pass


def test_canonical_hash_hex_alias():
    """Test canonical_hash_hex is an alias."""
    data = {"a": 1}
    assert canonical_hash_hex(data) == canonical_hash(data)


def test_canonical_sort_empty():
    """Test canonical_sort on empty structures."""
    assert canonical_sort({}) == {}
    assert canonical_sort([]) == []
    assert canonical_sort(None) is None
    assert canonical_sort(42) == 42
    assert canonical_sort("hello") == "hello"
