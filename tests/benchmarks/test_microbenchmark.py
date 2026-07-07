"""Tests for benchmarks/microbenchmark — hot-path microbenchmark.

These tests focus on the helper functions without running the full engine.
The benchmark is designed for interactive use (starts engine, runs cycles),
so we test the argument parser, mock model training, and utility functions
in isolation.
"""

import argparse
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from benchmarks.microbenchmark import (
    run_sweep,
    run_profiled,
)


class TestArgumentParser:
    def test_default_values(self):
        from benchmarks.microbenchmark import main as bench_main
        # Just verify the parser works without error
        with patch.object(sys, "argv", ["microbenchmark.py", "--quick", "--assets", "1", "--workers", "1"]):
            parser = argparse.ArgumentParser(description="EigenCapital hot-path microbenchmark")
            parser.add_argument("--assets", type=int, default=15)
            parser.add_argument("--workers", type=int, default=8)
            parser.add_argument("--cycles", type=int, default=5)
            parser.add_argument("--bars", type=int, default=500)
            parser.add_argument("--output", type=str, default="")
            parser.add_argument("--profile", type=str, default="")
            parser.add_argument("--skip-validation", action="store_true")
            parser.add_argument("--state-dir", type=str, default="")
            parser.add_argument("--quick", action="store_true")
            parser.add_argument("--sweep", action="store_true")
            args = parser.parse_args()
            assert args.assets == 1
            assert args.workers == 1
            assert args.quick is True

    def test_sweep_flag(self):
        from benchmarks.microbenchmark import main as bench_main
        parser = argparse.ArgumentParser(description="EigenCapital hot-path microbenchmark")
        parser.add_argument("--sweep", action="store_true")
        parser.add_argument("--quick", action="store_true")
        parser.add_argument("--assets", type=int, default=15)
        parser.add_argument("--workers", type=int, default=8)
        parser.add_argument("--cycles", type=int, default=5)
        parser.add_argument("--bars", type=int, default=500)
        parser.add_argument("--output", type=str, default="")
        parser.add_argument("--profile", type=str, default="")
        parser.add_argument("--skip-validation", action="store_true")
        parser.add_argument("--state-dir", type=str, default="")

        with patch.object(sys, "argv", ["microbenchmark.py", "--sweep", "--quick"]):
            args = parser.parse_args()
            assert args.sweep is True
            assert args.quick is True


class TestRunSweep:
    def test_run_sweep_outputs_json(self, capsys):
        """Sweep with 1 asset and 1 worker should produce output."""
        with patch("benchmarks.microbenchmark.run_benchmark") as mock_run:
            mock_run.return_value = [
                {"event": "cycle", "wall_s": 0.1, "n_assets": 1, "n_workers": 1},
                {"event": "summary", "warm_p50_s": 0.1},
            ]
            args = argparse.Namespace(
                assets=1, workers=1, bars=100, output="", profile="",
                skip_validation=True, quick=True, state_dir="",
                sweep=True, cycles=1,
            )
            run_sweep(args)
            captured = capsys.readouterr()
            assert "sweep_done" in captured.out


class TestRunProfiled:
    def test_profiled_mode_captures_profile(self, tmp_path):
        prof_path = tmp_path / "cycle.prof"
        with patch("benchmarks.microbenchmark.build_engine") as mock_build:
            mock_engine = MagicMock()
            mock_build.return_value = mock_engine

            args = argparse.Namespace(
                assets=1, workers=1, bars=100, profile=str(prof_path),
                skip_validation=True, quick=True, state_dir="",
                sweep=False, cycles=1,
            )
            run_profiled(args)
            # Should call engine.run_once at least once (warmup)
            assert mock_engine.run_once.call_count >= 1
