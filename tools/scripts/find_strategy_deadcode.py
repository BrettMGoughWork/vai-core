"""Find dead modules under src/strategy/ — modules NOT imported from outside src/strategy/.

Architecture: S2 (strategy) is isolated.  Only these touchpoints are allowed to import
from it; imports from anywhere else are stratum violations and do NOT count as liveness
evidence:
  - src/agent/              (S5 → S2 bridge)
  - src/platform/executors/ (S4 → S2 executor bridge)
  - src/runtime/llm/        (S1 → S2 s1_contract bridge)
  - tests/                  (tests may import anything)
"""
import ast
from pathlib import Path
from collections import defaultdict


def resolve_relative(module: str | None, level: int, importer: str) -> str | None:
    """Resolve a relative import to an absolute dotted module name.

    e.g.  from .canonical import X  (module='canonical', level=1)
          in importer='src.strategy.types.hashing'
          → 'src.strategy.types.canonical'
    """
    if module is None:
        return None
    if level == 0:
        return module
    parts = importer.split(".")
    if level > len(parts):
        return None
    base = ".".join(parts[: -level])  # strip 'level' trailing components
    return f"{base}.{module}"


def main():
    repo = Path(__file__).resolve().parent.parent.parent
    strategy_dir = repo / "src" / "strategy"

    def py_to_module(py: Path, root: Path) -> str:
        """Convert a .py path to a dotted module name, handling __init__.py."""
        rel = py.relative_to(root).as_posix().removesuffix(".py")
        if rel.endswith("/__init__"):
            rel = rel[: -len("/__init__")]
        return rel.replace("/", ".")

    # 1. Collect all strategy module paths (dot-notation, with src. prefix)
    strategy_modules: set[str] = set()
    for py in sorted(strategy_dir.rglob("*.py")):
        mod = "src." + py_to_module(py, repo / "src")
        strategy_modules.add(mod)

    # 2. Walk ALL .py files outside src/strategy/ for strategy imports.
    #    Only count imports from ALLOWED touchpoints; everything else is a stratum
    #    violation (e.g. src/capabilities/ importing strategy types) and must NOT
    #    keep strategy modules alive.
    import sys
    include_tests = "--include-tests" in sys.argv

    ALLOWED_IMPORTER_DIRS = [
        "src/agent/",
        "src/platform/executors/",
        "src/runtime/llm/",
    ]
    if include_tests:
        ALLOWED_IMPORTER_DIRS.append("tests/")
    ALLOWED_IMPORTER_DIRS = tuple(ALLOWED_IMPORTER_DIRS)

    external_imports: dict[str, set[str]] = defaultdict(set)  # module -> importers
    directly_live: set[str] = set()
    ignored_importers: dict[str, set[str]] = defaultdict(set)  # violation -> strategy modules

    for py in sorted(repo.rglob("*.py")):
        if ".venv" in py.parts:
            continue
        # Determine importer module name (dotted)
        importer = py_to_module(py, repo)
        # Skip files inside src/strategy/
        if importer.startswith("src.strategy."):
            continue

        # Only count imports from allowed touchpoints (stratum-bridge files).
        # Use path-based matching because the importer module name may not map
        # neatly to the allowed dirs (e.g. standalone scripts, __init__ quirks).
        rel_path = py.relative_to(repo).as_posix()
        allowed = any(rel_path.startswith(d) for d in ALLOWED_IMPORTER_DIRS)

        try:
            text = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Strip BOM (U+FEFF) — occurs in some test files; otherwise ast.parse fails
        if text.startswith("\ufeff"):
            text = text[1:]

        # Fast string scan first
        if "strategy." not in text and "from strategy" not in text:
            continue

        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in strategy_modules:
                        if allowed:
                            directly_live.add(alias.name)
                            external_imports[alias.name].add(importer)
                        else:
                            ignored_importers[importer].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module in strategy_modules:
                    if allowed:
                        directly_live.add(node.module)
                        external_imports[node.module].add(importer)
                    else:
                        ignored_importers[importer].add(node.module)

    # 3. Build intra-strategy import graph: importer -> imported strategy modules
    intra_deps: dict[str, set[str]] = defaultdict(set)  # importer -> modules it imports from strategy

    for py in sorted(strategy_dir.rglob("*.py")):
        importer = "src." + py_to_module(py, repo / "src")
        try:
            text = py.read_text(encoding="utf-8")
            if text.startswith("\ufeff"):
                text = text[1:]
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError):
            continue
        is_package = py.name == "__init__.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in strategy_modules:
                        intra_deps[importer].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    # __init__.py files: py_to_module already stripped `__init__`,
                    # so `from .X` (level=1) means "same package" → adjusted level 0.
                    adjusted_level = max(0, node.level - 1) if is_package else node.level
                    if adjusted_level == 0:
                        resolved = f"{importer}.{node.module}" if node.module else importer
                    else:
                        resolved = resolve_relative(node.module, adjusted_level, importer)
                    if resolved and resolved in strategy_modules:
                        intra_deps[importer].add(resolved)
                elif node.module and node.module in strategy_modules:
                    intra_deps[importer].add(node.module)

    # 4. Transitive closure: follow imports from live modules
    alive = set(directly_live)
    changed = True
    while changed:
        changed = False
        for mod in list(alive):
            for dep in intra_deps.get(mod, set()):
                if dep in strategy_modules and dep not in alive:
                    alive.add(dep)
                    changed = True

    dead = strategy_modules - alive

    # 5. Report
    print("=" * 70)
    print(f"  src/strategy/ dead-code analysis  (architecture-filtered)")
    print(f"  Allowed importers: {', '.join(ALLOWED_IMPORTER_DIRS)}")
    print(f"  {len(strategy_modules)} total modules")
    print(f"  {len(alive)} live  |  {len(dead)} dead")
    print("=" * 70)

    print("\n=== LIVE (directly or transitively imported from ALLOWED sources) ===\n")
    for m in sorted(alive):
        ext = external_imports.get(m, set())
        marker = "(direct external)" if m in directly_live else "(transitive)"
        print(f"  {m}  {marker}")
        if ext:
            for e in sorted(ext)[:5]:
                print(f"    <- {e}")

    print(f"\n=== DEAD ({len(dead)} modules) ===\n")
    for m in sorted(dead):
        print(f"  {m}")

    print(f"\n=== IGNORED IMPORTERS (stratum violations, not counted as liveness) ===\n")
    for importer in sorted(ignored_importers):
        mods = sorted(ignored_importers[importer])
        short = ", ".join(m.removeprefix("src.strategy.") for m in mods[:4])
        if len(mods) > 4:
            short += f", ... (+{len(mods) - 4} more)"
        print(f"  {importer}  ->  {short}")

    # 6. Write list files
    (repo / "tools" / "scripts").mkdir(parents=True, exist_ok=True)
    live_path = repo / "tools" / "scripts" / "strategy_live.txt"
    dead_path = repo / "tools" / "scripts" / "strategy_dead.txt"
    ignored_path = repo / "tools" / "scripts" / "strategy_ignored_importers.txt"
    live_path.write_text("\n".join(sorted(alive)))
    dead_path.write_text("\n".join(sorted(dead)))
    ignored_lines = []
    for importer in sorted(ignored_importers):
        for mod in sorted(ignored_importers[importer]):
            ignored_lines.append(f"{importer}  ->  {mod}")
    ignored_path.write_text("\n".join(ignored_lines))
    print(f"\nWrote {live_path}")
    print(f"Wrote {dead_path}")
    print(f"Wrote {ignored_path}")


if __name__ == "__main__":
    main()
