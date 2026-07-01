"""
YAML Pattern Loader
===================

Reads declarative pattern definitions from YAML files under
``config/patterns/`` and registers them into a ``PatternRegistry``.

YAML format (single pattern per file)::

    pattern_id: web_research
    name: Web Research
    description: Search the web and fetch full page content for analysis.
    primitives:
      - web_search
      - web_fetch
    instructions: |
      To research a topic:
      1. Use web_search to find relevant pages matching the query
      2. Analyze the search results to identify the most promising URLs
      3. Use web_fetch to retrieve full content from selected URLs
      4. Synthesize findings into a coherent summary
      5. Present results to the user with source citations
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yaml

from src.domain.patterns import PatternDefinition
from src.capabilities.patterns.pattern_registry import PatternRegistry


def load_patterns_from_directory(
    registry: PatternRegistry,
    directory: str | Path,
) -> List[PatternDefinition]:
    """Scan *directory* for ``*.yaml`` / ``*.yml`` files, each containing
    a single pattern definition, and register each into *registry*.

    Skips non-existent directories and files that fail to parse or validate,
    printing warnings to stderr so the caller knows a pattern was skipped.

    Returns:
        List of successfully loaded ``PatternDefinition`` instances.
    """
    root = Path(directory)
    if not root.is_dir():
        return []

    loaded: List[PatternDefinition] = []
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not isinstance(raw, dict):
                print(
                    f"[pattern-loader] skipping {yaml_path.name}: "
                    f"not a mapping"
                )
                continue
            pattern = _parse_pattern_entry(raw)
            registry.register(pattern)
            loaded.append(pattern)
        except (ValueError, TypeError, KeyError) as exc:
            print(
                f"[pattern-loader] skipping {yaml_path.name}: {exc}"
            )
    return loaded


def _parse_pattern_entry(entry: dict) -> PatternDefinition:
    """Parse a single YAML pattern entry into a ``PatternDefinition``."""
    return PatternDefinition(
        pattern_id=entry["pattern_id"],
        name=entry.get("name", entry["pattern_id"]),
        description=entry.get("description", ""),
        primitives=entry.get("primitives", []),
        instructions=entry.get("instructions", ""),
        version=entry.get("version", "1.0.0"),
    )
