from pathlib import Path

def collect_python_files(root: str):
    root_path = Path(root)
    files = []
    for path in root_path.rglob("*.py"):
        if any(part.startswith(".") for part in path.parts):
            continue
        files.append(path)
    return files