"""
S5.5 — Agent State & Lifecycle Types
=====================================

Defines the lifecycle model, state container, and event log for the
Agent Runtime Supervisor (S5.5).

All types compose existing S5 types — they do **not** redefine schemas.

- ``LifecycleState`` — deterministic lifecycle enumeration
- ``LifecycleEvent`` — auditable event log entry
- ``AgentState`` — immutable, versioned, serialisable runtime state
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.agent.activation import ActivatedAgentContext
from src.agent.contracts import ActionIntent, AgentResponse
from src.agent.job_interface import JobDispatchResult

if TYPE_CHECKING:
    from src.agent.cognitive_loop import CognitiveLoopResult

# ---------------------------------------------------------------------------
# LifecycleState
# ---------------------------------------------------------------------------


class LifecycleState(str, Enum):
    """Deterministic lifecycle states for an agent instance.

    Transitions
    -----------
    CREATED -> ACTIVATED -> RUNNING <-> WAITING
                                     |          |
                                     +-> COMPLETED (terminal)
                                     +-> FAILED   (terminal)
                                     +-> SUSPENDED -> RUNNING (via resume)
    """

    CREATED = "created"
    ACTIVATED = "activated"
    RUNNING = "running"
    WAITING = "waiting"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        """True if this state is terminal (no further transitions)."""
        return self in (LifecycleState.COMPLETED, LifecycleState.FAILED)

    def is_active(self) -> bool:
        """True if this state represents an active, progressing agent."""
        return self in (
            LifecycleState.RUNNING,
            LifecycleState.WAITING,
        )


# ---------------------------------------------------------------------------
# LifecycleEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LifecycleEvent:
    """An auditable event in the agent's lifecycle history.

    Fields
    ------
    timestamp:
        ISO-8601 timestamp of the event.
    from_state:
        Previous lifecycle state (None for the initial CREATED event).
    to_state:
        New lifecycle state after the transition.
    reason:
        Human-readable reason for the transition.
    details:
        Optional structured details (e.g. timeout_ms, error message).
    """

    timestamp: str
    from_state: Optional[LifecycleState]
    to_state: LifecycleState
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            raise ValueError("timestamp must be non-empty")
        if not self.reason:
            raise ValueError("reason must be non-empty")
        if not isinstance(self.details, dict):
            raise ValueError("details must be a dict")


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentState:
    """Immutable, versioned runtime state for an agent instance.

    Composes existing S5 types — never redefines schemas.

    Fields
    ------
    agent_id:
        The agent's unique identifier (must be registered in the registry).
    lifecycle_state:
        Current lifecycle state (see ``LifecycleState``).
    activation_snapshot:
        Snapshot of the activated agent context from S5.2.
    cognitive_result:
        Most recent cognitive loop result from S5.3 (None before first run).
    pending_intents:
        Action intents awaiting dispatch (None if none pending).
    dispatch_result:
        Most recent job dispatch result from S5.4 (None before first dispatch).
    final_response:
        Final AgentResponse when the agent has completed (None otherwise).
    errors:
        Accumulated errors across lifecycle steps.
    timestamps:
        ISO-8601 timestamps for key lifecycle milestones.
    correlation_id:
        Correlation ID for tracing.
    trace_id:
        Trace ID for distributed tracing.
    version:
        Monotonic version number (incremented on each mutation).  Enables
        optimistic concurrency and copy-on-write semantics.
    supervisor_metadata:
        Supervisor-specific metadata (e.g. timeout configuration, retry
        count, iteration limit).  Opaque to the rest of S5.
    lifecycle_history:
        Ordered list of lifecycle events for audit/debug.
    """

    agent_id: str
    lifecycle_state: LifecycleState = LifecycleState.CREATED

    # Composed S5 types
    activation_snapshot: Optional[ActivatedAgentContext] = None
    cognitive_result: Optional[Any] = None        # CognitiveLoopResult
    pending_intents: Optional[List[ActionIntent]] = None
    dispatch_result: Optional[JobDispatchResult] = None
    final_response: Optional[AgentResponse] = None

    # Metadata
    errors: List[Dict[str, Any]] = field(default_factory=list)
    timestamps: Dict[str, str] = field(default_factory=dict)
    correlation_id: str = ""
    trace_id: str = ""
    version: int = 1
    supervisor_metadata: Dict[str, Any] = field(default_factory=dict)

    # Audit
    lifecycle_history: List[LifecycleEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("agent_id must be non-empty")
        if not isinstance(self.lifecycle_state, LifecycleState):
            raise ValueError(
                f"lifecycle_state must be a LifecycleState, "
                f"got {type(self.lifecycle_state).__name__}"
            )
        if self.version < 1:
            raise ValueError(f"version must be >= 1, got {self.version}")
        if isinstance(self.errors, list):
            for err in self.errors:
                if not isinstance(err, dict):
                    raise ValueError("each error must be a dict")

    # ── Convenience factories ──────────────────────────────────────────

    def with_(self, **changes: Any) -> AgentState:
        """Return a new ``AgentState`` with the given fields replaced.

        This is the primary mutation mechanism.  It increments the version
        number and preserves immutability (copy-on-write).
        """
        d = {**changes}
        now = _now()

        # Append a lifecycle event if lifecycle_state changed
        new_state = d.get("lifecycle_state", self.lifecycle_state)
        if new_state != self.lifecycle_state:
            history = list(self.lifecycle_history)
            history.append(LifecycleEvent(
                timestamp=now,
                from_state=self.lifecycle_state,
                to_state=new_state,
                reason=d.pop("_reason", "state transition"),
                details=d.pop("_details", {}),
            ))
            d["lifecycle_history"] = history

        # Update timestamps
        timestamps = dict(self.timestamps)
        if self.lifecycle_state == LifecycleState.CREATED and new_state == LifecycleState.ACTIVATED:
            timestamps["activated_at"] = now
        if new_state == LifecycleState.RUNNING:
            timestamps.setdefault("first_run_at", now)
            timestamps["last_run_at"] = now
        if new_state == LifecycleState.COMPLETED:
            timestamps["completed_at"] = now
        if new_state == LifecycleState.FAILED:
            timestamps["failed_at"] = now
        if new_state == LifecycleState.SUSPENDED:
            timestamps["suspended_at"] = now
        d["timestamps"] = timestamps

        d["version"] = self.version + 1
        return dataclasses.replace(self, **d)

    # ── Introspection ──────────────────────────────────────────────────

    def has_response(self) -> bool:
        """True if the agent has produced a final ``AgentResponse``."""
        return self.final_response is not None

    def is_terminal(self) -> bool:
        """True if the agent is in a terminal lifecycle state."""
        return self.lifecycle_state.is_terminal()

    def is_active(self) -> bool:
        """True if the agent is actively progressing."""
        return self.lifecycle_state.is_active()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# The import of dataclasses is deferred to avoid shadowing the module-level
# "dataclass" name used in annotations.
import dataclasses
