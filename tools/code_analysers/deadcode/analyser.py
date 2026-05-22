import ast
from pathlib import Path
from collections import defaultdict


def collect_python_files(root: str | Path):
    root = Path(root)
    return [
        p for p in root.rglob("*.py")
        if not any(part.startswith(".") or part == "__pycache__" for part in p.parts)
    ]


class SmartDeadCodeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.defined = defaultdict(list)  # name -> list of (type, node)
        self.referenced = set()
        self.ignored = set()              # names marked with @deadcode_ignore

    def _has_deadcode_ignore(self, decorators) -> bool:
        """
        Detect:
          @deadcode_ignore
          @deadcode_ignore(...)
          @x.deadcode_ignore
          @x.deadcode_ignore(...)
        """
        for d in decorators:
            # @deadcode_ignore
            if isinstance(d, ast.Name) and d.id == "deadcode_ignore":
                return True

            # @module.deadcode_ignore
            if isinstance(d, ast.Attribute) and d.attr == "deadcode_ignore":
                return True

            # @deadcode_ignore(...) or @module.deadcode_ignore(...)
            if isinstance(d, ast.Call):
                if isinstance(d.func, ast.Name) and d.func.id == "deadcode_ignore":
                    return True
                if isinstance(d.func, ast.Attribute) and d.func.attr == "deadcode_ignore":
                    return True

        return False

    def visit_FunctionDef(self, node):
        self.defined[node.name].append(("func", node))
        if self._has_deadcode_ignore(node.decorator_list):
            self.ignored.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.defined[node.name].append(("class", node))
        if self._has_deadcode_ignore(node.decorator_list):
            self.ignored.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Load, ast.Del)):
            self.referenced.add(node.id)
        self.generic_visit(node)


def find_dead_code(root_path: str = "."):
    files = collect_python_files(root_path)
    all_defined = {}          # (path, name, typ) -> lineno
    references = set()
    ignored = set()

    for file in files:
        try:
            with open(file, "r", encoding="utf-8") as f:
                source = f.read()
                tree = ast.parse(source, filename=str(file))

            visitor = SmartDeadCodeVisitor()
            visitor.visit(tree)

            rel_path = str(file.relative_to(root_path))

            # Collect definitions
            for name, defs in visitor.defined.items():
                for typ, node in defs:
                    key = (rel_path, name, typ)
                    all_defined[key] = node.lineno

            references.update(visitor.referenced)
            ignored.update(visitor.ignored)

        except Exception as e:
            print(f"Skipping {file}: {e}")

    # Build unused list
    unused = []
    for (path, name, typ), lineno in all_defined.items():
        if name.startswith("_"):
            continue

        # ✅ explicit ignore only
        if name in ignored:
            continue

        # ✅ never referenced
        if name not in references:
            unused.append({
                "path": path,
                "name": name,
                "type": typ,
                "line": lineno
            })

    return sorted(unused, key=lambda x: (x["path"], x["line"]))


if __name__ == "__main__":
    dead = find_dead_code("src")
    print(f"Found {len(dead)} potentially dead items\n")
    for item in dead:
        print(f"{item['path']}:{item['line']}  {item['type']} {item['name']}")