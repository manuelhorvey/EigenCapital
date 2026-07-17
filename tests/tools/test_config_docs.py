"""Tests for tools/config_docs — CONFIGURATION.md generator."""

from dataclasses import dataclass

from tools.config_docs import _resolve_hints, _render_type, render_markdown


@dataclass
class _SampleDoc:
    """Sample dataclass for _resolve_hints tests."""

    x: int
    y: str


class TestRenderType:
    def test_simple_type(self):
        assert _render_type(str) == "str"
        assert _render_type(int) == "int"

    def test_optional_type(self):
        import typing

        result = _render_type(typing.Optional[str])
        assert "Optional" in result


class TestRenderMarkdown:
    def test_returns_string(self):
        result = render_markdown()
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_expected_sections(self):
        result = render_markdown()
        assert "# EigenCapital Configuration Reference" in result
        assert "Last updated" in result

    def test_contains_promoted_domain_table(self):
        result = render_markdown()
        assert "Promoted-Domain Status" in result

    def test_contains_capital_config(self):
        result = render_markdown()
        assert "CapitalConfig" in result


class TestResolveHints:
    def test_resolves_basic_hints(self):
        hints = _resolve_hints(_SampleDoc)
        assert hints["x"] is int
        assert hints["y"] is str
