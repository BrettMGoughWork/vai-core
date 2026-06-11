from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, Any, Optional
import time

from src.strategy.types.hashing import stable_hash
from src.strategy.types.json_pure import ensure_json_pure


class SubgoalLifecycleState(str, Enum):
    """
    Lifecycle states for subgoals.
    These states are governed by TransitionEngine and mutated only by SubgoalManager.

    High-level lifecycle: PENDING → ACTIVE → SATISFIED / FAILED / ABANDONED → CLOSED
    Execution lifecycle:  CREATED → VALIDATED → READY → RUNNING → SUCCESS / FAILED / BLOCKED
                          BLOCKED → READY; FAILED → RETRYING → RUNNING
    """

    # High-level lifecycle states
    PENDING = "pending"
    ACTIVE = "active"
    SATISFIED = "satisfied"
    ABANDONED = "abandoned"
    CLOSED = "closed"

    # Execution lifecycle states (2.3.7)
    CREATED = "created"
    VALIDATED = "validated"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    RETRYING = "retrying"


@dataclass(frozen=True)
class Subgoal:
    """
    Immutable structural representation of a subgoal.

    This is a Stratum‑2 model:
    - JSON‑pure
    - deterministic
    - hash‑stable
    - no behavior, no planner semantics
    """

    subgoal_id: str
    goal: str
    context: Dict[str, Any]
    metadata: Dict[str, Any]
    parent_id: Optional[str] = None
    state: SubgoalLifecycleState = SubgoalLifecycleState.PENDING
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    canonical_hash: str = field(init=False)

    # ------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------
    @staticmethod
    def new(
        goal: str,
        context: Dict[str, Any],
        metadata: Dict[str, Any],
        parent_id: Optional[str] = None,
    ) -> Subgoal:
        """
        Factory constructor used by SubgoalManager.
        Generates a deterministic subgoal_id and enforces JSON purity.
        """
        ensure_json_pure(context)
        ensure_json_pure(metadata)

        subgoal_id = stable_hash(
            {
                "goal": goal,
                "context": context,
                "metadata": metadata,
                "parent_id": parent_id,
                "ts": int(time.time() * 1000),
            }
        )

        return Subgoal(
            subgoal_id=subgoal_id,
            goal=goal,
            context=context,
            metadata=metadata,
            parent_id=parent_id,
        )

    # ------------------------------------------------------------
    # Post-init canonical hash
    # ------------------------------------------------------------
    def __post_init__(self):
        ensure_json_pure(self.context)
        ensure_json_pure(self.metadata)

        object.__setattr__(
            self,
            "canonical_hash",
            stable_hash(
                {
                    "subgoal_id": self.subgoal_id,
                    "goal": self.goal,
                    "context": self.context,
                    "metadata": self.metadata,
                    "parent_id": self.parent_id,
                    "state": self.state.value,
                }
            ),
        )

    # ------------------------------------------------------------
    # State mutation (immutable)
    # ------------------------------------------------------------
    def with_state(self, new_state: SubgoalLifecycleState) -> Subgoal:
        """
        Returns a new Subgoal instance with updated lifecycle state.
        Canonical hash is recomputed automatically.
        """
        return replace(self, state=new_state)

    @property
    def id(self) -> str:
        return self.subgoal_id