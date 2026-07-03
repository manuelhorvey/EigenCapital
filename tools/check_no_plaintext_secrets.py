"""Pre-commit hook — scan for plaintext secrets in code and YAML.

Patterns flagged:
    - python files containing ``password = "..."`` with non-empty value
    - python files with MT5_ACCOUNT= followed by a numeric value
    - YAML files containing MT5_PASSWORD with a non-placeholder value

Allowlist:
    - filename contains "example", "test", or "fixture"
    - in-code ``os.environ.get(...)`` lookups
    - the literal values **in this scan tool's own regex / examples**

This is a *defense-in-depth* sweep; it doesn't replace proper secret
managers.  It guards against accidentally committing credential files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Patterns: regex name → compiled pattern → description
_PATTERNS = [
    (
        "hardcoded_password_assign",
        re.compile(r'(?i)\bpassword\s*[:=]\s*["\']([^"\']+)["\']'),
        "Hardcoded password assignment",
    ),
    (
        "hardcoded_account_assign",
        re.compile(r"(?i)\b(MT5_ACCOUNT|DATADOG_API_KEY|AWS_SECRET)\s*[:=]\s*[\"']?([0-9a-zA-Z_-]{6,})"),
        "Hardcoded account/api-key assignment",
    ),
    (
        "yaml_password_non_placeholder",
        re.compile(
            r"^MT5_PASSWORD\s*[:=]\s*(?![\"']?(your_|placeholder|<|\$ENV|\$\{))[\"']?([^\s\"']{6,})",
            re.MULTILINE,
        ),
        "YAML literal password value",
    ),
]


def _is_excluded(path: Path) -> bool:
    """Dont scan vendored, cache, example, or tooling files."""
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    if any(p in parts for p in ("__pycache__", ".venv", ".git", "node_modules")):
        return True
    if any(p in ("example", "test", "fixture", "mock", "FakePwd", "passwd") for p in parts):
        return True
    # Test files are allowed to use synthetic credentials (password="x", ...)
    if rel.parts and rel.parts[0] == "tests":
        return True
    # This tool itself contains secret patterns
    return rel.name in (
        "check_no_plaintext_secrets.py",
        "check_no_bare_asserts.py",
    )


def _is_allowed_secret_match(text: str) -> bool:
    """Some matches are explicitly safe (placeholders, env lookups)."""
    if not text:
        return True
    placeholders = (
        "your_",
        "placeholder",
        "your_password",
        "your_key",
        "your_secret",
        "your_demo_",
        "REPLACE_ME",
        "Exness-MT5Trial",
        "...",
        "***",
    )
    lowered = text.lower()
    if lowered == "...":
        return True
    return any(lowered == p.lower() or lowered.startswith(p.lower()) for p in placeholders) or "${" in text


def _scan_paths() -> list[Path]:
    targets: list[Path] = []
    extensions = {".py", ".yaml", ".yml", ".sh", ".env"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        if _is_excluded(path):
            continue
        targets.append(path)
    return targets


def _per_file_patterns(file_path: Path) -> list[tuple[str, re.Pattern[str], str]]:
    """Filter pattern list down for this file type."""
    out = []
    for name, pattern, descr in _PATTERNS:
        if name == "yaml_password_non_placeholder" and file_path.suffix not in (".yaml", ".yml"):
            continue
        out.append((name, pattern, descr))
    return out


def main() -> int:
    findings: list[tuple[Path, str, str, int]] = []
    for path in _scan_paths():
        try:
            contents = path.read_text(errors="ignore")
        except OSError:
            continue
        for name, pattern, descr in _per_file_patterns(path):
            for m in pattern.finditer(contents):
                # Always use the LAST captured group as the secret value.
                value = m.group(0) if m.lastindex is None else m.group(m.lastindex)
                if _is_allowed_secret_match(value):
                    continue
                line_no = contents[: m.start()].count("\n") + 1
                findings.append((path, name, descr, line_no))

    if not findings:
        print("PASSED: no plaintext secrets detected.")
        return 0

    print(f"FAILED: {len(findings)} potential plain-text secret(s):")
    for path, name, descr, line_no in findings:
        rel = path.relative_to(REPO_ROOT)
        print(f"  {rel}:{line_no}: [{name}] {descr}")
    print(
        "\nUse environment variables, secret managers, or git-crypt. "
        "Replace hardcoded values with os.environ.get('VAR_NAME')."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
