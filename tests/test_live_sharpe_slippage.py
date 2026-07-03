"""Regression for live_sharpe.compute_slippage_estimate — was crashing with
`OSError: telling position disabled by next() call` because the old code
called `f.tell()` on a text-mode file after iterating via `for line in f:`.
Both the unbounded-exhaustion path and the 2000-line cap path must persist
the read position cleanly across calls.
"""
import json
import os
import tempfile

import pytest

from paper_trading.performance.live_sharpe import LiveSharpeTracker


def _write_trace(path, lines):
    with open(path, "w") as f:
        for ln in lines:
            f.write(ln + "\n")


def _entry(close, current):
    return json.dumps(
        {"asset": "X", "close_price": close, "current_price": current}
    )


def test_first_call_reads_from_zero_and_persists_pos():
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        _write_trace(trace, [_entry(100.0, 101.0)] * 5)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        result = t.compute_slippage_estimate()
        assert result["available"] is True
        assert result["n_samples"] == 5
        first_pos = t._trace_file_pos
        assert first_pos > 0
        # File size matches seek position
        assert first_pos == os.stat(trace).st_size


def test_second_call_no_new_samples_when_no_new_lines():
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        _write_trace(trace, [_entry(100.0, 101.0)] * 3)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        r1 = t.compute_slippage_estimate()
        pos1 = t._trace_file_pos
        r2 = t.compute_slippage_estimate()
        pos2 = t._trace_file_pos
        # No new lines → same samples, same position
        assert r2["n_samples"] == r1["n_samples"]
        assert pos2 == pos1


def test_third_call_reads_only_new_lines():
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        _write_trace(trace, [_entry(100.0, 101.0)] * 3)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        t.compute_slippage_estimate()  # baseline
        # Append two more lines
        with open(trace, "a") as f:
            f.write(_entry(100.0, 102.0) + "\n")
            f.write(_entry(100.0, 99.0) + "\n")
        r = t.compute_slippage_estimate()
        assert r["n_samples"] == 5  # 3 + 2 new


def test_truncation_resets_and_clears():
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        _write_trace(trace, [_entry(100.0, 101.0)] * 100)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        t.compute_slippage_estimate()
        # Truncate to a smaller file (rotate scenario)
        _write_trace(trace, [_entry(200.0, 198.0)] * 4)
        r = t.compute_slippage_estimate()
        assert r["n_samples"] == 4
        # After truncation reset, pos should be at end of new file
        assert t._trace_file_pos == os.stat(trace).st_size


def test_2000_line_cap_preserves_progress():
    """When the cap is hit, the next call resumes from exactly where we stopped."""
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        # 3000 lines — more than the 2000 cap
        _write_trace(trace, [_entry(100.0, 101.0)] * 3000)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        r1 = t.compute_slippage_estimate()
        assert r1["n_samples"] == 2000
        pos_after_cap = t._trace_file_pos
        r2 = t.compute_slippage_estimate()
        # Should pick up the remaining ~1000 samples, no duplicates, no double-read
        assert r2["n_samples"] == 1000
        assert t._trace_file_pos > pos_after_cap
        assert t._trace_file_pos == os.stat(trace).st_size


def test_no_tell_on_text_iter_file():
    """Direct regression: ensure f.tell() is called only on a binary-mode readline,
    not a text-mode for-loop iterator (which disables tell)."""
    with tempfile.TemporaryDirectory() as td:
        trace = os.path.join(td, "trace.jsonl")
        _write_trace(trace, [_entry(1.0, 1.0)] * 10)
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        # This call would have raised OSError before the fix.
        t.compute_slippage_estimate()
        # Confirm the position is sensibly updated (not 0, not negative)
        assert isinstance(t._trace_file_pos, int)
        assert t._trace_file_pos > 0


def test_missing_file_returns_unavailable():
    with tempfile.TemporaryDirectory() as td:
        t = LiveSharpeTracker(base_dir=td)
        t._base_dir = td
        r = t.compute_slippage_estimate()
        assert r["available"] is False
        assert "no trace file" in r["reason"]
