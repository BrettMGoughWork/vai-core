import ast
from pathlib import Path
from collections import defaultdict

def collect_python_files(root: str | Path):
    root = Path(root)
    return [p for p in root.rglob("*.py") 
            if not any(part.startswith(".") or part == "__pycache__" for part in p.parts)]

class SmartDeadCodeVisitor(ast.NodeVisitor):
    def __init__(self):
        self.defined = defaultdict(list)      # name -> list of (type, node)
        self.referenced = set()
        self.registered = set()               # names registered via decorators

    def visit_FunctionDef(self, node):
        self.defined[node.name].append(("func", node))
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.defined[node.name].append(("class", node))

        # Detect registration via decorators (this is the key part)
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):                                   # @register
                if any(k in dec.id.lower() for k in ("register", "factory")):
                    self.registered.add(node.name)
            elif isinstance(dec, ast.Attribute):                            # @factory.something
                if any(k in dec.attr.lower() for k in ("register", "factory")):
                    self.registered.add(node.name)
            elif isinstance(dec, ast.Call):                                 # @factory.register("key", BaseClass)
                if isinstance(dec.func, ast.Attribute):
                    if "register" in dec.func.attr.lower():
                        self.registered.add(node.name)

        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Load, ast.Del)):
            self.referenced.add(node.id)
        self.generic_visit(node)


def find_dead_code(root_path: str = "."):
    files = collect_python_files(root_path)
    all_defined = {}          # (path, name, typ) -> lineno
    references = set()
    registered = set()

    IGNORE_NAMES = {"Factory", "Registry", "Builder", "Provider", "Manager"}

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
            registered.update(visitor.registered)

        except Exception as e:
            print(f"Skipping {file}: {e}")

    # Build unused list with filtering
    unused = []
    for (path, name, typ), lineno in all_defined.items():
        if name.startswith("_"):
            continue

        # 1. Ignore explicitly registered classes
        if name in registered:
            continue

        # 2. Ignore common factory/registry patterns
        if any(ignore in name for ignore in IGNORE_NAMES) or name.endswith(("Factory", "Registry")):
            continue

        # 3. Check if it's actually never referenced
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