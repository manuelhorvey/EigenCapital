"""Tests for tools/config_diff — YAML diff between configuration files."""

import json
import tempfile

import yaml

from tools.config_diff import _flatten, diff, format_text, format_json


class TestFlatten:
    def test_simple_dict(self):
        result = _flatten({"a": 1, "b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested_dict(self):
        result = _flatten({"a": {"b": 1, "c": 2}})
        assert result == {"a.b": 1, "a.c": 2}

    def test_deeply_nested(self):
        result = _flatten({"a": {"b": {"c": 3}}})
        assert result == {"a.b.c": 3}

    def test_empty_dict(self):
        assert _flatten({}) == {}

    def test_with_prefix(self):
        result = _flatten({"x": 1}, prefix="root")
        assert result == {"root.x": 1}


class TestDiff:
    def test_identical_dicts(self):
        assert diff({"a": 1}, {"a": 1}) == {}

    def test_single_value_change(self):
        result = diff({"a": 1}, {"a": 2})
        assert "a" in result
        assert result["a"] == (1, 2)

    def test_key_added(self):
        result = diff({"a": 1}, {"a": 1, "b": 2})
        assert "b" in result
        assert result["b"] == (None, 2)

    def test_key_removed(self):
        result = diff({"a": 1, "b": 2}, {"a": 1})
        assert "b" in result
        assert result["b"] == (2, None)

    def test_nested_change(self):
        result = diff({"a": {"b": 1}}, {"a": {"b": 2}})
        assert "a.b" in result

    def test_multiple_changes(self):
        left = {"capital": 100000, "position_size": 0.95, "rebalance": "daily"}
        right = {"capital": 50000, "position_size": 0.80, "rebalance": "weekly"}
        result = diff(left, right)
        assert len(result) == 3


class TestFormatText:
    def test_no_diff(self):
        assert "No differences" in format_text({})

    def test_single_diff(self):
        output = format_text({"capital": (100000, 50000)})
        assert "capital" in output
        assert "100000" in output
        assert "50000" in output

    def test_added_key(self):
        output = format_text({"new_key": (None, "value")})
        assert "new_key" in output
        assert "None" in output


class TestFormatJson:
    def test_valid_json_output(self):
        diffs = {"capital": (100000, 50000)}
        output = format_json(diffs)
        parsed = json.loads(output)
        assert parsed["capital"]["left"] == 100000
        assert parsed["capital"]["right"] == 50000

    def test_empty_diff(self):
        assert json.loads(format_json({})) == {}


class TestEndToEnd:
    def test_cli_compare_two_yamls(self):
        left_data = {"a": 1, "b": 2}
        right_data = {"a": 1, "b": 3}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f1:
            yaml.dump(left_data, f1)
            lpath = f1.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f2:
            yaml.dump(right_data, f2)
            rpath = f2.name
        try:
            from tools.config_diff import main
            import sys
            sys.argv = ["config_diff.py", lpath, rpath]
            assert main() == 0
        finally:
            import os
            os.unlink(lpath)
            os.unlink(rpath)
