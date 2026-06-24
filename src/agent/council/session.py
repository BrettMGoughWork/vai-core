"""Runtime state tracking for a single council deliberation session."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from src.domain.council import CouncilDefinition


@dataclass
class CouncilSession:
    """Runtime state tracking for a single council deliberation.

    Fields
    ------
    session_id:
        Unique identifier for this deliberation session.
    council_def:
        The council configuration.
    problem_statement:
        The problem put to the council.
    phase:
        Current phase: ``convene`` | ``analysis`` | ``counter`` |
        ``arbitration`` | ``complete``.
    analyses:
        Map of member_agent_id → analysis text.
    counters:
        Map of member_agent_id → counter-analysis text.
    decision:
        Final decision text, set after arbitration.
    started_at:
        Timestamp when the session was created.
    completed_at:
        Timestamp when the session completed (or None).
    """

    session_id: str
    council_def: CouncilDefinition
    problem_statement: str
    phase: str = "convene"
    analyses: Dict[str, str] = field(default_factory=dict)
    counters: Dict[str, str] = field(default_factory=dict)
    decision: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @classmethod
    def create(cls, council_def: CouncilDefinition, problem: str) -> CouncilSession:
        """Create a new session in the ``convene`` phase."""
        return cls(
            session_id=str(uuid.uuid4()),
            council_def=council_def,
            problem_statement=problem,
            phase="convene",
            started_at=datetime.now(),
        )

    def transition_to(self, phase: str) -> None:
        """Advance the session to *phase*.

        Valid transitions:
            convene → analysis → counter → arbitration → complete
        """
        _VALID_PHASES = [
            "convene",
            "analysis",
            "counter",
            "arbitration",
            "complete",
        ]
        if phase not in _VALID_PHASES:
            raise ValueError(
                f"invalid phase {phase!r}; "
                f"valid: {_VALID_PHASES}"
            )
        current_idx = _VALID_PHASES.index(self.phase)
        next_idx = _VALID_PHASES.index(phase)
        if next_idx != current_idx + 1:
            raise ValueError(
                f"cannot transition from {self.phase!r} to {phase!r}"
            )
        self.phase = phase

    def complete(self) -> None:
        """Mark the session as complete."""
        self.phase = "complete"
        self.completed_at = datetime.now()
