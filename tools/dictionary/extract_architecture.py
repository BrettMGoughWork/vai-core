"""
Deterministic structural extraction of the vai-core repository.

Produces docs/architecture.json conforming to the schema:
  { packages, classes, references }

Idempotent: always overwrites the output file.
Usage:
    python tools/dictionary/extract_architecture.py
"""

from __future__ import annotations

import ast
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "docs" / "architecture.json"

EXCLUDE_DIRS = {".venv", ".git", "__pycache__", "node_modules"}

# Map directory path fragments → inferred_stratum
STRATUM_RULES: list[tuple[str, str]] = [
    # test first (most specific)
    ("tests/", "test"),
    ("tests\\", "test"),
    ("primitives/_dev", "test"),
    ("primitives\\_dev", "test"),
    ("tools/", "test"),
    ("tools\\", "test"),
    # infrastructure
    ("core/llm", "infrastructure"),
    ("core\\llm", "infrastructure"),
    ("transport", "infrastructure"),
    ("telemetry", "infrastructure"),
    ("observability", "infrastructure"),
    # domain
    ("core/types", "domain"),
    ("core\\types", "domain"),
    ("core/planning/models", "domain"),
    ("core\\planning\\models", "domain"),
    ("core/signals", "domain"),
    ("core\\signals", "domain"),
    ("primitives/runtime", "domain"),
    ("primitives\\runtime", "domain"),
    ("primitives/base", "domain"),
    ("primitives\\base", "domain"),
    ("primitives/builtin", "domain"),
    ("primitives\\builtin", "domain"),
    # adapter
    ("agent/", "adapter"),
    ("agent\\", "adapter"),
    ("tools/", "adapter"),
    ("tools\\", "adapter"),
    ("governance", "adapter"),
    # utility (catch-all for src/)
    ("execution", "utility"),
    ("core/state", "utility"),
    ("core\\state", "utility"),
    ("core/planning", "utility"),
    ("core\\planning", "utility"),
    ("core/config", "utility"),
    ("core\\config", "utility"),
    ("policy", "utility"),
    ("util", "utility"),
]


def infer_stratum(rel_path: str) -> str:
    """Map a repo-relative file path to an inferred_stratum."""
    rel = rel_path.replace("\\", "/")
    if rel.startswith("tests/") or "/_dev/" in rel or rel.startswith("tools/"):
        return "test"
    for fragment, stratum in STRATUM_RULES:
        frag = fragment.replace("\\", "/")
        if frag in rel:
            return stratum
    return "utility"


