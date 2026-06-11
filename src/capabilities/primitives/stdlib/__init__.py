"""
stdlib primitives — auto-discovery loader (Phase 2.18.5).
External loaders (CLI, MCP) — Phase 3.20 (Capability Loaders).

Import ``load_all_primitives`` to scan this directory for ``*Primitive``
classes, instantiate them, and register them into a ``PrimitiveRegistry``.
Also loads external primitives (CLI commands, MCP tools) from config.

Usage::

    from src.capabilities.primitives.stdlib import load_all_primitives
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry

    registry = PrimitiveRegistry()
    count = load_all_primitives(registry, cli_config={...}, mcp_config={...})
    print(f"Registered {count} primitives")
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.base import PrimitiveBase

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


_STDLIB_DIR = Path(__file__).resolve().parent


def load_all_primitives(
    registry: PrimitiveRegistry,
    cli_config: dict[str, Any] | None = None,
    mcp_config: dict[str, Any] | None = None,
) -> int:
    """Auto-discover all stdlib primitives and register them into *registry*.

    Scans ``src/capabilities/primitives/stdlib/`` for ``*Primitive`` classes,
    imports each module, instantiates the class, and registers it by its
    ``.name`` attribute.

    If *cli_config* and/or *mcp_config* are provided, also loads CLI
    primitives via ``CLILoader`` and/or MCP primitives via ``MCPLoader``.

    Returns the count of successfully registered primitives.
    """
    count = 0

    for py_file in sorted(_STDLIB_DIR.glob("*.py")):
        if py_file.name.startswith("_") or py_file.name == "__init__.py":
            continue

        module_path = f"src.capabilities.primitives.stdlib.{py_file.stem}"

        try:
            module = importlib.import_module(module_path)
        except Exception:
            continue

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

    # ── external loaders (CLI, MCP) ────────────────────────────────────
    if cli_config is not None or mcp_config is not None:
        from src.capabilities.registry.loaders import load_external_loaders

        count += load_external_loaders(registry, cli_config, mcp_config)

    return count
