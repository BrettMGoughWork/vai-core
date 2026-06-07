"""MCP primitive loader — loads MCPPrimitive instances from server configuration."""

from __future__ import annotations

from typing import Any, Dict, List

from src.capabilities.primitives.base import PrimitiveBase


class MCPLoader:
    """Loads MCPPrimitive instances from MCP server configuration."""

    @staticmethod
    def load_from_config(config: Dict[str, Any]) -> List[PrimitiveBase]:
        """Create MCPPrimitive instances from server tool listings.

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


__all__ = ["MCPLoader"]
