"""Tests for tools/config_lint — configuration architecture lint tool."""

import sys
from pathlib import Path

from tools.config_lint import (
    DEPRECATED_KEYS,
    lint,
)


class TestDeprecatedKeys:
    def test_deprecated_keys_defined(self):
        assert "min_lot" in DEPRECATED_KEYS


class TestLint:
    def test_lint_passes_on_valid_config(self):
        assert lint() == 0

    def test_lint_detects_deprecated_key(self, tmp_path):
        config = tmp_path / "bad.yaml"
        config.write_text("min_lot: 0.01\ncapital: 100\n")
        rc = lint(config)
        assert rc == 0  # report-only, non-strict

    def test_lint_strict_fails_on_deprecated_key(self, tmp_path):
        original_argv = list(sys.argv)
        try:
            config = tmp_path / "bad.yaml"
            config.write_text("min_lot: 0.01\ncapital: 100\n")
            sys.argv = ["config_lint.py", "--strict", "--config", str(config)]
            rc = lint(config)
            assert rc == 1
        finally:
            sys.argv = original_argv

    def test_lint_strict_passes_on_clean_config(self, tmp_path):
        original_argv = list(sys.argv)
        try:
            config = tmp_path / "good.yaml"
            config.write_text("capital: 100\nposition_size: 0.95\n")
            sys.argv = ["config_lint.py", "--strict", "--config", str(config)]
            rc = lint(config)
            assert rc == 0
        finally:
            sys.argv = original_argv

    def test_lint_missing_file_returns_zero(self, tmp_path):
        config = tmp_path / "nonexistent.yaml"
        rc = lint(config)
        assert rc == 0
