"""
Phase 2.17.1 — Repair Learning Store
====================================

In-memory, deterministic store for repair outcome records and
counterfactual entries.

Tracks drift type, chosen action, outcome, cost, and recurrence
for every repair event. Provides queries for success rates and
consecutive failure counts — the building blocks for the policy
engine (2.17.2) and pattern recognition (2.17.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .repair_learning_types import RepairMemoryRecord, CounterfactualEntry


@dataclass
class RepairLearningStore:
    """In-memory, deterministic store for repair outcome learning.

    All methods are pure with respect to their inputs — no I/O,
    no LLM calls, no randomness. The internal state is the only
    source of truth.
    """

    _records: List[RepairMemoryRecord] = field(default_factory=list)
    _counterfactuals: List[CounterfactualEntry] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_outcome(self, record: RepairMemoryRecord) -> None:
        """Record a repair outcome.

        Appends the record to the internal list. No deduplication —
        each call to repair() records its outcomes separately.
        """
        self._records.append(record)

    def record_counterfactual(self, entry: CounterfactualEntry) -> None:
        """Record a counterfactual alternative.

        If an entry with the same drift_type, failed_action, and
        alternative_action already exists, its frequency is incremented
        instead of creating a duplicate.
        """
        for i, existing in enumerate(self._counterfactuals):
            if (
                existing.drift_type == entry.drift_type
                and existing.failed_action == entry.failed_action
                and existing.alternative_action == entry.alternative_action
            ):
                self._counterfactuals[i] = CounterfactualEntry(
                    drift_type=existing.drift_type,
                    failed_action=existing.failed_action,
                    alternative_action=existing.alternative_action,
                    alternative_details=existing.alternative_details,
                    frequency=existing.frequency + 1,
                )
                return
        self._counterfactuals.append(entry)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_records(self) -> Tuple[RepairMemoryRecord, ...]:
        """Return all recorded outcomes as an immutable tuple."""
        return tuple(self._records)

    def get_counterfactuals(self) -> Tuple[CounterfactualEntry, ...]:
        """Return all counterfactual entries as an immutable tuple."""
        return tuple(self._counterfactuals)

    def success_rate(self, drift_type: str, action_type: str) -> float:
        """Compute historical success rate for a (drift_type, action_type) pair.

        Returns 0.0 when no history exists for this combination.
        """
        relevant = [
            r
            for r in self._records
            if r.drift_type == drift_type and r.action_type == action_type
        ]
        if not relevant:
            return 0.0
        successes = sum(1 for r in relevant if r.outcome == "success")
        return successes / len(relevant)

    def consecutive_failures(self, drift_type: str, action_type: str) -> int:
        """Count consecutive failures (most recent first).

        Only counts failures from the most recent entries backward.
        Stops at the first success.
        """
        relevant = [
            r
            for r in reversed(self._records)
            if r.drift_type == drift_type and r.action_type == action_type
        ]
        count = 0
        for r in relevant:
            if r.outcome == "failure":
                count += 1
            else:
                break
        return count

    def recurrence_count(self, drift_type: str) -> int:
        """How many times this drift type has appeared in recorded outcomes."""
        return sum(1 for r in self._records if r.drift_type == drift_type)

    def clear(self) -> None:
        """Reset the store, removing all records and counterfactuals."""
        self._records.clear()
        self._counterfactuals.clear()
