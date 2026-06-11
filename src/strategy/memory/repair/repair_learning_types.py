"""
Phase 2.17.1 — Repair Learning Types
=====================================

Shared frozen dataclasses for the Repair Learning Layer.

All types are immutable and deterministic — no LLM, no I/O, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.strategy.types.validation import deadcode_ignore


@dataclass(frozen=True)
class RepairMemoryRecord:
    """A single repair outcome record for the learning store.

    Records what drift was detected, which action was chosen, whether it
    succeeded or failed, what it cost, and how often this combination has
    recurred.
    """

    drift_type: str
    """The error_type from BreakageError (e.g. MISSING_SEGMENT, BROKEN_PARENT_LINK)."""

    action_type: str
    """The action_type from RepairAction (e.g. REGENERATE_SEGMENT, RECONSTRUCT_CHAIN)."""

    outcome: str
    """Either 'success' or 'failure'."""

    cost: int
    """Budget units consumed by this action."""

    recurrence: int = 1
    """How many times this drift_type+action_type combo has been seen."""

    plan_id: str = ""
    """The plan_id that was being repaired."""

    subgoal_id: str = ""
    """The subgoal_id that was being repaired."""

    timestamp: str = ""
    """ISO 8601 UTC timestamp of when this record was created."""


@dataclass(frozen=True)
class CounterfactualEntry:
    """Alternative action recorded when a repair action fails.

    Counterfactuals are recorded only on failure. They track what
    alternative action could have been tried instead, enabling
    frequency-based scoring for future repairs.
    """

    drift_type: str
    """The error_type from BreakageError."""

    failed_action: str
    """The action_type that failed."""

    alternative_action: str
    """An alternative action_type that could have been tried."""

    alternative_details: str = ""
    """Description of what the alternative would have done differently."""

    frequency: int = 1
    """How many times this counterfactual has been suggested."""


@deadcode_ignore(reason="Action ranking policy used by repair learning layer")
@dataclass(frozen=True)
class RepairPolicy:
    """Deterministic policy configuration for action ranking.

    All thresholds are purely frequency-based — no LLM reasoning,
    no semantic analysis.
    """

    success_threshold: float = 0.8
    """Actions with ≥ this success rate are promoted to the front."""

    failure_threshold: int = 3
    """Actions with ≥ this many consecutive failures are demoted to the end."""

    max_actions_per_cycle: int = 10
    """Maximum number of actions to rank per repair cycle."""


@dataclass(frozen=True)
class PatternMatch:
    """A recognised pattern: drift_type → best_action.

    Detected through pure frequency-based pattern recognition.
    """

    drift_type: str
    """The error_type this pattern applies to."""

    best_action: str
    """The action_type with the highest success rate for this drift."""

    success_rate: float
    """Historical success rate [0.0, 1.0]."""

    sample_count: int
    """Number of historical records that informed this pattern."""

    promoted: bool = False
    """True when success_rate ≥ policy.success_threshold."""

    demoted: bool = False
    """True when consecutive failures ≥ policy.failure_threshold."""
