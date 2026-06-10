"""
PrimitiveBase — abstract base class for all S3 primitives (Phase 3.1.1).

Defines the unified execution contract that every primitive must
fulfil: ``execute(args, context) -> PrimitiveResult``.

This module is the single abstraction boundary between Stratum 2
(Planning + Execution) and Stratum 3 (Capabilities).  Every concrete
primitive type (Python, CLI, MCP) subclasses PrimitiveBase and
implements its own validation and execution logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult


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
    — never ``**kwargs``.  This guarantees determinism and enables
    replayability across S2→S3 calls.
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
        # Resolve from class-level attributes when not passed explicitly
        # (supports the zero-boilerplate plugin-author pattern where
        #  name/description/primitive_type are class attributes only).
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
        """Owning plugin name, or ``None`` for stdlib primitives (3.15)."""

        self.plugin_version: str | None = plugin_version
        """Owning plugin version, or ``None`` for stdlib primitives (3.15)."""

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
