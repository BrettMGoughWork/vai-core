"""
MCPPrimitive — a primitive backed by an MCP server (Phase 3.1.5).

MCP primitives delegate execution to an external MCP server via the
Model Context Protocol, enabling cross‑language and cross‑process
capabilities.
"""

from __future__ import annotations

import json
from typing import Any

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveResult, PrimitiveType
from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class MCPPrimitive(PrimitiveBase):
    """A primitive backed by an MCP server endpoint."""

    __match_args__ = ("name",)

    # Default input schema (overridden per-instance from MCP tools/list).
    # Every MCP tool exposes its own JSON Schema, so the meaningful
    # schema lives on the instance, not the class.
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(
        self,
        *,
        name: str,
        description: str,
        server_name: str,
        tool_name: str,
        input_schema: dict | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            primitive_type=PrimitiveType.MCP,
        )
        self.server_name = server_name
        """Key used to look up the MCP server in the registry."""
        self.tool_name = tool_name
        """The MCP tool to invoke on that server."""
        self.input_schema = input_schema or {"type": "object", "properties": {}}
        """JSON Schema for the tool's input parameters (from MCP tools/list)."""

    # ------------------------------------------------------------------
    # PrimitiveBase interface
    # ------------------------------------------------------------------

    def validate_args(self, args: dict) -> None:
        """
        Validate that ``args`` is a dict suitable for MCP transport.

        All keys must be strings and all values must be
        JSON‑serializable (best‑effort check).
        """
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")

        for key in args:
            if not isinstance(key, str):
                raise ValueError(f"All keys must be strings, got {type(key).__name__}")

        # Best-effort JSON-serialisability check
        try:
            json.dumps(args)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"args values must be JSON-serializable: {exc}") from exc

    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """
        Resolve the MCP server from ``context`` and invoke the tool.

        Expects ``context`` to contain an ``"mcpclient"`` entry whose
        ``get_server()`` method returns the server handle backing
        ``self.server_name``.
        """
        self.validate_args(args)

        # --- resolve MCP client ---
        mcp_client = context.get("mcpclient")
        if mcp_client is None:
            return PrimitiveResult(
                status="error",
                error="missing mcpclient",
            )

        # --- resolve server ---
        server = mcp_client.get_server(self.server_name)
        if server is None:
            return PrimitiveResult(
                status="error",
                error=f"unknown MCP server: {self.server_name!r}",
            )

        # --- invoke tool ---
        try:
            response = server.call_tool(self.tool_name, args)
        except Exception as exc:
            return PrimitiveResult(
                status="error",
                error=str(exc),
            )

        return PrimitiveResult(
            status="success",
            data=response,
        )
