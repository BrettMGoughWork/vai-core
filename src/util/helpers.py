import os
from pathlib import Path
from typing import Optional


def load_env_file(path: Optional[Path] = None, override: bool = False) -> None:
    """
    Load key=value pairs from a .env file into process environment.
    Lightweight parser for local development; supports:
    - comments and blank lines
    - optional leading `export `
    - quoted or unquoted values
    """
    env_path = path or (Path(__file__).resolve().parents[2] / ".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        if key and (override or key not in os.environ):
            os.environ[key] = value