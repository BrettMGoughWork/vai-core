"""
Skill step executor (Phase 3.3.4).

Executes a ``Skill`` by interpreting its ordered steps from the
``SkillManifest``: resolves each primitive by name, calls
``primitive.execute(args, context)``, collects ``PrimitiveResult``
objects, and returns a ``SkillResult``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.types import PrimitiveResult

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill

_TEMPLATE_RE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")  # matches strings that are exactly one token
_ANY_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")  # matches tokens anywhere in a string
# Matches {{ key == 'value' }} conditions used in switch/case branches
_SWITCH_CASE_RE = re.compile(
    r"^\{\{\s*(\w+)\s*==\s*'([^']*)'\s*\}\}$"
)


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
    def _resolve_dotted_key(key: str, inputs: dict[str, Any]) -> Any | None:
        """Resolve a possibly-dotted key against *inputs*.

        ``"params.query"`` traverses ``inputs["params"]["query"]``.
        A simple key like ``"action"`` returns ``inputs["action"]``.
        Returns ``None`` if any part of the path is missing.
        """
        parts = key.split(".")
        val: Any = inputs
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                return None
        return val

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
        input_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Recursively resolve ``{{ key }}`` template tokens in *args* against *inputs*.

        Args:
            args: Step argument dict potentially containing template tokens.
            inputs: User‑supplied input values keyed by name.
            defaults: Fallback values for optional keys not present in *inputs*.
            input_schema: Skill input schema for type-aware casting.

        Returns:
            A new dict with all ``{{ key }}`` tokens replaced by ``inputs[key]``
            (or ``defaults[key]`` if the key is absent from *inputs*).

        Raises:
            KeyError: If a referenced token key is not present in *inputs* or *defaults*.
        """
        resolved_inputs: dict[str, Any] = dict(defaults or {})
        resolved_inputs.update(inputs)

        def _cast(key: str, raw: Any) -> Any:
            """Cast *raw* value to the type declared in *input_schema*, if available."""
            if input_schema is None or key not in input_schema:
                return raw
            prop = input_schema[key]
            if not isinstance(prop, dict):
                return raw
            type_name = prop.get("type", "any")
            if type_name == "number":
                try:
                    return float(raw) if "." in str(raw) else int(raw)
                except (ValueError, TypeError):
                    return raw
            if type_name == "integer":
                try:
                    return int(raw)
                except (ValueError, TypeError):
                    return raw
            if type_name == "boolean":
                if isinstance(raw, str) and raw.lower() in ("true", "1", "yes"):
                    return True
                if isinstance(raw, str) and raw.lower() in ("false", "0", "no"):
                    return False
                return bool(raw)
            return raw

        # Regex for whole-step references like {{step-1}}, {{step-2}}, etc.
        _STEP_REF_RE = re.compile(r"^step-\d+$")

        def _resolve(value: Any) -> Any:
            if isinstance(value, str):
                # Bare token: "{{ key }}" → return cast raw value
                m = _TEMPLATE_RE.match(value)
                if m:
                    key = m.group(1)
                    resolved = SkillExecutor._resolve_dotted_key(key, resolved_inputs)
                    if resolved is not None:
                        return _cast(key, resolved)
                    # Fallback: {{step-N}} → stringified accumulated inputs
                    if _STEP_REF_RE.match(key):
                        return json.dumps(resolved_inputs, default=str)
                    raise KeyError(
                        f"interpolation token '{{{{{key}}}}}' not found in inputs"
                    )

                # Embedded tokens: "prefix {{key}} suffix" → stringify
                def _replace(m: re.Match[str]) -> str:
                    key = m.group(1)
                    resolved = SkillExecutor._resolve_dotted_key(key, resolved_inputs)
                    if resolved is not None:
                        return str(resolved)
                    # Fallback: {{step-N}} → stringified accumulated inputs
                    if _STEP_REF_RE.match(key):
                        return json.dumps(resolved_inputs, default=str)
                    raise KeyError(
                        f"interpolation token '{{{{{key}}}}}' not found in inputs"
                    )

                return _ANY_TEMPLATE_RE.sub(_replace, value)
            if isinstance(value, dict):
                return {k: _resolve(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_resolve(v) for v in value]
            return value

        return _resolve(dict(args))

    @staticmethod
    def _interpolate_value(
        value: str | dict[str, Any],
        inputs: dict[str, Any],
        step_results: list[PrimitiveResult],
    ) -> str | dict[str, Any]:
        """Resolve ``{{key}}`` tokens in *value* against *inputs* and prior results.

        If *value* is a dict, returns a new dict with each string field interpolated.
        Non‑string fields are returned as‑is.

        ``{{N}}`` references resolve to the data of ``step_results[N]``.
        Named references like ``{{result.value}}`` resolve from the last result.
        """
        if isinstance(value, dict):
            return {
                k: SkillExecutor._interpolate_value(v, inputs, step_results)
                for k, v in value.items()
            }
        if not isinstance(value, str):
            return value

        _STEP_REF_RE = re.compile(r"^\d+$")

        def _resolve_token(m: re.Match[str]) -> str:
            key = m.group(1)
            # {{N}} → step_results[N]
            if _STEP_REF_RE.match(key):
                idx = int(key)
                if idx < len(step_results):
                    sr = step_results[idx]
                    return str(sr.data.get("value", sr.data))
            # {{result}} or {{result.X}} → last result
            if key.startswith("result"):
                parts = key.split(".", 1)
                if step_results:
                    last = step_results[-1]
                    if len(parts) == 1:
                        return str(last.data.get("value", last.data))
                    field = parts[1]
                    return str(last.data.get(field, ""))
            # {{key}} or {{key.subkey}} → inputs / inputs[key][subkey]
            resolved = SkillExecutor._resolve_dotted_key(key, inputs)
            if resolved is not None:
                return str(resolved)
            # {{step-N}} → stringified accumulated inputs
            if key.startswith("step-"):
                return json.dumps(inputs, default=str)
            raise KeyError(
                f"interpolation token '{{{{{key}}}}}' not found in inputs"
            )

        return _ANY_TEMPLATE_RE.sub(_resolve_token, value)

    @staticmethod
    def _evaluate_switch_case(
        condition: str,
        inputs: dict[str, Any],
        step_results: list[PrimitiveResult],
    ) -> bool:
        """Evaluate a single ``case`` condition string against *inputs*."""
        m = _SWITCH_CASE_RE.match(condition)
        if m:
            key, expected = m.group(1), m.group(2)
            resolved = SkillExecutor._interpolate_value(
                f"{{{{ {key} }}}}", inputs, step_results,
            )
            return resolved == expected
        # If the condition is a bare key name, treat as truthiness check.
        if condition in inputs:
            resolved = SkillExecutor._interpolate_value(
                f"{{{{ {condition} }}}}", inputs, step_results,
            )
            return bool(resolved)
        return False

    def _execute_switch_step(
        self,
        step: dict,
        inputs: dict[str, Any],
        step_results: list[PrimitiveResult],
        skill: "CapabilitySkill",
        context: dict[str, Any] | None = None,
    ) -> PrimitiveResult:
        """Evaluate a ``switch`` step — find a matching case and run its sub-steps."""
        branches: list[dict] = step["switch"]
        matched_steps: list[dict] | None = None

        for branch in branches:
            if "default" in branch:
                continue
            condition = branch.get("case", "")
            if self._evaluate_switch_case(condition, inputs, step_results):
                matched_steps = branch.get("steps", [])
                break

        if matched_steps is None:
            for branch in branches:
                if "default" in branch:
                    # YAML: default: is null; steps are at the same level.
                    matched_steps = branch.get("steps", [])
                    break

        if not matched_steps:
            return PrimitiveResult(status="success", data={"value": None})

        for sub in matched_steps:
            if "return" in sub:
                val = SkillExecutor._interpolate_value(
                    sub["return"], inputs, step_results,
                )
                return PrimitiveResult(status="success", data={"value": val})
            if "call" in sub:
                call = sub["call"]
                args = sub.get("args") or sub.get("with", {})
                primitive = skill.primitives.get(call)
                if primitive is None:
                    return PrimitiveResult(
                        status="error", error=f"Primitive '{call}' not found",
                    )
                from copy import deepcopy
                resolved = SkillExecutor._interpolate_args(
                    deepcopy(args), inputs, None, skill.input_schema,
                )
                result = primitive.execute(resolved, context=context or inputs)
                step_results.append(result)
                if result.status == "error":
                    return result
                # Store ``as`` alias so subsequent steps can interpolate
                alias = sub.get("as")
                if alias and result.data is not None:
                    inputs[alias] = result.data.get("value", result.data) if isinstance(result.data, dict) else result.data

        return PrimitiveResult(status="success", data={"value": None})

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
            has_return = "return" in step

            if has_python and has_call:
                raise ValueError("step must not contain both 'python' and 'call'")

            # ── return step ── (terminal: emit final output)
            if has_return:
                return_val = self._interpolate_value(
                    step["return"], inputs, step_results,
                )
                step_results.append(
                    PrimitiveResult(status="success", data={"value": return_val})
                )
                return SkillExecutionResult(
                    status="success",
                    results=step_results,
                )

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

            # ── switch step ── (conditional branch)
            if "switch" in step:
                result = self._execute_switch_step(step, inputs, step_results, skill, context)
                step_results.append(result)
                if result.status == "error":
                    return SkillExecutionResult(
                        status="error", results=step_results, error=result.error,
                    )
                continue

            if not has_call:
                raise ValueError("Invalid step: must contain 'call' or 'python'")

            call: str = step["call"]
            # Accept both "args" and "with" as the argument bag for a call step.
            args: dict[str, Any] = step.get("args") or step.get("with", {})

            primitive = skill.primitives.get(call)
            if primitive is None:
                raise ValueError(f"unknown primitive: {call}")

            result = primitive.execute(self._interpolate_args(args, inputs, defaults, skill.input_schema), context)
            step_results.append(result)

            # Store ``as`` alias so subsequent steps can interpolate
            alias = step.get("as")
            if alias and result.data is not None:
                inputs[alias] = result.data.get("value", result.data) if isinstance(result.data, dict) else result.data

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
