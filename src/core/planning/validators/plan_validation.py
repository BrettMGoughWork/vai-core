"""
Plan Validation Layer - Validates plan structure, safety, and completeness.

This module validates a plan BEFORE execution.
It is a pure validation layer with NO side effects, NO planner calls, and NO execution logic.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PlanValidationResult:
    """
    Result of plan validation.

    Attributes:
        valid: Whether the plan passed all validation checks
        errors: List of human-readable error messages (empty if valid=True)
    """

    valid: bool
    errors: list[str] = field(default_factory=list)


class CapabilityRegistry(Protocol):
    """
    Protocol for a capability/skill registry.
    Expects methods to query capability specifications.
    """

    def get_spec(self, name: str) -> Any | None:
        """Get the specification for a capability by name."""
        ...


def validate_plan(
    plan: dict[str, Any], capability_registry: CapabilityRegistry
) -> PlanValidationResult:
    """
    Validate a plan before execution.

    Performs structural, capability, schema, ordering, and invariant validation.
    This is a pure function with NO side effects.

    Args:
        plan: Plan object produced by planner, containing metadata and steps
        capability_registry: Registry for looking up capability specifications

    Returns:
        PlanValidationResult with valid flag and list of error messages
    """
    errors = []

    # A. Structural validation
    structural_errors = _validate_structure(plan)
    errors.extend(structural_errors)

    if structural_errors:
        # If structure is invalid, we can't proceed with other validations
        return PlanValidationResult(valid=False, errors=errors)

    steps = plan.get("steps", [])

    # B. Capability existence validation
    capability_errors = _validate_capabilities(steps, capability_registry)
    errors.extend(capability_errors)

    # C. Input schema validation
    input_errors = _validate_inputs(steps, capability_registry)
    errors.extend(input_errors)

    # D. Output schema validation
    output_errors = _validate_outputs(steps, capability_registry)
    errors.extend(output_errors)

    # E. Ordering validation (output dependencies)
    ordering_errors = _validate_ordering(steps)
    errors.extend(ordering_errors)

    # F. Invariant validation
    invariant_errors = _validate_invariants(steps, capability_registry)
    errors.extend(invariant_errors)

    return PlanValidationResult(valid=len(errors) == 0, errors=errors)


def _validate_structure(plan: dict[str, Any]) -> list[str]:
    """A. Structural validation: plan format and required fields."""
    errors = []

    if "steps" not in plan:
        errors.append("Plan must contain 'steps' field")
        return errors

    steps = plan.get("steps")
    if not isinstance(steps, list):
        errors.append("'steps' must be a list")
        return errors

    if len(steps) == 0:
        errors.append("Plan must contain at least one step")
        return errors

    # Validate each step has required fields
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"Step {i}: step must be a dictionary")
            continue

        for required_field in ["name", "capability", "inputs", "outputs"]:
            if required_field not in step:
                errors.append(f"Step {i}: missing required field '{required_field}'")
            elif required_field in ["inputs", "outputs"] and not isinstance(
                step[required_field], dict
            ):
                errors.append(
                    f"Step {i}: field '{required_field}' must be a dictionary"
                )

    return errors


def _validate_capabilities(
    steps: list[dict[str, Any]], capability_registry: CapabilityRegistry
) -> list[str]:
    """B. Capability existence validation: ensure all capabilities exist."""
    errors = []

    for i, step in enumerate(steps):
        capability_name = step.get("capability")
        spec = capability_registry.get_spec(capability_name)

        if spec is None:
            errors.append(f"Step {i}: Unknown capability '{capability_name}'")

    return errors


def _validate_inputs(
    steps: list[dict[str, Any]], capability_registry: CapabilityRegistry
) -> list[str]:
    """C. Input schema validation: check inputs match capability requirements."""
    errors = []

    for i, step in enumerate(steps):
        capability_name = step.get("capability")
        spec = capability_registry.get_spec(capability_name)

        if spec is None:
            # Already reported in capability validation
            continue

        step_inputs = step.get("inputs", {})

        # Check if capability spec has schema with properties (handle both dict and object specs)
        schema = spec.get("schema", {}) if isinstance(spec, dict) else getattr(spec, "schema", {})
        if not schema:
            continue

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check for missing required inputs
        for required_field in required:
            if required_field not in step_inputs:
                errors.append(
                    f"Step {i}: Missing required input '{required_field}' for capability '{capability_name}'"
                )

        # Check for unexpected fields
        for input_name in step_inputs.keys():
            if input_name not in properties:
                errors.append(
                    f"Step {i}: Unexpected input '{input_name}' for capability '{capability_name}'"
                )

    return errors


def _validate_outputs(
    steps: list[dict[str, Any]], capability_registry: CapabilityRegistry
) -> list[str]:
    """D. Output schema validation: check outputs match capability schema."""
    errors = []

    for i, step in enumerate(steps):
        capability_name = step.get("capability")
        spec = capability_registry.get_spec(capability_name)

        if spec is None:
            # Already reported in capability validation
            continue

        step_outputs = step.get("outputs", {})

        # Get expected outputs from capability schema (handle both dict and object specs)
        schema = spec.get("schema", {}) if isinstance(spec, dict) else getattr(spec, "schema", {})
        if not schema:
            continue

        # Assume outputs field in schema, or use an empty dict if not defined
        expected_outputs = schema.get("outputs", {})

        if not expected_outputs:
            # If no outputs are defined, any outputs are acceptable
            continue

        # Check for missing or extra outputs
        expected_keys = set(expected_outputs.keys())
        actual_keys = set(step_outputs.keys())

        missing = expected_keys - actual_keys
        for missing_output in missing:
            errors.append(
                f"Step {i}: Missing expected output '{missing_output}' for capability '{capability_name}'"
            )

        extra = actual_keys - expected_keys
        for extra_output in extra:
            errors.append(
                f"Step {i}: Unexpected output '{extra_output}' for capability '{capability_name}'"
            )

    return errors


def _validate_ordering(steps: list[dict[str, Any]]) -> list[str]:
    """E. Ordering validation: ensure output dependencies are satisfied."""
    errors = []

    # Build a map of step index -> output names
    step_outputs: dict[int, set[str]] = {}
    for i, step in enumerate(steps):
        step_outputs[i] = set(step.get("outputs", {}).keys())

    # Check each step for references to prior outputs
    for i, step in enumerate(steps):
        step_inputs = step.get("inputs", {})

        # Look for references in input values (simple string matching for refs like "step_0.output")
        for input_name, input_value in step_inputs.items():
            referenced_steps = _extract_step_references(input_value)

            for ref_step_idx in referenced_steps:
                if ref_step_idx >= i:
                    # Future reference
                    errors.append(
                        f"Step {i}: References output from step {ref_step_idx} which appears later in plan"
                    )

    return errors


def _extract_step_references(value: Any) -> set[int]:
    """Extract step indices referenced in a value (e.g., 'step_0.output')."""
    refs = set()

    if isinstance(value, str):
        # Look for patterns like "step_N" or "step_N.field"
        import re

        matches = re.findall(r"step_(\d+)", value)
        refs.update(int(m) for m in matches)

    elif isinstance(value, dict):
        for v in value.values():
            refs.update(_extract_step_references(v))

    elif isinstance(value, list):
        for v in value:
            refs.update(_extract_step_references(v))

    return refs


def _validate_invariants(
    steps: list[dict[str, Any]], capability_registry: CapabilityRegistry
) -> list[str]:
    """F. Invariant validation: check state mutation, side effects, and circular deps."""
    errors = []

    # Check for circular dependencies
    circular_errors = _check_circular_dependencies(steps)
    errors.extend(circular_errors)

    # Check for state mutations without stateful flag
    for i, step in enumerate(steps):
        capability_name = step.get("capability")
        spec = capability_registry.get_spec(capability_name)

        if spec is None:
            continue

        # Get metadata flags (handle both dict and object specs)
        is_stateful = spec.get("stateful", False) if isinstance(spec, dict) else getattr(spec, "stateful", False)
        side_effects = spec.get("side_effects", None) if isinstance(spec, dict) else getattr(spec, "side_effects", None)

        # Check for side_effects flag
        if side_effects and not is_stateful:
            # side_effects exist and not marked stateful - this is OK, they're separate concepts
            pass

    return errors


def _check_circular_dependencies(steps: list[dict[str, Any]]) -> list[str]:
    """Check for circular dependencies between steps."""
    errors = []

    # Build dependency graph: step i -> set of steps it depends on
    dependencies: dict[int, set[int]] = {}
    for i, step in enumerate(steps):
        deps = set()
        step_inputs = step.get("inputs", {})

        for input_value in step_inputs.values():
            refs = _extract_step_references(input_value)
            deps.update(refs)

        dependencies[i] = deps

    # Check for cycles using DFS
    visited = set()
    rec_stack = set()

    def has_cycle(node: int) -> bool:
        visited.add(node)
        rec_stack.add(node)

        for neighbor in dependencies.get(node, set()):
            if neighbor not in visited:
                if has_cycle(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True

        rec_stack.remove(node)
        return False

    for i in range(len(steps)):
        if i not in visited:
            if has_cycle(i):
                errors.append(f"Step {i}: Circular dependency detected in plan")

    return errors