def path_to_package(rel_path: str) -> str:
    """Convert a repo-relative file path to a dotted package name."""
    p = Path(rel_path)
    parts = list(p.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


def collect_py_files(root: Path) -> list[Path]:
    result = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in sorted(filenames):
            if fname.endswith(".py"):
                result.append(Path(dirpath) / fname)
    return result


def parse_imports(tree: ast.Module) -> list[str]:
    """Return all import strings found at module level."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = f"{module}.{alias.name}" if module else alias.name
                imports.append(name)
    seen: set[str] = set()
    deduped = []
    for imp in imports:
        if imp not in seen:
            seen.add(imp)
            deduped.append(imp)
    return deduped


def parse_exports(tree: ast.Module) -> list[str]:
    """Return names from __all__ if present, else all public top-level names."""
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            exports = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    exports.append(elt.value)
            return exports

    # No __all__: collect all public top-level definitions
    exports = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                exports.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    exports.append(target.id)
    return exports


def base_name(node: ast.expr) -> str:
    """Extract a simple name from a base class expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    return ""


def extract_class_info(
    cls_node: ast.ClassDef, file_imports: list[str], rel_path: str
) -> dict[str, Any]:
    """Extract structured info from a single class AST node."""
    bases = [base_name(b) for b in cls_node.bases if base_name(b)]
    inherits = [b for b in bases if b not in ("ABC", "Protocol", "object")]
    implements = [b for b in bases if b in ("ABC", "Protocol")]

    public_methods: list[str] = []
    public_attributes: list[str] = []

    for node in cls_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                public_methods.append(node.name)
            # Scan __init__ for self.x assignments
            if node.name == "__init__":
                for stmt in ast.walk(node):
                    if (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Attribute)
                        and isinstance(stmt.targets[0].value, ast.Name)
                        and stmt.targets[0].value.id == "self"
                    ):
                        attr = stmt.targets[0].attr
                        if not attr.startswith("_"):
                            if attr not in public_attributes:
                                public_attributes.append(attr)
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and not node.target.id.startswith("_")
            ):
                if node.target.id not in public_attributes:
                    public_attributes.append(node.target.id)

    # References: names used in class body (annotations, calls, bases)
    references: list[str] = list(inherits) + list(implements)
    for node in ast.walk(cls_node):
        if isinstance(node, ast.Name) and not node.id.startswith("_"):
            if node.id[0].isupper() and node.id not in references:
                references.append(node.id)
        if isinstance(node, ast.Attribute) and not node.attr.startswith("_"):
            if node.attr[0:1].isupper() and node.attr not in references:
                references.append(node.attr)

    # Remove self-reference
    references = [r for r in references if r != cls_node.name]

    package = ".".join(Path(rel_path).parts[:-1]) if Path(rel_path).parts[:-1] else ""
    if Path(rel_path).name == "__init__.py":
        package = ".".join(Path(rel_path).parts[:-1])

    return {
        "name": cls_node.name,
        "file": rel_path.replace("\\", "/"),
        "package": path_to_package(str(Path(rel_path).parent / "__init__").removesuffix("/__init__").removesuffix("\\__init__")),
        "inherits": inherits,
        "implements": implements,
        "public_methods": public_methods,
        "public_attributes": public_attributes,
        "imports": file_imports,
        "references": references,
        "inferred_stratum": infer_stratum(rel_path.replace("\\", "/")),
        "fan_in": 0,
        "fan_out": len(set(references)),
    }


def main() -> None:
    py_files = collect_py_files(REPO_ROOT)

    packages: list[dict] = []
    classes: list[dict] = []
    top_references: list[dict] = []

    for abs_path in py_files:
        rel_path = str(abs_path.relative_to(REPO_ROOT))
        rel_posix = rel_path.replace("\\", "/")

        try:
            source = abs_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(abs_path))
        except SyntaxError:
            continue

        file_imports = parse_imports(tree)

        # Package entry for __init__.py files
        if abs_path.name == "__init__.py":
            pkg_path = str(abs_path.parent.relative_to(REPO_ROOT)).replace("\\", "/")
            pkg_name = path_to_package(rel_path)
            packages.append(
                {
                    "name": pkg_name,
                    "path": pkg_path,
                    "imports": file_imports,
                    "exports": parse_exports(tree),
                }
            )

        # Class entries
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                info = extract_class_info(node, file_imports, rel_path)
                classes.append(info)

    # Build cross-class reference index for fan_in calculation
    class_names = {c["name"] for c in classes}

    # Add import-type top-level references (class → imported class name)
    for cls in classes:
        for imp in cls["imports"]:
            last = imp.split(".")[-1]
            if last in class_names and last != cls["name"]:
                top_references.append(
                    {"source": cls["name"], "target": last, "type": "import"}
                )
        for ref in cls["references"]:
            if ref in class_names and ref != cls["name"]:
                ref_type = "inheritance" if ref in cls["inherits"] + cls["implements"] else "call"
                entry = {"source": cls["name"], "target": ref, "type": ref_type}
                if entry not in top_references:
                    top_references.append(entry)

    # Compute fan_in
    fan_in_counts: dict[str, int] = defaultdict(int)
    for ref in top_references:
        fan_in_counts[ref["target"]] += 1

    for cls in classes:
        cls["fan_in"] = fan_in_counts.get(cls["name"], 0)

    output = {
        "packages": packages,
        "classes": classes,
        "references": top_references,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Written: {OUTPUT_PATH}")
    print(f"  packages : {len(packages)}")
    print(f"  classes  : {len(classes)}")
    print(f"  references: {len(top_references)}")


if __name__ == "__main__":
    sys.exit(main())
