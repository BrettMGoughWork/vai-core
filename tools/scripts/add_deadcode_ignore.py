"""Add @deadcode_ignore to dynamically-registered capability classes."""
import ast
from pathlib import Path

PRIMITIVES = Path("src/capabilities/primitives")
REASON = 'Dynamically registered primitive, used on demand by LLM/planner'


def class_decorated(node: ast.ClassDef, decorator_name: str = "deadcode_ignore") -> bool:
    for d in node.decorator_list:
        if isinstance(d, ast.Name) and d.id == decorator_name:
            return True
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == decorator_name:
            return True
    return False


def add_deadcode_ignore(filepath: Path) -> bool:
    text = filepath.read_text(encoding="utf-8")
    tree = ast.parse(text)

    # Find import for deadcode_ignore
    has_import = any(
        isinstance(n, ast.ImportFrom)
        and n.module and "deadcode_markers" in n.module
        for n in ast.iter_child_nodes(tree)
    )

    lines = text.splitlines(keepends=True)
    modified = False

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and not class_decorated(node):
            indent = " " * (node.col_offset if node.col_offset is not None else 0)
            decorator = f'{indent}@deadcode_ignore(reason="{REASON}")\n'
            lines.insert(node.lineno - 1, decorator)
            modified = True

    if not has_import and modified:
        import_stmt = 'from src.strategy.types.validation import deadcode_ignore\n'
        # Find the last import statement position
        insert_pos = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("from ") and not stripped.startswith("import ") and not stripped.startswith('"""') and not stripped.startswith("'''"):
                insert_pos = i
                break
            insert_pos = i + 1

        for i, line in enumerate(lines):
            if line.strip().startswith(("from ", "import ")):
                insert_pos = i + 1

        lines.insert(insert_pos, import_stmt)
        modified = True

    if modified:
        filepath.write_text("".join(lines), encoding="utf-8")
        return True
    return modified


# Process all files in stdlib and root primitives
count = 0
for f in sorted(PRIMITIVES.rglob("*.py")):
    if f.name == "__init__.py":
        continue
    text = f.read_text(encoding="utf-8")
    if "class " not in text:
        continue
    if "deadcode_ignore" in text:
        continue
    if add_deadcode_ignore(f):
        print(f"  OK {f}")
        count += 1

print(f"\nUpdated {count} files with @deadcode_ignore")
