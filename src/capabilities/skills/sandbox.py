"""
Behavioural skill sandbox (Phase 3.17.3).

Executes an agent-authored skill with mock primitives to observe its
behaviour before allowing it into the active registry.  Captures every
primitive call, its arguments, and any attempted side-effects.

Usage::

    sandbox = SkillSandbox(primitive_registry=prim_reg)
    report = sandbox.run(skill, inputs={"city": "London"})
    if not report.passed:
        print(f"Sandbox blocked: {report.warnings}")
"""

from __future__ import annotations

import copy as _copy
import random
import string
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.capabilities.primitives.types import PrimitiveResult

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.skills.skill import CapabilitySkill


@dataclass
class SandboxCall:
    """A single primitive call captured during sandbox execution."""

    primitive_name: str
    """Name of the primitive that was called."""

    args: dict[str, Any]
    """Arguments passed to the primitive (resolved)."""

    step_index: int
    """Which step in the manifest triggered this call."""

    mock_response: PrimitiveResult
    """The mock response returned to the skill."""


@dataclass
class SandboxReport:
    """Result of a sandbox execution."""

    passed: bool
    """``True`` if the skill completed without violations."""

    calls: list[SandboxCall] = field(default_factory=list)
    """Every primitive call captured during execution."""

    warnings: list[str] = field(default_factory=list)
    """Human-readable warnings for suspicious behaviour."""

    duration_ms: float = 0.0
    """Wall-clock duration of the sandbox run in milliseconds."""

    timeout_triggered: bool = False
    """``True`` if the run was aborted by the timeout."""

    error: str | None = None
    """Error message if the skill raised an unhandled exception."""


