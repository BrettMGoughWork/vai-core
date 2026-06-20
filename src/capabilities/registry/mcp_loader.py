"""
MCP primitive loader — scans JSON/YAML server manifests and registers MCPPrimitive instances.

DEPRECATED: This module uses static YAML/JSON manifests to define MCP server tools.
Auto-discovery via MCPClientManager.discover_tools() (tools/list protocol) now
replaces this — MCP servers need only be listed in config/mcp_servers.yaml and
their tools are discovered automatically at startup.

Kept for backward compatibility during migration. Will be removed in the clean sweep.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Dict, List

import yaml

from src.capabilities.primitives.mcp import MCPPrimitive

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry


def load_mcp_primitives(registry: PrimitiveRegistry, directory: str) -> list[str]:
    """Scan *directory* for ``.json``, ``.yaml``, and ``.yml`` files defining
    MCP server manifests, extract tool definitions, and register the resulting
    ``MCPPrimitive`` instances into *registry*.

    Each manifest must parse to a dict containing the required top-level keys:
        ``server_name`` (str), ``tools`` (list).

    Each tool entry must contain:
        ``name`` (str), ``description`` (str).

    Returns:
        A list of registered primitive names (e.g. ``["gmail.send", "drive.read"]``).
    """

    EXTENSIONS: tuple[str, ...] = (".json", ".yaml", ".yml")
    registered: list[str] = []

    try:
        entries = os.scandir(directory)
    except OSError:
        return registered

    for entry in entries:
        if not entry.is_file():
            continue

        _root, ext = os.path.splitext(entry.name)
        if ext.lower() not in EXTENSIONS:
            continue

        try:
            with open(entry.path, "r", encoding="utf-8") as fh:
                if ext.lower() == ".json":
                    manifest: Dict[str, Any] = json.load(fh)
                else:
                    manifest = yaml.safe_load(fh)
        except Exception:
            continue

        if not isinstance(manifest, dict):
            continue

        server_name: Any = manifest.get("server_name")
        tools: Any = manifest.get("tools")

        if not isinstance(server_name, str) or not isinstance(tools, list):
            continue

        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_name: Any = tool.get("name")
            tool_description: Any = tool.get("description")

            if not isinstance(tool_name, str) or not isinstance(tool_description, str):
                continue

            try:
                primitive = MCPPrimitive(
                    name=f"{server_name}.{tool_name}",
                    description=tool_description,
                    server_name=server_name,
                    tool_name=tool_name,
                )
            except Exception:
                continue

            registry.register(primitive.name, primitive)
            registered.append(primitive.name)

    return registered
