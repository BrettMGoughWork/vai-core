"""Update all deadcode_ignore imports from src.strategy.types.validation to src.runtime._markers."""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "src"

# Pattern: from src.strategy.types.validation import ... deadcode_ignore ...
PATTERN = re.compile(
    r"from\s+src\.strategy\.types\.validation\s+import\s+([^#\n]*)"
)

OBSOLETE_NAMES = {"deadcode_ignore"}


def _import_contains(names_str: str) -> bool:
    """Check if the import names include any of the obsolete names."""
    # Parse just the names part
    for name_part in names_str.split(","):
        name_part = name_part.strip()
        # Handle 'as' aliases
        base = name_part.split(" as ")[0].strip()
        if base in OBSOLETE_NAMES:
            return True
    return False


def _strip_names(names_str: str, names_to_remove: set[str]) -> str | None:
    """Remove obsolete names from import list. Returns None if all names removed."""
    remaining = []
    all_removed = True
    for name_part in names_str.split(","):
        name_part = name_part.strip()
        base = (name_part.split(" as ")[0]).strip()
        if base in names_to_remove:
            continue  # skip this name
        all_removed = False
        remaining.append(name_part)
    if all_removed:
        return None
    return ", ".join(remaining)


def update_file(path: Path) -> bool:
    """Update a single file. Returns True if changes made."""
    content = path.read_text(encoding="utf-8")
    original = content
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    need_new_import = False

    for line in lines:
        m = PATTERN.match(line)
        if m:
            names_str = m.group(1)
            if _import_contains(names_str):
                # Remove deadcode_ignore from this import
                new_names = _strip_names(names_str, OBSOLETE_NAMES)
                if new_names is None:
                    # All names removed — skip this line entirely
                    continue
                # Replace with remaining names
                indent = line[: len(line) - len(line.lstrip())]
                new_lines.append(f"{indent}from src.strategy.types.validation import {new_names}\n")
                need_new_import = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if need_new_import:
        # Add the new import line right after the import block
        insert_pos = 0
        for i, line in enumerate(new_lines):
            if line.strip().startswith("from ") or line.strip().startswith("import "):
                insert_pos = i + 1
            elif line.strip() and not line.strip().startswith("#"):
                break
        # Insert after last import
        new_lines.insert(insert_pos, "from src.runtime._markers import deadcode_ignore\n")

    result = "".join(new_lines)
    if result != original:
        path.write_text(result, encoding="utf-8")
        return True
    return False


def main():
    changed = 0
    for py_file in sorted(SRC.rglob("*.py")):
        if ".venv" in py_file.parts:
            continue
        if update_file(py_file):
            rel = py_file.relative_to(REPO)
            print(f"  Updated: {rel}")
            changed += 1

    print(f"\nDone. {changed} file(s) updated.")


if __name__ == "__main__":
    main()
