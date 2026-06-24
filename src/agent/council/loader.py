"""
Council Definition Loader — parse YAML council definitions.

Loads ``CouncilDefinition`` instances from YAML files, following the
same pattern as ``load_agents_from_directory`` and the workflow loader.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from src.domain.council import CouncilDefinition


def load_council_definition(path: str | Path) -> CouncilDefinition:
    """Load a single council definition from a YAML file.

    Parameters
    ----------
    path:
        Filesystem path to the YAML file.

    Returns
    -------
    CouncilDefinition:
        Parsed council definition.

    Raises
    ------
    FileNotFoundError:
        *path* does not exist.
    yaml.YAMLError:
        *path* is not valid YAML.
    ValueError:
        The YAML content failed validation (missing fields, bad types).
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"council definition {path!r} must be a mapping")

    member_ids = raw.get("member_agent_ids", [])
    if not isinstance(member_ids, list):
        raise ValueError(f"council {path!r}: member_agent_ids must be a list")

    _require_field(raw, path, "council_id")
    _require_field(raw, path, "name")
    _require_field(raw, path, "arbitrator_agent_id")

    return CouncilDefinition(
        council_id=raw["council_id"],
        name=raw["name"],
        description=raw.get("description", ""),
        arbitrator_agent_id=raw["arbitrator_agent_id"],
        member_agent_ids=tuple(member_ids),
        max_analysis_tokens=raw.get("max_analysis_tokens", 2000),
        max_counter_tokens=raw.get("max_counter_tokens", 1500),
        require_consensus=raw.get("require_consensus", False),
    )


def load_councils_from_directory(
    directory: str | Path,
) -> List[CouncilDefinition]:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` files and load each as a
    ``CouncilDefinition``.

    Skips non-existent directories and files that fail to parse, printing
    warnings to stderr so the caller knows a definition was skipped.

    Parameters
    ----------
    directory:
        Directory containing council YAML files.

    Returns
    -------
    list[CouncilDefinition]:
        All successfully loaded council definitions.
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    definitions: List[CouncilDefinition] = []
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            defn = load_council_definition(yaml_path)
            definitions.append(defn)
        except (ValueError, yaml.YAMLError) as exc:
            import sys
            print(
                f"[council-loader] skipping {yaml_path.name}: {exc}",
                file=sys.stderr,
            )
    return definitions


def _require_field(raw: dict, path: Path, field: str) -> None:
    """Raise if *field* is missing or empty in *raw*."""
    value = raw.get(field)
    if not value:
        raise ValueError(
            f"council definition {path!r}: required field "
            f"{field!r} is missing or empty"
        )
