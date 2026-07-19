"""Tests for tools/check_import_os.py — detects os.* calls without import os."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_import_os import (
    _find_os_calls,
    _has_local_import_os,
    _has_module_level_import_os,
    check_file,
)


# ── _has_module_level_import_os ──────────────────────────────────────────────


class TestHasModuleLevelImportOs:
    def test_detects_import_os(self):
        assert _has_module_level_import_os("import os\nimport json\n")

    def test_detects_from_os_import(self):
        assert _has_module_level_import_os("from os import path\n")

    def test_detects_import_os_with_alias(self):
        assert _has_module_level_import_os("import os as operating_system\n")

    def test_negative_when_missing(self):
        assert not _has_module_level_import_os("from pathlib import Path\nimport json\n")

    def test_negative_on_local_import(self):
        """Module-level scan should not match local imports inside functions."""
        code = 'def f():\n    import os\n    return os.fsync(1)\n'
        assert not _has_module_level_import_os(code)


# ── _has_local_import_os ─────────────────────────────────────────────────────


class TestHasLocalImportOs:
    def test_detects_local_import(self):
        code = 'def f():\n    import os\n    os.fsync(1)\n'
        assert _has_local_import_os(code)

    def test_detects_local_from_import(self):
        code = 'def f():\n    from os import fsync\n    fsync(1)\n'
        assert _has_local_import_os(code)

    def test_negative_when_only_module_level(self):
        code = 'import os\n\ndef f():\n    os.fsync(1)\n'
        assert not _has_local_import_os(code)

    def test_negative_when_no_import(self):
        code = 'def f():\n    return 42\n'
        assert not _has_local_import_os(code)

    def test_async_function(self):
        code = 'async def f():\n    import os\n    os.fsync(1)\n'
        assert _has_local_import_os(code)


# ── _find_os_calls ───────────────────────────────────────────────────────────


class TestFindOsCalls:
    def test_finds_os_fsync(self):
        calls = _find_os_calls("os.fsync(f.fileno())")
        assert "os.fsync" in calls

    def test_finds_os_replace(self):
        calls = _find_os_calls("os.replace(tmp, path)")
        assert "os.replace" in calls

    def test_finds_os_stat(self):
        calls = _find_os_calls("os.stat(trace).st_size")
        assert "os.stat" in calls

    def test_finds_os_unlink(self):
        calls = _find_os_calls("os.unlink(tmp_path)")
        assert "os.unlink" in calls

    def test_finds_os_makedirs(self):
        calls = _find_os_calls("os.makedirs(path, exist_ok=True)")
        assert "os.makedirs" in calls

    def test_finds_os_getcwd(self):
        calls = _find_os_calls("os.getcwd()")
        assert "os.getcwd" in calls

    def test_finds_os_listdir(self):
        calls = _find_os_calls("os.listdir(path)")
        assert "os.listdir" in calls

    def test_skips_os_path(self):
        calls = _find_os_calls("os.path.join(a, b)")
        assert "os.path" not in calls
        assert not calls

    def test_skips_os_environ(self):
        calls = _find_os_calls("os.environ.get('HOME')")
        assert "os.environ" not in calls
        assert not calls

    def test_finds_multiple_calls(self):
        code = """
os.fsync(f.fileno())
os.replace(tmp, path)
"""
        calls = _find_os_calls(code)
        assert "os.fsync" in calls
        assert "os.replace" in calls


# ── check_file ───────────────────────────────────────────────────────────────


class TestCheckFile:
    def test_clean_when_import_os_present(self, tmp_path: Path):
        p = tmp_path / "clean.py"
        p.write_text("import os\nos.fsync(f.fileno())\n")
        assert check_file(p) == []

    def test_clean_when_local_import_present(self, tmp_path: Path):
        p = tmp_path / "local_import.py"
        p.write_text('def doit():\n    import os\n    os.fsync(f.fileno())\n')
        assert check_file(p) == []

    def test_violation_when_import_os_missing(self, tmp_path: Path):
        p = tmp_path / "bad.py"
        p.write_text("from pathlib import Path\nos.fsync(f.fileno())\n")
        msgs = check_file(p)
        assert len(msgs) == 1
        assert "missing ``import os``" in msgs[0]

    def test_clean_when_only_safe_calls(self, tmp_path: Path):
        p = tmp_path / "safe.py"
        p.write_text("from pathlib import Path\nret = os.path.join(a, b)\n")
        assert check_file(p) == []

    def test_clean_when_no_os_calls(self, tmp_path: Path):
        p = tmp_path / "no_os.py"
        p.write_text("from pathlib import Path\nprint('hello')\n")
        assert check_file(p) == []

    def test_violation_reports_all_calls(self, tmp_path: Path):
        p = tmp_path / "multi.py"
        p.write_text("from pathlib import Path\nos.fsync(f)\nos.replace(a, b)\n")
        msgs = check_file(p)
        assert len(msgs) == 1
        assert "os.fsync" in msgs[0]
        assert "os.replace" in msgs[0]

    def test_skips_syntax_error_files(self, tmp_path: Path):
        p = tmp_path / "broken.py"
        p.write_text("this is not valid python {{{{\n")
        assert check_file(p) == []
