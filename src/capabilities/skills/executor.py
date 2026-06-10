"""
Skill step executor (Phase 3.3.4).

Executes a ``Skill`` by interpreting its ordered steps from the
``SkillManifest``: resolves each primitive by name, calls
``primitive.execute(args, context)``, collects ``PrimitiveResult``
objects, and returns a ``SkillResult``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.types import PrimitiveResult

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill

_TEMPLATE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


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

    @staticmethod
    def _execute_python_block(code: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a sandboxed inline Python block and return the ``result`` dict.

        The code runs with ``globals={}`` and only ``inputs`` available as a
        local variable.  No builtins, imports, I/O, or external state are
        accessible.

        Args:
            code: The Python source code to execute.
            inputs: The skill's input dictionary, exposed as ``inputs``.

        Returns:
            The ``result`` dict captured from the executed code's local scope.

        Raises:
            ValueError: If ``result`` is not defined or is not a ``dict``.
        """
        local_env: dict[str, Any] = {"inputs": inputs}
        exec(code, {"__builtins__": {}}, local_env)

        result = local_env.get("result")
        if result is None:
            raise ValueError("result missing: no 'result' variable defined")
        if not isinstance(result, dict):
            raise ValueError(f"result must be a dict, got {type(result).__name__}")
        return result

    @staticmethod
    def _interpolate_args(
        args: dict[str, Any],
        inputs: dict[str, Any],
        defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Recursively resolve ``{{ key }}`` template tokens in *args* against *inputs*.

        Args:
            args: Step argument dict potentially containing template tokens.
            inputs: User‑supplied input values keyed by name.
            defaults: Fallback values for optional keys not present in *inputs*.

        Returns:
            A new dict with all ``{{ key }}`` tokens replaced by ``inputs[key]``
            (or ``defaults[key]`` if the key is absent from *inputs*).

        Raises:
            KeyError: If a referenced token key is not present in *inputs* or *defaults*.
        """
        resolved_inputs: dict[str, Any] = dict(defaults or {})
        resolved_inputs.update(inputs)

        def _resolve(value: Any) -> Any:
            if isinstance(value, str):
                def _replace(m: re.Match[str]) -> str:
                    key = m.group(1)
                    if key not in resolved_inputs:
                        raise KeyError(
                            f"interpolation token '{{{{{key}}}}}' not found in inputs"
                        )
                    return str(resolved_inputs[key])

                return _TEMPLATE_RE.sub(_replace, value)
            if isinstance(value, dict):
                return {k: _resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_resolve(v) for v in value]
            return value

        return _resolve(dict(args))

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

        defaults: dict[str, Any] = {}
        if skill.input_schema:
            for key, prop_def in skill.input_schema.items():
                if isinstance(prop_def, dict) and "default" in prop_def:
                    defaults[key] = prop_def["default"]

        step_results: list[PrimitiveResult] = []

        for step in skill.manifest.steps:
            on_error: str | None = step.get("on_error")
            has_python = "python" in step
            has_call = "call" in step

            if has_python and has_call:
                raise ValueError("step must not contain both 'python' and 'call'")
            if has_python:
                try:
                    data = self._execute_python_block(step["python"], inputs)
                    result = PrimitiveResult(status="success", data=data)
                except Exception as exc:
                    result = PrimitiveResult(status="error", error=str(exc))
                step_results.append(result)

                if result.status == "error":
                    if on_error == "continue":
                        continue
                    return SkillExecutionResult(
                        status="error",
                        results=step_results,
                        error=result.error,
                    )
                continue

            if not has_call:
                raise ValueError("Invalid step: must contain 'call' or 'python'")

            call: str = step["call"]
            args: dict[str, Any] = step.get("args", {})

            primitive = skill.primitives.get(call)
            if primitive is None:
                raise ValueError(f"unknown primitive: {call}")

            result = primitive.execute(self._interpolate_args(args, inputs, defaults), context)
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
