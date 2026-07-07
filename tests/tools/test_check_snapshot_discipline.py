"""Tests for tools/check_snapshot_discipline — useSystemSnapshot select param checker."""

from pathlib import Path

from tools.check_snapshot_discipline import (
    CALL_PATTERN,
    EXEMPT_COMPONENTS,
    EXEMPT_FILES,
    is_exempt,
)


class TestIsExempt:
    def test_exempt_falls_through(self):
        assert "useSystemSnapshot.ts" in EXEMPT_FILES
        assert "AppShell.tsx" in EXEMPT_COMPONENTS

    def test_test_directory_exempt(self):
        assert is_exempt(Path("/repo/src/hooks/__tests__/useSystemSnapshot.test.tsx"))

    def test_non_exempt_file(self):
        assert not is_exempt(Path("/repo/src/components/AssetCard.tsx"))

    def test_exempt_by_name(self):
        for name in EXEMPT_FILES:
            assert is_exempt(Path(f"/repo/src/hooks/{name}"))

    def test_exempt_component_by_name(self):
        for name in EXEMPT_COMPONENTS:
            assert is_exempt(Path(f"/repo/src/components/{name}"))


class TestCallPattern:
    def test_matches_simple_call(self):
        assert CALL_PATTERN.search("useSystemSnapshot(selectFoo)")

    def test_matches_no_arg_call(self):
        assert CALL_PATTERN.search("useSystemSnapshot()")

    def test_does_not_match_partial(self):
        # Pattern requires open paren after the function name
        assert not CALL_PATTERN.search("useSystemSnapshotRef.current")
        assert not CALL_PATTERN.search("useSystemSnapshots()")


class TestEndToEnd:
    def test_main_passes_on_clean_repo(self):
        from tools.check_snapshot_discipline import main
        assert main() == 0
