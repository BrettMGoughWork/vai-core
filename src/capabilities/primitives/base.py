"""
Primitive metadata spec (Phase 3.0.2).

Defines the shape of a primitive: name, type, function signature,
description, declared side effects, input/output schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class PrimitiveType(str, Enum):
    """The runtime type of a primitive."""
    PYTHON = "python"
    CLI = "cli"
    MCP = "mcp"


@dataclass
class PrimitiveResult:
    """Standardised return value from primitive execution."""

    success: bool
    """Whether the call succeeded without error."""

    value: Any = None
    """The return value on success."""

    error: Optional[str] = None
    """Error message on failure."""

    error_type: Optional[str] = None
    """Machine-readable error category."""

    duration_ms: Optional[float] = None
    """Wall-clock execution time in milliseconds."""


@dataclass
class PrimitiveBase:
    """
    Base class for all primitives.

    A primitive is the lowest-level building block in Stratum 3.
    Skills compose primitives into higher-level workflows.
    """

    name: str
    """Unique, dot-separated hierarchical name (e.g. 'file.read', 'json.parse')."""

    primitive_type: PrimitiveType
    """Runtime type: python, cli, or mcp."""

    description: str
    """Human-readable description of what this primitive does."""

    handler: Callable[..., Any]
    """Python callable that executes the primitive."""

    input_schema: Dict[str, Any] = field(default_factory=dict)
    """JSON Schema describing expected input arguments."""

    output_schema: Optional[Dict[str, Any]] = None
    """JSON Schema describing expected output shape (optional)."""

    side_effects: List[str] = field(default_factory=list)
    """Declared side effects (e.g. 'read', 'write', 'network', 'system')."""

    deterministic: bool = True
    """Whether the primitive is deterministic (same input → same output)."""

    pure: bool = True
    """Whether the primitive is pure (no side effects, no external state)."""

    idempotent: bool = True
    """Whether repeated calls with the same input yield the same result."""

    enabled: bool = True
    """Whether the primitive is enabled for use."""

    def execute(self, **kwargs) -> PrimitiveResult:
        """Execute the primitive with validated arguments."""
        import time
        start = time.perf_counter()
        try:
            result = self.handler(**kwargs)
            return PrimitiveResult(
                success=True,
                value=result,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:
            return PrimitiveResult(
                success=False,
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=(time.perf_counter() - start) * 1000,
            )
