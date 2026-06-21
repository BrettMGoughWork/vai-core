"""
custom primitives — auto-discovery loader.

Opinionated, user/organisation-specific primitives built on third-party
SDKs (Google, AWS, etc.).  This package lives alongside ``stdlib`` and
follows the same auto-discovery pattern.  Anyone forking the project
can simply delete this directory.

Usage::

    from src.capabilities.primitives.custom import load_all_primitives
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

    registry = PrimitiveRegistry()
    count = load_all_primitives(registry)
    print(f"Registered {count} custom primitives")
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING

from src.capabilities.primitives.base import PrimitiveBase

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


_CUSTOM_DIR = Path(__file__).resolve().parent

# Modules whose imports are expected to fail when optional SDKs are absent.
_OPTIONAL_IMPORTS = {
    "gmail_client",
    "gmail_search",
    "gmail_read",
    "gmail_send",
    "gmail_delete",
}


def load_all_primitives(
    registry: PrimitiveRegistry,
) -> int:
    """Auto-discover all custom primitives and register them into *registry*.

    Scans ``src/capabilities/primitives/custom/`` for ``*Primitive`` classes,
    imports each module, instantiates the class, and registers it by its
    ``.name`` attribute.

    Modules that fail to import (e.g. missing optional SDKs) are silently
    skipped rather than crashing the loader.

    Returns the count of successfully registered primitives.
    """
    count = 0

    for py_file in sorted(_CUSTOM_DIR.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue

        module_path = f"src.capabilities.primitives.custom.{py_file.stem}"

        try:
            module = importlib.import_module(module_path)
        except ImportError:
            continue  # optional dependency not installed — skip gracefully

        for attr_name in dir(module):
            if not attr_name.endswith("Primitive"):
                continue
            cls = getattr(module, attr_name)
            if not isinstance(cls, type) or not issubclass(cls, PrimitiveBase):
                continue
            if cls is PrimitiveBase:
                continue

            try:
                instance = cls()
                registry.register(instance.name, instance)
                count += 1
            except Exception:
                continue

    return count
