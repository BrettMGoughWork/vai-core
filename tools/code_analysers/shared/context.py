from dataclasses import dataclass

@dataclass
class CheckerContext:
    root: str
    files: list
    import_graph: dict
    config: dict

    def module_for_path(self, path):
        parts = list(path.with_suffix("").parts)
        if "src" in parts:
            parts = parts[parts.index("src") + 1 :]
        return ".".join(parts)