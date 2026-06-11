from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class GovernanceViolation:
    """
    Pure, JSON-serialisable record of a single governance rule breach.

    rule:      machine-readable rule identifier (e.g. "subgoal_id_required").
    field:     name of the offending field, or None if not field-specific.
    message:   human-readable description.
    record_id: ID of the offending record, or None if not applicable.
    """
    rule: str
    field: Optional[str]
    message: str
    record_id: Optional[str]

    def __str__(self) -> str:
        parts = [f"[{self.rule}]"]
        if self.field:
            parts.append(f"field={self.field!r}")
        if self.record_id:
            parts.append(f"id={self.record_id!r}")
        parts.append(self.message)
        return " ".join(parts)


class MemoryGovernanceError(Exception):
    """
    Raised when a governed write or read fails one or more governance rules.

    violations is always non-empty.
    """

    def __init__(self, violations: List[GovernanceViolation]) -> None:
        if not violations:
            raise ValueError("MemoryGovernanceError requires at least one violation")
        self.violations = violations
        super().__init__("; ".join(str(v) for v in violations))
