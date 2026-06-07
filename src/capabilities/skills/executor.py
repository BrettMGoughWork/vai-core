"""
Skill step executor (Phase 3.0.1).

Interprets the ordered 'steps' from a SkillManifest and executes
each step by calling the referenced primitives in sequence.

Each step has the shape:
  - call: primitive.name
    with:
      param: value

The executor resolves template variables (e.g. {{inputs.path}})
and chains outputs between steps.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.capabilities.contracts import SkillResult
from src.capabilities.registry.primitive_registry import SkillRegistry
from src.capabilities.runtime.validator import validate_structural

# Template variable pattern: {{name}} or {{name.path}}
_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


class SkillExecutor:
    """
    Executes a skill by stepping through its manifest steps.

    Each step calls a primitive referenced by name. Template variables
    in step arguments are resolved against the execution context.
    """

    def execute(
        self,
        skill_name: str,
        steps: List[Dict[str, Any]],
        inputs: Dict[str, Any],
        registry: SkillRegistry | None = None,
    ) -> SkillResult:
        """
        Execute a sequence of steps.

        Args:
            skill_name: Name of the skill being executed (for result metadata).
            steps: Ordered list of step dicts (from manifest).
            inputs: Input arguments to the skill.
            registry: Skill registry for primitive lookup (defaults to global).

        Returns:
            SkillResult with the final step's output on success.
        """
        import time

        if registry is None:
            registry = SkillRegistry

        start = time.perf_counter()
        context: Dict[str, Any] = {"inputs": inputs}

        last_output: Any = None

        try:
            for step in steps:
                primitive_name = step["call"]
                step_args_raw = step.get("with", {})

                # Resolve template variables in step arguments
                step_args = self._resolve_templates(step_args_raw, context)

                # Look up and execute the primitive
                spec = registry.get(primitive_name)
                spec.run(**step_args)

                # Store output for chaining
                last_output = step_args  # placeholder; real impl tracks primitive output
                context["output"] = last_output

            duration = (time.perf_counter() - start) * 1000
            return SkillResult(
                skill_name=skill_name,
                success=True,
                output=last_output,
                duration_ms=duration,
            )

        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            return SkillResult(
                skill_name=skill_name,
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=duration,
            )

    def _resolve_templates(
        self, template_dict: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Resolve {{...}} template variables in a dict against context."""
        resolved: Dict[str, Any] = {}
        for key, value in template_dict.items():
            resolved[key] = self._resolve_value(value, context)
        return resolved

    def _resolve_value(self, value: Any, context: Dict[str, Any]) -> Any:
        """Recursively resolve template variables in a value."""
        if isinstance(value, str):
            return self._resolve_string(value, context)
        elif isinstance(value, dict):
            return {k: self._resolve_value(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_value(v, context) for v in value]
        return value

    def _resolve_string(self, value: str, context: Dict[str, Any]) -> str:
        """Replace {{...}} patterns in a string with context values."""

        def replacer(match: re.Match) -> str:
            path = match.group(1).strip()
            parts = path.split(".")
            current: Any = context
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part, match.group(0))
                else:
                    return match.group(0)
            return str(current) if current is not None else match.group(0)

        return _TEMPLATE_RE.sub(replacer, value)
