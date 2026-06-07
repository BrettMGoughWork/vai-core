"""Plugin loader stub — directory scanning only; no loading or execution."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def scan_plugins(directory: str) -> List[str]:
    """Scan *directory* for subdirectories that could represent plugins.

    Returns a list of plugin names (directory names without paths).
    Hidden directories and non-directory entries are ignored.
    No modules are imported, no code is executed.
    """
    plugins: List[str] = []
    try:
        for entry in os.scandir(directory):
            if entry.is_dir() and not entry.name.startswith("."):
                plugins.append(entry.name)
    except OSError:
        pass
    return plugins


def load_plugins(registry: PrimitiveRegistry, directory: str) -> None:
    """Placeholder — does not load or register anything."""
    return
