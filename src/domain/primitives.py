"""
Primitive types and base class for S3 primitives.

Defines the shared types used by PrimitiveBase and all
concrete primitive implementations:
- PrimitiveType: enum (python, cli, mcp)
- PrimitiveResult: dataclass returned by every execute() call
- PrimitiveBase: abstract base class for all primitives

Canonical home for cross-stratum primitive type sharing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from src.domain._markers import deadcode_ignore


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class PrimitiveType(str, Enum):
    """The runtime type of a primitive."""

    PYTHON = "python"
    CLI = "cli"
    MCP = "mcp"


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
@dataclass
class PrimitiveResult:
    """
    Standardised result returned by every primitive execution.

    Behavioural rules:
    - ``status`` is always ``"success"`` or ``"error"``.
    - When ``status == "success"``, ``error`` must be ``None`` and
      ``data`` carries the output payload.
    - When ``status == "error"``, ``data`` may be ``None`` and
      ``error`` carries the message.
    - ``side_effects`` is always a list (default empty).
    """

    status: Literal["success", "error"]
    """Outcome of the call."""

    data: Any | None = None
    """Payload on success."""

    error: str | None = None
    """Error message on failure."""

    side_effects: list[dict[str, Any]] = field(default_factory=list)
    """Any side-effects recorded during execution."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata for tooling / observability."""

    def __post_init__(self) -> None:
        """Enforce behavioural invariants."""
        if self.status not in ("success", "error"):
            raise ValueError(
                f"status must be 'success' or 'error', got {self.status!r}"
            )
        if self.status == "success" and self.error is not None:
            raise ValueError("error must be None when status is 'success'")

    def __bool__(self) -> bool:
        """Convenience: truthy when status == 'success'."""
        return self.status == "success"


@deadcode_ignore(reason="Dynamically registered primitive, used on demand by LLM/planner")
class PrimitiveBase(ABC):
    """
    Abstract base class for all S3 primitives.

    A primitive is the lowest-level building block in Stratum 3.
    Skills compose primitives into higher-level workflows.

    Every primitive MUST implement two methods:

    * ``validate_args(self, args: dict) -> None``
      Validate that the supplied arguments are well-formed.
      Raise ``ValueError`` on invalid input.

    * ``execute(self, args: dict, context: dict) -> PrimitiveResult``
      Execute the primitive with validated arguments and runtime context.
      Return a ``PrimitiveResult`` indicating success or failure.

    The ``args`` dict is a closed, explicit, serializable dictionary
    --- never ``**kwargs``.  This guarantees determinism and enables
    replayability across S2->S3 calls.
    """

    def __init__(
        self,
        *,
        name: str = "",
        description: str = "",
        primitive_type: PrimitiveType | None = None,
        plugin_name: str | None = None,
        plugin_version: str | None = None,
    ) -> None:
        cls = type(self)
        self.name = name or getattr(cls, "name", "")
        """Canonical primitive name (e.g. ``'file.read'``, ``'json.parse'``)."""

        self.description = description or getattr(cls, "description", "")
        """Human-readable description of what this primitive does."""

        self.primitive_type = primitive_type or getattr(
            cls, "primitive_type", PrimitiveType.PYTHON
        )
        """Runtime type: ``python``, ``cli``, or ``mcp``."""

        self.plugin_name: str | None = plugin_name
        """Owning plugin name, or ``None`` for stdlib primitives."""

        self.plugin_version: str | None = plugin_version
        """Owning plugin version, or ``None`` for stdlib primitives."""

    @abstractmethod
    def validate_args(self, args: dict) -> None:
        """
        Validate that ``args`` is well-formed for this primitive.

        Args:
            args: Closed, serializable dictionary of input arguments.

        Raises:
            ValueError: If ``args`` is invalid.
        """
        ...

    @abstractmethod
    def execute(self, args: dict, context: dict) -> PrimitiveResult:
        """
        Execute the primitive with validated arguments and runtime context.

        Args:
            args: Closed, serializable dictionary of input arguments.
            context: Runtime context dictionary (may include caller info,
                     trace ids, resource limits, etc.).

        Returns:
            ``PrimitiveResult`` indicating success or failure.
        """
        ...
