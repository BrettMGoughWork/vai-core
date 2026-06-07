"""
MCPPrimitive – a primitive backed by an MCP (Model Context Protocol) server.

MCP primitives delegate execution to an external MCP server,
enabling cross-language and cross-process capabilities.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.capabilities.primitives.base import PrimitiveBase, PrimitiveType


class MCPPrimitive(PrimitiveBase):
    """A primitive backed by an MCP server endpoint."""

    def __init__(
        self,
        name: str,
        description: str,
        server_name: str,
        tool_name: str,
        *,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        side_effects: Optional[list[str]] = None,
        deterministic: bool = False,
        pure: bool = False,
        idempotent: bool = False,
        enabled: bool = True,
        server_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            name=name,
            primitive_type=PrimitiveType.MCP,
            description=description,
            handler=self._call_mcp,
            input_schema=input_schema or {},
            output_schema=output_schema,
            side_effects=side_effects or [],
            deterministic=deterministic,
            pure=pure,
            idempotent=idempotent,
            enabled=enabled,
        )
        self._server_name = server_name
        self._tool_name = tool_name
        self._server_config = server_config or {}

    def _call_mcp(self, **kwargs) -> Any:
        """
        Placeholder MCP call implementation.

        Full MCP integration requires an MCP client transport
        and connection lifecycle management. This will be
        implemented in a later phase when the MCP runtime is ready.
        """
        raise NotImplementedError(
            f"MCP primitive '{self.name}' is not yet implemented. "
            f"Server: {self._server_name}, Tool: {self._tool_name}. "
            f"Arguments: {kwargs}"
        )
