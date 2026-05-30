from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# ---------------------------------------------------------------------------
# Full event-driven transition table for SubgoalLifecycleState
#
# Two parallel, independent lifecycles share this table:
#
#   Execution lifecycle:
#     CREATED → VALIDATED → READY → RUNNING → SUCCESS / FAILED / BLOCKED
#     BLOCKED → READY (recovery) | FAILED (unrecoverable)
#     FAILED  → RETRYING → RUNNING
#
#   High-level lifecycle:
#     PENDING → ACTIVE → SATISFIED / FAILED / ABANDONED
#
# The lifecycles are parallel views over the same enum; they do NOT bridge.
# Shared states (FAILED) carry consistent semantics across both views.
#
# Key: (from_state_value, event_value) → to_state_value
# All values are str (Enum.value) for JSON-serialisability.
# ---------------------------------------------------------------------------

SUBGOAL_EVENT_TRANSITIONS: Dict[Tuple[str, str], str] = {
    # ── Execution lifecycle ──────────────────────────────────────────────
    ("created",   "validate") : "validated",  # structural validation passed
    ("validated", "activate") : "ready",       # execution queue entry
    ("ready",     "start")    : "running",     # execution started
    ("running",   "succeed")  : "success",     # execution completed
    ("running",   "fail")     : "failed",      # execution failed
    ("running",   "block")    : "blocked",     # execution blocked (drift-triggered)
    ("blocked",   "unblock")  : "ready",       # block cleared → back to ready
    ("blocked",   "fail")     : "failed",      # block unrecoverable → failure
    ("failed",    "retry")    : "retrying",    # repair-triggered retry scheduled
    ("retrying",  "resume")   : "running",     # retry execution started
    ("retrying",  "fail")     : "failed",      # retry exhausted → permanent failure

    # ── High-level lifecycle ─────────────────────────────────────────────
    ("pending",   "activate") : "active",      # lifecycle activation
    ("active",    "succeed")  : "satisfied",   # goal achieved
    ("active",    "fail")     : "failed",      # goal failed
}


# ---------------------------------------------------------------------------
# Direct state transition table (no event trigger required)
#
# These transitions are governed by LifecycleTransitionEngine (2.3.x) and are
# expressed as state → {reachable states}.  They have no SubgoalEvent trigger.
#
# SATISFIED / FAILED / ABANDONED → CLOSED is achieved via direct transition only.
# ---------------------------------------------------------------------------

SUBGOAL_DIRECT_TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "pending":   frozenset({"active"}),
    "active":    frozenset({"satisfied", "failed", "abandoned"}),
    "satisfied": frozenset({"closed"}),
    "failed":    frozenset({"closed"}),
    "abandoned": frozenset({"closed"}),
    # Execution-lifecycle states have no direct (event-free) transitions
    "created":   frozenset(),
    "validated": frozenset(),
    "ready":     frozenset(),
    "running":   frozenset(),
    "success":   frozenset(),
    "blocked":   frozenset(),
    "retrying":  frozenset(),
    "closed":    frozenset(),
}


# ---------------------------------------------------------------------------
# Terminal-state sets
#
# EVENT_TERMINAL_STATES   — states with no outgoing event transitions.
#                           `list_allowed_transitions` returns {} for these.
#
# LIFECYCLE_TERMINAL_STATES — states with no outgoing transitions of any kind
#                             (event or direct).  Currently only CLOSED.
# ---------------------------------------------------------------------------

EVENT_TERMINAL_STATES: FrozenSet[str] = frozenset({
    "success",    # execution complete — no further events
    "satisfied",  # high-level satisfied — only direct → closed
    "abandoned",  # high-level abandoned — only direct → closed
    "closed",     # fully terminal
})

LIFECYCLE_TERMINAL_STATES: FrozenSet[str] = frozenset({
    "closed",
})


# ---------------------------------------------------------------------------
# Human-readable explanations  (deterministic, JSON-serialisable strings)
# ---------------------------------------------------------------------------

SUBGOAL_EVENT_EXPLANATIONS: Dict[Tuple[str, str], str] = {
    ("created",   "validate") : "Subgoal passed structural validation; enters execution queue",
    ("validated", "activate") : "Subgoal activated and ready for execution",
    ("ready",     "start")    : "Subgoal execution has started",
    ("running",   "succeed")  : "Subgoal execution completed successfully",
    ("running",   "fail")     : "Subgoal execution failed; eligible for retry",
    ("running",   "block")    : "Subgoal execution blocked (possibly drift-triggered)",
    ("blocked",   "unblock")  : "Blocking condition resolved; subgoal returns to ready",
    ("blocked",   "fail")     : "Blocking condition unrecoverable; subgoal failed",
    ("failed",    "retry")    : "Subgoal scheduled for retry via repair",
    ("retrying",  "resume")   : "Retry execution has started",
    ("retrying",  "fail")     : "Retry exhausted; subgoal permanently failed",
    ("pending",   "activate") : "Subgoal lifecycle activated from pending",
    ("active",    "succeed")  : "Subgoal goal satisfied; awaiting closure",
    ("active",    "fail")     : "Subgoal goal failed at high-level lifecycle",
}

SUBGOAL_DIRECT_EXPLANATIONS: Dict[Tuple[str, str], str] = {
    ("pending",   "active")    : "Direct lifecycle activation from pending",
    ("active",    "satisfied") : "Goal satisfied; closure pending",
    ("active",    "failed")    : "Goal failed at lifecycle level",
    ("active",    "abandoned") : "Goal abandoned by governance decision",
    ("satisfied", "closed")    : "Satisfied subgoal closed",
    ("failed",    "closed")    : "Failed subgoal closed after resolution",
    ("abandoned", "closed")    : "Abandoned subgoal closed",
}
