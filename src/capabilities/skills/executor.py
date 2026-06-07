"""
Skill step executor (Phase 3.3.4).

Executes a ``Skill`` by interpreting its ordered steps from the
``SkillManifest``: resolves each primitive by name, calls
``primitive.execute(args, context)``, collects ``PrimitiveResult``
objects, and returns a ``SkillResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.types import PrimitiveResult

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill


@dataclass
class SkillExecutionResult:
    """Result of executing a skill."""

    status: str
    """``"success"`` or ``"error"``."""

    results: list[PrimitiveResult] = field(default_factory=list)
    """Per‑step results in execution order."""

    error: str | None = None
    """Error message when *status* is ``"error"``."""


class SkillExecutor:
    """Executes a ``CapabilitySkill`` by stepping through its manifest steps sequentially."""

    def execute(
        self,
        skill: CapabilitySkill,
        inputs: dict[str, Any],
        context: dict[str, Any],
    ) -> SkillExecutionResult:
        """Execute *skill* with *inputs* and *context*.

        Args:
            skill: The runtime‑ready ``CapabilitySkill`` to execute.
            inputs: Input arguments (validated against the skill's input schema).
            context: Execution context passed to every primitive call.

        Returns:
            ``SkillExecutionResult`` with per‑step results and overall status.
        """
        skill.validate_inputs(inputs)

        step_results: list[PrimitiveResult] = []

        for step in skill.manifest.steps:
            call: str = step["call"]
            args: dict[str, Any] = step.get("args", {})
            on_error: str | None = step.get("on_error")

            primitive = skill.primitives.get(call)
            if primitive is None:
                raise ValueError(f"unknown primitive: {call}")

            result = primitive.execute(args, context)
            step_results.append(result)

            if result.status == "error":
                if on_error == "continue":
                    continue
                return SkillExecutionResult(
                    status="error",
                    results=step_results,
                    error=result.error,
                )

        # Validate outputs against the final step's data.
        if step_results and step_results[-1].data is not None:
            skill.validate_outputs(step_results[-1].data)

        return SkillExecutionResult(
            status="success",
            results=step_results,
            error=None,
        )
