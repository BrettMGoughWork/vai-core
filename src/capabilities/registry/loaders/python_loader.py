"""Registry loaders for discovering primitives from different sources."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.capabilities.primitives.base import PrimitiveBase


class PythonLoader:
    """Loads PythonPrimitive instances from Python modules."""

    @staticmethod
    def load_from_module(module_path: str) -> List[PrimitiveBase]:
        """
        Discover primitives in a Python module.

        Scans the module for PrimitiveBase subclasses and instantiates them.
        """
        import importlib
        module = importlib.import_module(module_path)
        primitives: List[PrimitiveBase] = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, PrimitiveBase):
                primitives.append(attr)
        return primitives

    @staticmethod
    def load_from_directory(directory: Path | str) -> List[PrimitiveBase]:
        """
        Discover primitives by scanning a directory of Python files.

        Each .py file is imported and scanned for PrimitiveBase instances.
        """
        directory = Path(directory)
        primitives: List[PrimitiveBase] = []
        for py_file in sorted(directory.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, PrimitiveBase):
                        primitives.append(attr)
        return primitives


class CLILoader:
    """Loads CLIPrimitive instances from configuration or discovery."""

    @staticmethod
    def load_from_config(config: Dict[str, Any]) -> List[PrimitiveBase]:
        """
        Create CLIPrimitive instances from configuration dictionaries.

        Each entry should have: name, description, command, and optionally
        input_schema, side_effects, timeout_ms.
        """
        from src.capabilities.primitives.cli import CLIPrimitive

        primitives: List[PrimitiveBase] = []
        if isinstance(config, list):
            entries = config
        else:
            entries = config.get("cli_primitives", [])
        for entry in entries:
            prim = CLIPrimitive(
                name=entry["name"],
                description=entry["description"],
                command=entry["command"],
                input_schema=entry.get("input_schema"),
                side_effects=entry.get("side_effects"),
                timeout_ms=entry.get("timeout_ms"),
            )
            primitives.append(prim)
        return primitives


class MCPLoader:
    """Loads MCPPrimitive instances from MCP server configuration."""

    @staticmethod
    def load_from_config(config: Dict[str, Any]) -> List[PrimitiveBase]:
        """
        Create MCPPrimitive instances from server tool listings.

        Expects config with 'servers' key, each with a 'tools' list.
        """
        from src.capabilities.primitives.mcp import MCPPrimitive

        primitives: List[PrimitiveBase] = []
        servers = config.get("mcp_servers", config.get("servers", []))
        for server in servers:
            server_name = server["name"]
            for tool in server.get("tools", []):
                prim = MCPPrimitive(
                    name=f"mcp.{server_name}.{tool['name']}",
                    description=tool.get("description", ""),
                    server_name=server_name,
                    tool_name=tool["name"],
                    input_schema=tool.get("input_schema"),
                    server_config=server.get("config", {}),
                )
                primitives.append(prim)
        return primitives


class PluginLoader:
    """Loads primitives from external plugin packages."""

    @staticmethod
    def discover_plugins(search_paths: Optional[List[str]] = None) -> List[PrimitiveBase]:
        """
        Discover primitives from installed plugins.

        Plugins are Python packages that expose primitives via
        an entry point or convention-based module.
        """
        primitives: List[PrimitiveBase] = []
        try:
            from importlib.metadata import entry_points
            for ep in entry_points(group="vai.primitives"):
                factory = ep.load()
                result = factory()
                if isinstance(result, list):
                    primitives.extend(result)
                elif isinstance(result, PrimitiveBase):
                    primitives.append(result)
        except Exception:
            # Plugin discovery is best-effort
            pass
        return primitives
