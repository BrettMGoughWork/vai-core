"""
Primitive types and results (Phase 3.1.2).

Defines the shared types used by PrimitiveBase and all
concrete primitive implementations:
- PrimitiveType: enum (python, cli, mcp)
- PrimitiveResult: dataclass returned by every execute() call
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class PrimitiveType(str, Enum):
    """The runtime type of a primitive."""

    PYTHON = "python"
    CLI = "cli"
    MCP = "mcp"


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
    """Successful output payload (``None`` on error)."""

    error: str | None = None
    """Error message (``None`` on success)."""

    side_effects: list[dict] = field(default_factory=list)
    """Structured list of observed side effects."""

    def __post_init__(self) -> None:
        """Enforce behavioural invariants."""
        if self.status not in ("success", "error"):
            raise ValueError(
                f"status must be 'success' or 'error', got {self.status!r}"
            )
        if self.status == "success" and self.error is not None:
            raise ValueError("error must be None when status is 'success'")
