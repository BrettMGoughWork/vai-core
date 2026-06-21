"""
PrimitiveToolAdapter — exposes all Primitives as LLM-callable tools.

Each primitive in the ``PrimitiveRegistry`` becomes an LLM tool with the
name ``primitive.<primitive_name>``, description from the primitive's
``.description``, and input schema derived from the primitive's ``input_schema``
(or a generic object schema if none is set).

This enables the LLM to discover and invoke any registered primitive
directly via native ``tool_calls`` (no ``/invoke-skill`` text directives).
"""

from __future__ import annotations

from typing import Any, Optional

from src.capabilities.registry.primitive_registry import PrimitiveRegistry

PRIMITIVE_TOOL_PREFIX = "primitive"


class PrimitiveToolAdapter:
    """Adapts a ``PrimitiveRegistry`` into LLM tool definitions.

    Parameters
    ----------
    registry:
        The ``PrimitiveRegistry`` containing registered primitives.
    """

    def __init__(self, registry: PrimitiveRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return a list of LLM tool definitions for all primitives.

        Returns a list of dicts in OpenAI-compatible tool format::

            [
                {
                    "name": "primitive.<name>",
                    "description": "...",
                    "input_schema": { ... },
                },
            ]
        """
        tools: list[dict[str, Any]] = []

        for primitive in self._registry.list():
            tool_name = f"{PRIMITIVE_TOOL_PREFIX}.{primitive.name}"

            # Use the primitive's input_schema if available, else generic
            input_schema = getattr(primitive, "input_schema", None)
            if not input_schema:
                input_schema = {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "The primary input for the primitive",
                        },
                    },
                }

            tools.append({
                "name": tool_name,
                "description": primitive.description or f"Execute the {primitive.name} primitive",
                "input_schema": input_schema,
            })

        return tools

    def resolve_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Optional[tuple[str, dict[str, Any]]]:
        """Resolve a tool call name/args to a primitive name + params.

        Args:
            tool_name: Full tool name (e.g. ``"primitive.mcp.google-workspace-mcp.sendEmail"``).
            arguments: The arguments dict from the LLM tool call.

        Returns:
            A ``(primitive_name, arguments)`` tuple if the tool name
            matches a registered primitive, or ``None`` if unknown.
        """
        if not tool_name.startswith(f"{PRIMITIVE_TOOL_PREFIX}."):
            return None

        primitive_name = tool_name[len(PRIMITIVE_TOOL_PREFIX) + 1:]

        primitive = self._registry.get(primitive_name)
        if primitive is None:
            return None

        return primitive_name, dict(arguments)
