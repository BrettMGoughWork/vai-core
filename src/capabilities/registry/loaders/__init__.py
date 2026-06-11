"""Loaders package — CLI, MCP, and Python primitive loaders.

Usage::

    from src.capabilities.registry.loaders import load_external_loaders

    count = load_external_loaders(prim_registry)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.capabilities.registry.loaders.cli_loader import CLILoader
from src.capabilities.registry.loaders.mcp_loader import MCPLoader

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def load_external_loaders(
    registry: PrimitiveRegistry,
    cli_config: dict | None = None,
    mcp_config: dict | None = None,
) -> int:
    """Load CLI and MCP primitives from configuration into *registry*.

    Pass ``cli_config`` and/or ``mcp_config`` dicts to enable each loader.
    Returns the total number of primitives registered.
    """
    count = 0

    if cli_config:
        for prim in CLILoader.load_from_config(cli_config):
            registry.register(prim.name, prim)
            count += 1

    if mcp_config:
        for prim in MCPLoader.load_from_config(mcp_config):
            registry.register(prim.name, prim)
            count += 1

    return count


__all__ = ["load_external_loaders", "CLILoader", "MCPLoader"]
