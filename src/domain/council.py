"""
Council Arbitration — domain types.

A council is a multi-agent deliberation pattern where multiple agents
analyse the same problem from different perspectives, challenge each
other's reasoning, and an impartial arbitrator synthesises a final decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class CouncilDefinition:
    """Declarative definition of a council — members, arbitrator, constraints.

    Fields
    ------
    council_id:
        Stable, unique identifier (e.g. ``general-nominal``, ``dev-squad``).
    name:
        Human-readable name for display and discovery.
    description:
        Short summary of when to use this council.
    arbitrator_agent_id:
        The neutral agent that makes the final decision.
    member_agent_ids:
        Ordered tuple of council member agent IDs.
    max_analysis_tokens:
        Truncation limit (in tokens) for each member's analysis output.
    max_counter_tokens:
        Truncation limit (in tokens) for each member's counter-analysis output.
    require_consensus:
        If True, iterate analysis/counter cycles until consensus (V2 feature).
    """

    council_id: str
    name: str
    description: str = ""
    arbitrator_agent_id: str = ""
    member_agent_ids: tuple[str, ...] = field(default_factory=tuple)
    max_analysis_tokens: int = 2000
    max_counter_tokens: int = 1500
    require_consensus: bool = False

    def __post_init__(self) -> None:
        if not self.council_id:
            raise ValueError("council_id must be non-empty")
        if not self.name:
            raise ValueError("name must be non-empty")
        if not self.arbitrator_agent_id:
            raise ValueError("arbitrator_agent_id must be non-empty")
        if not self.member_agent_ids:
            raise ValueError("member_agent_ids must be non-empty")
        if self.max_analysis_tokens < 1:
            raise ValueError("max_analysis_tokens must be >= 1")
        if self.max_counter_tokens < 1:
            raise ValueError("max_counter_tokens must be >= 1")


@dataclass
class CouncilOutcome:
    """Result of a completed council deliberation, returned to the caller.

    Fields
    ------
    council_id:
        The council that produced this outcome.
    decision:
        The arbitrator's final decision text.
    member_analyses:
        Map of member_agent_id → analysis text (for audit trail).
    member_counters:
        Map of member_agent_id → counter-analysis text.
    confidence:
        The arbitrator's self-assessed confidence (0.0 — 1.0).
    dissent_notes:
        Any minority opinions or flags from the arbitrator.
    """

    council_id: str
    decision: str
    member_analyses: Dict[str, str] = field(default_factory=dict)
    member_counters: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    dissent_notes: Optional[str] = None
