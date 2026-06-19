"""Phase 5.8 — Workflow Tool Adapter

Converts registered workflow definitions into LLM‑callable tool definitions
so that agents can discover and invoke workflows as tools during LLM calls
(rather than only via explicit ``/workflow`` commands).

Two‑way contract
----------------
**Agent → Tool**: When an LLM response includes a ``tool_calls`` entry
with ``name="workflow.execute.<workflow_id>"``, the tool adapter can
resolve it back to a ``(WorkflowDefinition, params)`` tuple for the
supervisor to start a workflow.

**Tool → Agent**: Each workflow becomes a tool whose name is the
workflow ID (prefixed ``workflow.execute.``), description comes from
the YAML ``description`` field, and input schema from the YAML
``input_schema`` field (if present).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.agent.workflow.workflow_definition import WorkflowDefinition
from src.agent.workflow.registry import WorkflowRegistry

# Namespace prefix for workflow tools
WORKFLOW_TOOL_PREFIX = "workflow.execute"


class WorkflowToolAdapter:
    """Adapts registered workflows into LLM tool definitions.

    Parameters
    ----------
    registry:
        The ``WorkflowRegistry`` containing workflow definitions.
    exclude_ids:
        Optional set of workflow IDs to exclude from tool listing
        (e.g. internal workflows not meant for agent discovery).
    """

    def __init__(
        self,
        registry: WorkflowRegistry,
        exclude_ids: Optional[set[str]] = None,
    ) -> None:
        self._registry = registry
        self._exclude_ids = exclude_ids or set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return a list of LLM tool definitions for all eligible workflows.

        Returns a list of dicts in the standard tool format::

            [
                {
                    "name": "workflow.execute.workflow_id",
                    "description": "Workflow description from YAML",
                    "input_schema": { ... },
                },
            ]

        Workflows whose IDs are in ``exclude_ids`` are omitted.
        """
        tools: list[dict[str, Any]] = []
        for defn in self._registry.list():
            if defn.workflow_id in self._exclude_ids:
                continue

            tool_name = f"{WORKFLOW_TOOL_PREFIX}.{defn.workflow_id}"

            # Build the input schema — prefer explicit input_schema, fall
            # back to a sensible default based on the workflow's known
            # context keys.
            input_schema = defn.input_schema or {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The primary input text for the workflow",
                    },
                },
            }

            tools.append({
                "name": tool_name,
                "description": defn.description or f"Execute the {defn.name} workflow",
                "input_schema": input_schema,
            })

        return tools

    def resolve_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Optional[Tuple[WorkflowDefinition, dict[str, Any]]]:
        """Resolve a tool call name/args to a workflow definition + params.

        Args:
            tool_name: Full tool name (e.g. ``"workflow.execute.demo_chat"``).
            arguments: The arguments dict from the LLM tool call.

        Returns:
            A ``(WorkflowDefinition, params)`` tuple if the tool name
            matches a registered workflow, or ``None`` if the tool name
            is unknown or refers to a workflow outside this adapter's scope.
        """
        if not tool_name.startswith(f"{WORKFLOW_TOOL_PREFIX}."):
            return None

        workflow_id = tool_name[len(WORKFLOW_TOOL_PREFIX) + 1:]

        defn = self._registry.get(workflow_id)
        if defn is None:
            return None

        # Build initial workflow context from tool call arguments
        params: dict[str, Any] = dict(arguments)

        return defn, params
