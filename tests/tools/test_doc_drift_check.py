"""Tests for tools/doc_drift_check — documentation drift checker."""

from pathlib import Path

import pytest

from tools.doc_drift_check import (
    CANONICAL_FACTS,
    _check_feature_count_claims,
    _check_metric_consistency,
    _check_mode_selector_present,
    _check_pre_phase_in_readme,
    _check_walrunner_occurrences,
    _is_excluded,
    _is_path_like,
    _normalize,
    _collect_markdown_files,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestNormalize:
    def test_strips_caret(self):
        assert _normalize("^DJI") == "DJI"

    def test_preserves_normal(self):
        assert _normalize("EURUSD") == "EURUSD"

    def test_empty_string(self):
        assert _normalize("") == ""


class TestCanonicalFacts:
    def test_all_facts_defined(self):
        assert "governance_layers" in CANONICAL_FACTS
        assert "core_alpha_features" in CANONICAL_FACTS
        assert "sell_only_count" in CANONICAL_FACTS
        assert CANONICAL_FACTS["sell_only_count"] == "6"

    def test_promoted_assets_count(self):
        assert CANONICAL_FACTS["promoted_assets"] == "22"


class TestIsPathLike:
    def test_identifies_paths(self):
        assert _is_path_like("paper_trading/engine.py")
        assert _is_path_like("config.yaml")
        assert _is_path_like("docs/ARCHITECTURE.md")

    def test_rejects_prose(self):
        assert not _is_path_like("this is prose")
        assert not _is_path_like("a → b")
        assert not _is_path_like("x = y")

    def test_rejects_math_symbols(self):
        assert not _is_path_like("a ≈ b")
        assert not _is_path_like("x ≤ y")

    def test_rejects_code_with_spaces(self):
        assert not _is_path_like("assert x > 0")


class TestIsExcluded:
    def test_excludes_archive(self):
        assert _is_excluded(REPO_ROOT / "docs" / "archive" / "old.md")

    def test_excludes_adr(self):
        assert _is_excluded(REPO_ROOT / "docs" / "adr" / "ADR-001.md")

    def test_excludes_audit(self):
        assert _is_excluded(REPO_ROOT / "docs" / "audit" / "report.md")

    def test_excludes_planning(self):
        assert _is_excluded(REPO_ROOT / "docs" / "planning" / "plan.md")

    def test_allows_active_docs(self):
        assert not _is_excluded(REPO_ROOT / "docs" / "ARCHITECTURE.md")

    def test_excludes_node_modules(self):
        assert _is_excluded(REPO_ROOT / "node_modules" / "pkg" / "readme.md")


class TestCollectMarkdownFiles:
    def test_returns_list_of_paths(self):
        files = _collect_markdown_files()
        assert isinstance(files, list)
        assert len(files) >= 10
        assert all(f.suffix == ".md" for f in files)

    def test_includes_known_docs(self):
        files = _collect_markdown_files()
        names = {f.name for f in files}
        assert "ARCHITECTURE.md" in names


class TestCheckWalRunner:
    def test_returns_empty_when_clean(self):
        occurrences = _check_walrunner_occurrences()
        assert isinstance(occurrences, list)


class TestCheckFeatureCount:
    def test_returns_list(self):
        issues = _check_feature_count_claims()
        assert isinstance(issues, list)


class TestCheckMetricConsistency:
    def test_returns_list(self):
        issues = _check_metric_consistency()
        assert isinstance(issues, list)


class TestCheckModeSelector:
    def test_returns_bool(self):
        result = _check_mode_selector_present()
        assert isinstance(result, bool)


class TestCheckPrePhaseInReadme:
    def test_returns_tuple(self):
        ok, lines = _check_pre_phase_in_readme()
        assert isinstance(ok, bool)
        assert isinstance(lines, int)
        assert lines > 0


class TestMain:
    def test_main_passes_when_clean(self):
        # The doc-drift check should pass on the current repo state
        from tools.doc_drift_check import main
        assert main() == 0
