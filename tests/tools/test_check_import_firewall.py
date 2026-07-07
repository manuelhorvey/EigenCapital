"""Tests for tools/check_import_firewall — AST-scanner for forbidden imports."""

import ast
from pathlib import Path

from tools.check_import_firewall import (
    FORBIDDEN_MODULES,
    _check_file,
    _is_excluded,
    _module_forbidden,
    main,
)


class TestModuleForbidden:
    def test_detects_exact_match(self):
        # _module_forbidden checks if a module starts with a forbidden prefix
        result = _module_forbidden("features.builder")
        assert result == "features.builder"

    def test_detects_submodule(self):
        result = _module_forbidden("features.builder.something")
        assert result == "features.builder"

    def test_allows_safe_modules(self):
        assert _module_forbidden("features.alpha_features") is None
        assert _module_forbidden("shared.registry") is None

    def test_allows_unknown_modules(self):
        assert _module_forbidden("numpy") is None
        assert _module_forbidden("pandas") is None

    def test_all_forbidden_modules_recognized(self):
        for mod in FORBIDDEN_MODULES:
            result = _module_forbidden(mod)
            assert result == mod, f"{mod!r} should be detected as forbidden"


class TestCheckFile:
    def test_detects_forbidden_import(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("import features.builder\n")
        violations = _check_file(f)
        assert len(violations) == 1, f"Expected 1 violation, got {violations}"
        assert violations[0][2] == "features.builder"

    def test_detects_forbidden_from_import(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("from features.builder import something\n")
        violations = _check_file(f)
        assert len(violations) == 1, f"Expected 1 violation, got {violations}"

    def test_ignores_safe_imports(self, tmp_path):
        f = tmp_path / "good.py"
        f.write_text("import numpy\nimport pandas as pd\nfrom features.alpha_features import build\n")
        violations = _check_file(f)
        assert len(violations) == 0

    def test_handles_syntax_errors_gracefully(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("this is not valid python @@@\n")
        violations = _check_file(f)
        assert violations == []

    def test_detects_shared_meta_labeling(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("import shared.meta_labeling\n")
        violations = _check_file(f)
        assert len(violations) == 1
        assert violations[0][2] == "shared.meta_labeling"

    def test_skips_comment_only(self, tmp_path):
        f = tmp_path / "comment.py"
        f.write_text("# import features.builder\n")
        violations = _check_file(f)
        assert len(violations) == 0


class TestIsExcluded:
    def test_excludes_pycache(self):
        assert _is_excluded(Path("/path/__pycache__/file.py"))

    def test_excludes_venv(self):
        assert _is_excluded(Path("/path/.venv/file.py"))

    def test_excludes_git(self):
        assert _is_excluded(Path("/path/.git/file.py"))

    def test_allows_normal_path(self):
        assert not _is_excluded(Path("/path/paper_trading/engine.py"))


class TestMain:
    def test_main_runs_and_returns_int(self):
        """main() should return 0 or 1 depending on repo state.
        The repo has known legacy imports in scripts/ and legacy files."""
        result = main()
        assert result in (0, 1)