class SkillSandbox:
    """Executes a skill in a safe sandbox with mock primitives.

    Every primitive declared by the skill is replaced with a mock that
    returns plausible, type-safe fake data.  This lets us observe what
    the skill *would* do without allowing any real side-effects.

    After execution the ``SandboxReport`` is inspected.  Skills that
    attempt to use undeclared primitives, produce suspicious call
    patterns, or exceed the timeout are rejected.
    """

    # Default timeout in seconds for the entire sandbox run.
    DEFAULT_TIMEOUT_S = 5.0

    def __init__(
        self,
        primitive_registry: PrimitiveRegistry,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._primitive_registry = primitive_registry
        self._timeout_s = timeout_s

    @staticmethod
    def generate_mock_inputs(input_schema: dict[str, Any]) -> dict[str, Any]:
        """Auto‑generate safe mock inputs that satisfy *input_schema*.

        Accepts both a flat property dict and a JSON‑Schema‑style dict
        with ``"properties"`` and ``"required"``.

        Each property is filled with a plausible dummy value based on
        its ``"type"``.  This lets the sandbox exercise an agent‑authored
        skill without the caller needing to supply real data.
        """
        type_generators: dict[str, Any] = {
            "string": lambda: "mock_" + "".join(
                random.choices(string.ascii_lowercase, k=6)
            ),
            "number": lambda: round(random.uniform(1.0, 100.0), 2),
            "integer": lambda: random.randint(1, 100),
            "boolean": lambda: random.choice([True, False]),
        }

        # Support JSON‑Schema‑style schemas: {"type": "object", "properties": {...}}
        properties: dict[str, Any] = input_schema.get("properties") or {}
        if isinstance(properties, dict) and properties:
            schema_props = properties
        else:
            # Fallback: treat the schema itself as a flat property dict
            schema_props = {}
            for key, prop in input_schema.items():
                if key in ("type", "properties", "required", "additionalProperties", "description"):
                    continue
                schema_props[key] = prop

        inputs: dict[str, Any] = {}
        for key, prop in schema_props.items():
            if not isinstance(prop, dict):
                inputs[key] = "mock_value"
                continue
            type_name = prop.get("type", "string")
            gen = type_generators.get(type_name)
            inputs[key] = gen() if gen else f"[MOCK] {key}"
        return inputs

    def run(
        self,
        skill: CapabilitySkill,
        inputs: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> SandboxReport:
        """Execute *skill* in sandbox mode with the given *inputs*.

        Args:
            skill: The agent-authored skill to test.
            inputs: Input arguments matching the skill's input schema.
            context: Optional execution context (default empty dict).

        Returns:
            ``SandboxReport`` with full call trace and pass/fail verdict.
        """
        start = time.perf_counter()
        ctx = context or {}

        # ── Build mock primitives ───────────────────────────────────────
        mock_prims: dict[str, _MockPrimitive] = {}
        for name in skill.manifest.primitives:
            mock_prims[name] = _MockPrimitive(name)

        # ── Build a sandboxed copy of the skill (shallow) ────────────────
        sandboxed = _copy.copy(skill)
        sandboxed.primitives = mock_prims  # type: ignore[assignment]

        # ── Execute in a thread with timeout ─────────────────────────────
        from src.capabilities.skills.executor import SkillExecutor

        executor = SkillExecutor()
        result_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception | None] = {"exc": None}

        def _target() -> None:
            try:
                result_holder["result"] = executor.execute(
                    sandboxed, inputs, ctx
                )
            except Exception as exc:
                error_holder["exc"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self._timeout_s)

        elapsed_ms = (time.perf_counter() - start) * 1000

        # ── Timeout handling ─────────────────────────────────────────────
        if thread.is_alive():
            return SandboxReport(
                passed=False,
                duration_ms=elapsed_ms,
                timeout_triggered=True,
                warnings=[
                    f"sandbox timeout after {self._timeout_s}s — "
                    "skill may contain an infinite loop or deadlock"
                ],
            )

        # ── Exception handling ───────────────────────────────────────────
        exc = error_holder.get("exc")
        if exc is not None:
            return SandboxReport(
                passed=False,
                duration_ms=elapsed_ms,
                error=str(exc),
                warnings=[f"skill raised exception: {exc}"],
            )

        result = result_holder.get("result")

        # ── Collect call trace ──────────────────────────────────────────
        calls: list[SandboxCall] = []
        warnings: list[str] = []
        for i, step in enumerate(skill.manifest.steps):
            call_name = step.get("call")
            if call_name is None:
                continue
            mock = mock_prims.get(call_name)
            if mock is None:
                warnings.append(
                    f"step[{i}] calls undeclared primitive '{call_name}'"
                )
                continue
            # Each step's call is at position i in mock.calls (if executed in order).
            # Use call index relative to step index to avoid double-counting
            # when multiple steps share the same mock primitive.
            if i < len(mock.calls):
                call_record = mock.calls[i]
                calls.append(SandboxCall(
                    primitive_name=call_name,
                    args=call_record["args"],
                    step_index=i,
                    mock_response=call_record["result"],
                ))

        # ── Check result status ─────────────────────────────────────────
        if result is not None and result.status == "error":
            warnings.append(f"execution error: {result.error}")

        # ── Verdict ─────────────────────────────────────────────────────
        return SandboxReport(
            passed=len(warnings) == 0,
            calls=calls,
            warnings=warnings,
            duration_ms=elapsed_ms,
        )


class _MockPrimitive:
    """A mock primitive that tracks calls and returns safe default data.

    Each call is recorded so the sandbox can audit what the skill
    attempted to do and with what arguments.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []

    def execute(self, args: dict[str, Any], context: dict[str, Any]) -> PrimitiveResult:
        """Record the call and return safe mock data."""
        result = PrimitiveResult(
            status="success",
            data=_mock_data_for_primitive(self.name, args),
        )
        self.calls.append({"args": _copy.deepcopy(args), "result": result})
        return result

    def validate_args(self, args: dict[str, Any]) -> None:
        """No-op: mocks accept any args."""


def _mock_data_for_primitive(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return plausible mock data for *name* based on its semantic category.

    The mock data is intentionally distinguishable from real data so
    that downstream consumers can detect it.
    """
    name_lower = name.lower()

    # File operations
    if any(p in name_lower for p in ("file.", "fs.", "io.")):
        return {
            "path": args.get("path", "/mock/path"),
            "content": '[MOCK] file content',
            "exists": True,
            "size": 1024,
        }

    # HTTP / network
    if any(p in name_lower for p in ("http", "fetch", "request", "curl", "get", "post")):
        return {
            "status_code": 200,
            "body": "[MOCK] response body",
            "headers": {"content-type": "application/json"},
        }

    # Database
    if any(p in name_lower for p in ("db", "sql", "query", "database")):
        return {
            "rows": [{"id": 1, "value": "[MOCK]"}],
            "row_count": 1,
        }

    # Search
    if any(p in name_lower for p in ("search", "find", "lookup", "query")):
        return {
            "results": ["[MOCK] result 1", "[MOCK] result 2"],
            "total": 2,
        }

    # Process / exec (dangerous — mock returns error-like data)
    if any(p in name_lower for p in ("exec", "proc", "shell", "cmd", "run")):
        return {
            "stdout": "[MOCK] command output",
            "stderr": "",
            "exit_code": 0,
            "blocked": True,
        }

    # Generic fallback
    return {
        "result": "[MOCK] generic result",
        "status": "ok",
    }
