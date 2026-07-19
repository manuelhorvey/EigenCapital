#!/usr/bin/env python3
"""Convert os.path.join → pathlib.Path across the codebase.

Usage:
    python tools/convert_paths_to_pathlib.py                    # apply changes
    python tools/convert_paths_to_pathlib.py --dry-run          # preview only
    python tools/convert_paths_to_pathlib.py --file FILE.py     # single file

This script handles the following conversions:
    Path(a) / b / c          → Path(a) / b / c
    Path(os.path.abspath(__file__).parent) → Path(__file__).resolve().parent
    Path(path).mkdir(parents=True, exist_ok=True) → Path(path).mkdir(parents=True, exist_ok=True)
    Path(path).exists()           → Path(path).exists()
    Path(path).is_dir()            → Path(path).is_dir()
    Path(path).name         → Path(path).name
    Path(path).parent          → Path(path).parent
    import os                      → from pathlib import Path  (if no other os usage)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

# Files already converted manually in Batch 1
ALREADY_CONVERTED = frozenset({
    "paper_trading/inference/regime_model.py",
    "paper_trading/inference/shadow_registry.py",
    "paper_trading/state/data_cache.py",
    "paper_trading/state_store.py",
    "paper_trading/asset_engine_factory.py",
    "paper_trading/governance/health.py",
    "paper_trading/shadow/feedback.py",
    "paper_trading/shadow/learning.py",
    "paper_trading/shadow/memory.py",
    "paper_trading/services/attribution_service.py",
})

# Directories/files to exclude
EXCLUDE_DIRS = frozenset({".venv", "archive", ".git", "__pycache__", ".agents", "node_modules"})

# Regex patterns
RE_OS_PATH_JOIN = re.compile(
    r"os\.path\.join\(([^)]*)\)"
)

# Pattern for os.path.join with Path(os.path.abspath(__file__).parent)
RE_ABSPATH_DIRNAME = re.compile(
    r"os\.path\.dirname\(os\.path\.abspath\(__file__\)\)"
)

# Pattern for nested dirname chains: Path(os.path.dirname(...).parent)
RE_DIRNAME_CHAIN = re.compile(
    r"os\.path\.dirname\(" * 3 + r"os\.path\.abspath\(__file__\)" + r"\)" * 3
)

# Pattern for os.makedirs (general)
RE_OS_MAKEDIRS = re.compile(
    r"os\.makedirs\(([^,]+)(,\s*exist_ok=True)?\)"
)

# Pattern for os.path.exists
RE_OS_PATH_EXISTS = re.compile(r"os\.path\.exists\(([^)]+)\)")

# Pattern for os.path.isdir
RE_OS_PATH_ISDIR = re.compile(r"os\.path\.isdir\(([^)]+)\)")

# Pattern for os.path.basename
RE_OS_PATH_BASENAME = re.compile(r"os\.path\.basename\(([^)]+)\)")

# Pattern for os.path.dirname (standalone, not part of join chain)
RE_OS_PATH_DIRNAME = re.compile(r"os\.path\.dirname\(([^)]+)\)")

# Pattern for os.path.getsize
RE_OS_PATH_GETSIZE = re.compile(r"os\.path\.getsize\(([^)]+)\)")

# Pattern for os.listdir
RE_OS_LISTDIR = re.compile(r"os\.listdir\(([^)]+)\)")


def find_target_files(root: str = ".") -> list[Path]:
    """Find all .py files containing os.path.join, excluding already-converted."""
    files: list[Path] = []
    root_path = Path(root).resolve()

    for path in root_path.rglob("*.py"):
        # Skip excluded dirs
        rel = path.relative_to(root_path)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        # Skip already-converted files
        if str(rel) in ALREADY_CONVERTED:
            continue
        # Check if file contains os.path.join
        try:
            content = path.read_text()
            if "Path(" in content:
                files.append(path)
        except (OSError, UnicodeDecodeError):
            continue

    return sorted(files)


def count_os_usages(content: str) -> dict[str, int]:
    """Count usages of various os.* functions in content."""
    counts = {
        "os.path.join": len(re.findall(r"os\.path\.join\(", content)),
        "os.makedirs": len(re.findall(r"os\.makedirs\(", content)),
        "os.path.exists": len(re.findall(r"os\.path\.exists\(", content)),
        "os.path.isdir": len(re.findall(r"os\.path\.isdir\(", content)),
        "os.listdir": len(re.findall(r"os\.listdir\(", content)),
        "os.path.basename": len(re.findall(r"os\.path\.basename\(", content)),
        "os.path.dirname": len(re.findall(r"(?<!os\.path\.join\()os\.path\.dirname\(", content)),
        "os.path.getsize": len(re.findall(r"os\.path\.getsize\(", content)),
        "os.environ": len(re.findall(r"os\.environ", content)),
        "os.sep": len(re.findall(r"os\.sep", content)),
        "os.linesep": len(re.findall(r"os\.linesep", content)),
        "os.open": len(re.findall(r"(?<!\.)os\.open\(", content)),
        "os.getpid": len(re.findall(r"os\.getpid", content)),
        "os.unlink": len(re.findall(r"os\.unlink\(", content)),
        "os.remove": len(re.findall(r"os\.remove\(", content)),
        "os.rename": len(re.findall(r"os\.rename\(", content)),
        "os.replace": len(re.findall(r"os\.replace\(", content)),
        "os.chmod": len(re.findall(r"os\.chmod\(", content)),
        "os.kill": len(re.findall(r"os\.kill\(", content)),
        "os.getcwd": len(re.findall(r"os\.getcwd\(", content)),
        "os.getenv": len(re.findall(r"os\.getenv\(", content)),
    }
    return counts


def needs_os_import(counts: dict[str, int]) -> bool:
    """Check if any non-path os functions are used (keeping import os)."""
    non_path_uses = (
        counts["os.environ"]
        + counts["os.sep"]
        + counts["os.linesep"]
        + counts["os.open"]
        + counts["os.getpid"]
        + counts["os.unlink"]
        + counts["os.remove"]
        + counts["os.rename"]
        + counts["os.replace"]
        + counts["os.chmod"]
        + counts["os.kill"]
        + counts["os.getcwd"]
        + counts["os.getenv"]
    )
    return non_path_uses > 0


def convert_os_path_join(match: re.Match) -> str:
    """Convert Path(a) / b / c → Path(a) / b / c."""
    args = match.group(1)
    # Split by comma, but be careful of nested commas in f-strings
    parts = _split_args(args)
    if not parts:
        return match.group(0)

    # Handle special case: Path(Path(os.path.abspath(__file__).parent), ...)
    first = parts[0].strip()
    if "Path(os.path.abspath(__file__).parent)" in first:
        # Count parent levels
        depth = _count_dirname_depth(first)
        # Replace the dirname chain
        rest = parts[1:] if len(parts) > 1 else []
        if depth == 1:
            converterd = "Path(__file__).resolve().parent"
        else:
            converterd = "Path(__file__).resolve().parent" + ".parent" * (depth - 1)
        if rest:
            return converterd + " / " + " / ".join(r.strip() for r in rest)
        return converterd

    # Regular: Path(BASE) / "a" / "b" → Path(BASE) / "a" / "b"
    first = parts[0].strip()
    rest = parts[1:] if len(parts) > 1 else []
    result = f"Path({first})"
    if rest:
        result += " / " + " / ".join(r.strip() for r in rest)
    return result


def _split_args(args_str: str) -> list[str]:
    """Split os.path.join arguments respecting nested parentheses and string literals."""
    parts = []
    depth = 0
    current = []
    in_string = False
    string_char = None
    i = 0
    while i < len(args_str):
        ch = args_str[i]
        if in_string:
            current.append(ch)
            if ch == "\\" and i + 1 < len(args_str):
                i += 1
                current.append(args_str[i])
            elif ch == string_char:
                in_string = False
                string_char = None
        elif ch in ("'", '"'):
            in_string = True
            string_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts


def _count_dirname_depth(expr: str) -> int:
    """Count the number of nested os.path.dirname calls."""
    count = 0
    while "Path(" in expr:
        count += 1
        # Remove one level
        expr = expr.replace("os.path.dirname(", "", 1).parent
    return count


def convert_content(content: str) -> str:
    """Apply all conversions to file content."""
    # Count os usages before conversion
    counts = count_os_usages(content)
    has_pathlib_import = "from pathlib import Path" in content or "from pathlib import" in content
    has_future_annotations = "from __future__ import annotations" in content

    # 1. Convert os.path.join → Path(a) / b / c
    content = RE_OS_PATH_JOIN.sub(convert_os_path_join, content)

    # 2. Convert Path(path).mkdir(parents=True, exist_ok=True) → Path(path).mkdir(parents=True, exist_ok=True)
    # Only convert when the argument looks like a path variable (not when it's already a Path)
    def _convert_makedirs(m: re.Match) -> str:
        arg = m.group(1).strip()
        # Don't convert if it's already a Path method call
        if ".mkdir(" in arg or "Path(" in arg:
            return m.group(0)
        exist_ok = m.group(2) or ""
        return f"Path({arg}).mkdir(parents=True, exist_ok=True)"

    content = RE_OS_MAKEDIRS.sub(_convert_makedirs, content)

    # 3. Convert Path(path).exists() → Path(path).exists()
    def _convert_exists(m: re.Match) -> str:
        arg = m.group(1).strip()
        # Don't convert if the arg is already a Path
        if arg.startswith("Path("):
            return f"{arg}.exists()"
        return f"Path({arg}).exists()"

    content = RE_OS_PATH_EXISTS.sub(_convert_exists, content)

    # 4. Convert Path(path).is_dir() → Path(path).is_dir()
    def _convert_isdir(m: re.Match) -> str:
        arg = m.group(1).strip()
        if arg.startswith("Path("):
            return f"{arg}.is_dir()"
        return f"Path({arg}).is_dir()"

    content = RE_OS_PATH_ISDIR.sub(_convert_isdir, content)

    # 5. Convert Path(path).name → Path(path).name
    def _convert_basename(m: re.Match) -> str:
        arg = m.group(1).strip()
        if arg.startswith("Path("):
            return f"{arg}.name"
        return f"Path({arg}).name"

    content = RE_OS_PATH_BASENAME.sub(_convert_basename, content)

    # 6. Convert Path(path).parent → Path(path).parent
    def _convert_dirname(m: re.Match) -> str:
        arg = m.group(1).strip()
        if arg.startswith("Path("):
            return f"{arg}.parent"
        return f"Path({arg}).parent"

    content = RE_OS_PATH_DIRNAME.sub(_convert_dirname, content)

    # 7. Convert Path(path).stat().st_size → Path(path).stat().st_size
    def _convert_getsize(m: re.Match) -> str:
        arg = m.group(1).strip()
        if arg.startswith("Path("):
            return f"{arg}.stat().st_size"
        return f"Path({arg}).stat().st_size"

    content = RE_OS_PATH_GETSIZE.sub(_convert_getsize, content)

    # 8. Convert sorted(Path(path).iterdir()) → sorted(path.iterdir())
    def _convert_listdir(m: re.Match) -> str:
        arg = m.group(1).strip()
        if arg.startswith("Path("):
            return f"sorted({arg}.iterdir())"
        return f"sorted(Path({arg}).iterdir())"

    content = RE_OS_LISTDIR.sub(_convert_listdir, content)

    # 9. Handle imports
    lines = content.split("\n")
    new_lines = []
    has_pathlib_already = False
    has_os_import = False
    os_import_line = -1

    for i, line in enumerate(lines):
        if "from pathlib import" in line or "import pathlib" in line:
            has_pathlib_already = True
        if re.match(r"^import os\b", line.strip()) or re.match(r"^import os,", line.strip()):
            has_os_import = True
            os_import_line = i
        new_lines.append(line)

    # After all conversions, recount what's left
    new_counts = count_os_usages(content)
    new_non_path_os = needs_os_import(new_counts)

    # Add from pathlib import Path if needed and not present
    if not has_pathlib_already and (
        "Path(" in content
    ):
        # Find the right place to insert
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("from __future__"):
                insert_idx = i + 1
            elif stripped.startswith(("import ", "from ")) and not stripped.startswith("from __future__"):
                insert_idx = i + 1

        if not has_pathlib_already:
            new_lines.insert(insert_idx, "from pathlib import Path")
            insert_idx += 1

    # Remove import os if no longer needed
    if has_os_import and not new_non_path_os:
        # Remove the import os line
        new_lines = [l for l in new_lines if not re.match(r"^import os\b", l.strip()) and not re.match(r"^import os,", l.strip())]

    return "\n".join(new_lines)


def verify_syntax(content: str, filepath: Path) -> bool:
    """Verify the file still compiles after conversion."""
    try:
        ast.parse(content)
        return True
    except SyntaxError as e:
        print(f"  ⚠  Syntax error in {filepath}: {e}", file=sys.stderr)
        return False


def process_file(filepath: Path, dry_run: bool = False) -> bool:
    """Process a single file. Returns True if changes were made."""
    try:
        orig_content = filepath.read_text()
    except (OSError, UnicodeDecodeError) as e:
        print(f"  ⚠  Cannot read {filepath}: {e}", file=sys.stderr)
        return False

    new_content = convert_content(orig_content)

    if new_content == orig_content:
        return False

    if not verify_syntax(new_content, filepath):
        return False

    if dry_run:
        print(f"  📝 Would modify: {filepath}")
        # Show diff summary
        orig_lines = orig_content.split("\n")
        new_lines = new_content.split("\n")
        if len(orig_lines) != len(new_lines):
            print(f"     Line count: {len(orig_lines)} → {len(new_lines)}")
        return True

    # Write changes
    filepath.write_text(new_content)
    print(f"  ✅ Modified: {filepath}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert os.path.join → pathlib.Path")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying")
    parser.add_argument("--file", type=str, default=None, help="Process a single file")
    parser.add_argument("--dir", type=str, default=".", help="Root directory to scan")
    args = parser.parse_args()

    label = "DRY RUN" if args.dry_run else "CONVERT"
    print(f"═══ {label}: os.path.join → pathlib.Path ═══")

    if args.file:
        files = [Path(args.file).resolve()]
    else:
        files = find_target_files(args.dir)

    print(f"Found {len(files)} files to process")

    modified = 0
    for fp in files:
        try:
            if process_file(fp, dry_run=args.dry_run):
                modified += 1
        except Exception as e:
            print(f"  ❌ Error processing {fp}: {e}", file=sys.stderr)

    print(f"\n{'Dry run' if args.dry_run else 'Converted'}: {modified}/{len(files)} files")
    return 0 if modified == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
