import ast

def build_import_graph(files):
    graph = {}
    for path in files:
        module = _module_name_from_path(path)
        graph[module] = set()

        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    graph[module].add(n.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    graph[module].add(node.module.split(".")[0])
    return graph

def _module_name_from_path(path):
    parts = list(path.with_suffix("").parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    return ".".join(parts)