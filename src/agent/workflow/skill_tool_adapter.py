"""Phase 5.8b — Skill Tool Adapter

Converts agent-accessible ``CapabilitySkill`` objects into LLM-callable tool
definitions so that agents can discover and invoke skills directly (rather
than only via workflow steps).

Two‑way contract
----------------
**Agent → Tool**: When an LLM response includes ``/invoke-skill`` directive
or a ``tool_calls`` entry with ``name="skill.execute.<skill_name>"``, the
tool adapter can resolve it back to a ``(skill_name, arguments)`` tuple for
the supervisor to execute.

**Tool → Agent**: Each skill becomes a tool whose name is the skill name
(prefixed ``skill.execute.``), description comes from the skill manifest,
and input schema from the skill's validated ``input_schema``.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.skills.skill import CapabilitySkill

# Namespace prefix for skill tools
SKILL_TOOL_PREFIX = "skill.execute"


class SkillToolAdapter:
    """Adapts registry skills into LLM tool definitions.

    Parameters
    ----------
    registry:
        The ``CapabilitySkillRegistry`` containing registered skills.
    """

    def __init__(self, registry: CapabilitySkillRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_tools(
        self, skills_filter: Optional[list[str]] = None
    ) -> List[dict[str, Any]]:
        """Return a list of LLM tool definitions for eligible skills.

        Args:
            skills_filter:
                Optional list of skill names the agent has access to.
                If ``None`` or empty, all skills are returned.
                Supports ``"*"`` to match all.

        Returns a list of dicts in the standard tool format::

            [
                {
                    "name": "skill.execute.<skill_name>",
                    "description": "Skill description from manifest",
                    "input_schema": { ... },
                },
            ]
        """
        tools: list[dict[str, Any]] = []

        for skill in self._registry.list():
            name = skill.manifest.name

            # Filter by agent's accessible skills
            if skills_filter and "*" not in skills_filter:
                if name not in skills_filter:
                    continue

            tool_name = f"{SKILL_TOOL_PREFIX}.{name}"

            # Convert VAI-native schema {field: {type, required, description, enum?, ...}}
            # to JSON Schema {type: "object", properties: {...}, required: [...]}.
            input_schema = skill.input_schema
            if input_schema:
                properties: dict[str, Any] = {}
                required: list[str] = []
                for field_name, field_def in input_schema.items():
                    prop: dict[str, Any] = {
                        "type": field_def.get("type", "string"),
                        "description": field_def.get("description", ""),
                    }
                    if "enum" in field_def:
                        prop["enum"] = field_def["enum"]
                    properties[field_name] = prop
                    if field_def.get("required", False):
                        required.append(field_name)
                input_schema = {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            else:
                input_schema = {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "The primary input for the skill",
                        },
                    },
                }

            tools.append({
                "name": tool_name,
                "description": skill.manifest.description or f"Execute the {name} skill",
                "input_schema": input_schema,
            })

        return tools

    def resolve_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> Optional[Tuple[str, dict[str, Any]]]:
        """Resolve a tool call name/args to a skill name + params.

        Args:
            tool_name: Full tool name (e.g. ``"skill.execute.workspace-mcp.email-manager"``).
            arguments: The arguments dict from the LLM tool call.

        Returns:
            A ``(skill_name, arguments)`` tuple if the tool name
            matches a registered skill, or ``None`` if unknown.
        """
        if not tool_name.startswith(f"{SKILL_TOOL_PREFIX}."):
            return None

        skill_name = tool_name[len(SKILL_TOOL_PREFIX) + 1:]

        skill = self._registry.get(skill_name)
        if skill is None:
            return None

        return skill_name, dict(arguments)
