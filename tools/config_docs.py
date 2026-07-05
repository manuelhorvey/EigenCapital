"""
config_docs.py — generate CONFIGURATION.md from the typed domain models.

Phase 9 of the configuration architecture refactor. The generator walks
the typed dataclass models in :mod:`configs.domain_models` and emits
a single Markdown reference table per domain. The output is checked
into the repo so contributors can browse settings without running the
engine.

Usage:
    python tools/config_docs.py               # write to docs/CONFIGURATION.md
    python tools/config_docs.py --stdout      # emit to stdout
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import types as _types
from dataclasses import MISSING, fields, is_dataclass
from pathlib import Path
from typing import get_type_hints


def _resolve_hints(cls) -> dict[str, type]:
    """Resolve type hints for a dataclass, with fallback for stringified annotations.

    ``get_type_hints()`` can fail when the class uses ``from __future__ import annotations``
    combined with PEP 604 union syntax (``int | None``) in some Python environments.
    This function falls back to manual ``eval()`` resolution in the module's namespace.
    """
    hints = {}
    try:
        hints = get_type_hints(cls)
        if hints:
            return hints
    except Exception as e:  # noqa: BLE001
        print(f"config_docs: warning — get_type_hints failed for {cls.__name__}: {e}", file=sys.stderr)

    # Fallback: manually resolve string annotations
    module = sys.modules.get(cls.__module__)
    ns = dict(vars(module)) if module else {}
    ns.setdefault("__builtins__", __builtins__)

    for name, ann in cls.__annotations__.items():
        if not isinstance(ann, str):
            hints[name] = ann
        elif name not in hints:
            with contextlib.suppress(Exception):
                hints[name] = eval(ann, ns)
    return hints


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_PATH = REPO_ROOT / "docs" / "CONFIGURATION.md"


def _format_field(line: str) -> str:
    return f"| `{line}` | | |"


_DOMAIN_FILE_MAP: dict[str, str] = {
    "CapitalConfig": "`configs/domains/risk/capital.yaml`",
    "HaltConfig": "`configs/domains/risk/halt.yaml`",
    "SizingConfig": "`configs/domains/risk/sizing.yaml`",
    "ExitConfig": "`configs/domains/risk/exits.yaml`",
    "SellOnlyConfig": "`configs/domains/assets/_defaults.yaml` + `configs/domains/assets/*.yaml`",
}


def _promoted_status_table() -> str:
    """Render the promoted-domain status summary."""
    try:
        from configs.paper_config_registry import PaperConfigRegistry

        reg = PaperConfigRegistry.load()
    except Exception:  # noqa: BLE001
        reg = None

    domains = [
        # Actually wired through PaperConfigRegistry.load()
        ("Capital", "risk/capital.yaml", "✅ promoted"),
        ("Halt", "risk/halt.yaml", "✅ promoted (Phase 12.2c)"),
        ("Sizing", "risk/sizing.yaml", "✅ promoted"),
        ("Exits", "risk/exits.yaml", "✅ promoted"),
        ("Sell-only", "_defaults.yaml + per-asset", "✅ promoted (Phase 5)"),
        ("Assets (per-asset)", "assets/<TICKER>.yaml", "✅ promoted (Phase 7)"),
        ("Infrastructure scalars", "infrastructure/config.yaml", "✅ promoted (Phase 12.3)"),
        # Promoted domains (wired through PaperConfigRegistry.load())
        ("MT5 broker", "broker/mt5.yaml", "✅ promoted (Phase 12.6)"),
        ("Execution/governance", "governance/*.yaml", "✅ promoted (Phase 12.6)"),
        ("Optimizations", "infrastructure/optimizations.yaml", "✅ promoted (Phase 12.6)"),
        ("Portfolio weights", "portfolio/weights.yaml", "✅ promoted"),
        ("Regime geometry", "governance/regime_geometry.yaml", "✅ promoted"),
        ("Calibration", "ml/calibration.yaml", "✅ promoted"),
        ("Ensemble", "ml/ensemble.yaml", "✅ promoted"),
        ("Meta-labeling", "ml/meta_labeling.yaml", "✅ promoted"),
        ("Triple-barrier (label params)", "ml/triple_barrier.yaml", "✅ promoted (stored as label_params)"),
        ("Alerts", "infrastructure/alerts.yaml", "✅ promoted"),
        ("Spread gate", "execution/spreads.yaml", "✅ promoted"),
        ("Session gate", "execution/sessions.yaml", "✅ promoted"),
        ("Mode definitions", "modes/*.yaml", "✅ promoted"),
        # Governance domain files — standalone fields + composed into execution.governance
        ("Liquidity", "governance/liquidity.yaml", "✅ promoted (standalone + composed into `execution.governance`)"),
        ("Narrative", "governance/narrative.yaml", "✅ promoted (standalone + composed into `execution.governance`)"),
        # Environment overlays — wired through PaperConfigRegistry.load() Step 1r
        ("Environment overlays", "environments/*.yaml", "✅ promoted (final overlay layer)"),
    ]

    # Legacy_extras keys from the live registry
    extras = []
    if reg is not None:
        extras = sorted(reg.legacy_extras.keys())

    # Add legacy-extras rows
    if extras:
        for k in extras:
            domains.append((f"`{k}` (legacy only)", "—", "⏳ legacy_extras"))

    out = "## Promoted-Domain Status\n\n"
    out += "Domains sourced from `configs/domains/` and wired through `PaperConfigRegistry`.\n\n"
    out += "| Domain | Source File | Status |\n|---|---|---|\n"
    for name, source, status in domains:
        out += f"| {name} | `{source}` | {status} |\n"
    out += "\n**Pruned keys** (never consumed through EngineConfig):\n"
    out += "`kelly`\n\n"
    if extras:
        out += f"**Remaining legacy_extras** ({len(extras)} keys):\n"
        out += ", ".join(f"`{k}`" for k in extras) + "\n\n"
    return out


def _table_for_dataclass(cls) -> str:
    """Render a single config domain as a Markdown table."""
    name = cls.__name__
    doc = (cls.__doc__ or "").strip().splitlines()[0] if cls.__doc__ else "(no docstring)"
    source = _DOMAIN_FILE_MAP.get(name, "(legacy fallback)")
    out = f"## `{name}`\n\n{doc}\n\n**Source domain file:** {source}\n\n"
    out += "| Field | Type | Default |\n|---|---|---|\n"
    hints = _resolve_hints(cls)
    for f in fields(cls):
        if f.name.startswith("_"):
            continue
        type_name = "Any"
        if f.name in hints:
            t = hints[f.name]
            type_name = _render_type(t)
        else:
            type_name = type(f.default).__name__
        if f.default is not MISSING:
            default_repr = repr(f.default)
        elif f.default_factory is not MISSING:
            default_repr = "(default_factory)"
        else:
            default_repr = "(required)"
        out += f"| `{f.name}` | `{type_name}` | `{default_repr}` |\n"
    out += "\n"
    return out


def _render_type(tp) -> str:
    """Render a type annotation into a compact human-readable name.

    Handles Union (including the Optional form), nested generics, the
    typing module's Union sentinel, and Python 3.10+ ``X | None``
    syntax (``types.UnionType``).
    """
    import typing as _typing

    origin = getattr(tp, "__origin__", None)
    args = getattr(tp, "__args__", ())

    # Handle Python 3.10+ X | None / X | Y syntax (types.UnionType)
    if origin is _types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return f"Optional[{_render_type(non_none[0])}]"
        inner = ", ".join(_render_type(a) for a in args)
        return f"Union[{inner}]"

    if origin is _typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return f"Optional[{_render_type(non_none[0])}]"
        return "Union[" + ", ".join(_render_type(a) for a in args) + "]"

    if origin is not None:
        origin_name = getattr(origin, "__name__", str(origin))
        rendered_args = ", ".join(_render_type(a) for a in args)
        return f"{origin_name}[{rendered_args}]"

    name = getattr(tp, "__name__", None)
    if name is not None:
        return name
    return str(tp)


def render_markdown() -> str:
    """Render the full CONFIGURATION.md."""
    sys.path.insert(0, str(REPO_ROOT))

    try:
        risk_mod = __import__("configs.domain_models.risk", fromlist=["x"])
    except Exception as e:  # noqa: BLE001
        return f"# Configuration Reference\n\n*Generator import failed: {e}*\n"

    blocks = ["# EigenCapital Configuration Reference", ""]
    blocks.append(
        "Generated by `tools/config_docs.py` from the typed domain models.\n"
        "Regenerate after changing `configs/domain_models/*.py`.\n"
    )

    try:
        blocks.append(_promoted_status_table())
    except Exception as e:  # noqa: BLE001
        blocks.append(f"\n*Promoted-domain status unavailable: {e}*\n\n")

    for cls_name in ("CapitalConfig", "HaltConfig", "SizingConfig", "ExitConfig", "SellOnlyConfig"):
        cls = getattr(risk_mod, cls_name, None)
        if cls is None or not is_dataclass(cls):
            continue
        try:
            blocks.append(_table_for_dataclass(cls))
        except Exception as e:  # noqa: BLE001
            blocks.append(f"\n*Skipped `{cls_name}` due to render error: {e}*\n")

    return "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of file")
    args = parser.parse_args()

    markdown = render_markdown()
    if args.stdout:
        print(markdown)
        return 0

    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(markdown)
    print(f"config_docs: wrote {DOCS_PATH} ({len(markdown.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
