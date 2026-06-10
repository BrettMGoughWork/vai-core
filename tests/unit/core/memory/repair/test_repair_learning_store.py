"""
Phase 2.17.5 — Tests for RepairLearningStore
=============================================

Tests for the in-memory repair learning store: CRUD, counterfactuals,
recurrence tracking, success rate computation, consecutive failure counting.
"""

from __future__ import annotations

import pytest

from src.core.memory.repair.repair_learning_types import (
    RepairMemoryRecord,
    CounterfactualEntry,
)
from src.core.memory.repair.repair_learning_store import RepairLearningStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> RepairLearningStore:
    return RepairLearningStore()


@pytest.fixture
def populated_store() -> RepairLearningStore:
    """A store with 5 records across 2 drift types."""
    s = RepairLearningStore()
    # MISSING_SEGMENT + REGENERATE_SEGMENT: 3 successes
    for _ in range(3):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="REGENERATE_SEGMENT",
                outcome="success",
                cost=1,
                plan_id="p-1",
                subgoal_id="sg-1",
            )
        )
    # MISSING_SEGMENT + RECONSTRUCT_CHAIN: 2 failures
    for _ in range(2):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="RECONSTRUCT_CHAIN",
                outcome="failure",
                cost=1,
                plan_id="p-1",
                subgoal_id="sg-1",
            )
        )
    return s


# ---------------------------------------------------------------------------
# 2.17.1 — Recording and retrieval
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    def test_empty_store_has_no_records(self, store: RepairLearningStore) -> None:
        assert store.get_records() == ()

    def test_record_single_outcome(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="REGENERATE_SEGMENT",
                outcome="success",
                cost=1,
            )
        )
        records = store.get_records()
        assert len(records) == 1
        assert records[0].drift_type == "MISSING_SEGMENT"
        assert records[0].outcome == "success"

    def test_record_multiple_outcomes(self, store: RepairLearningStore) -> None:
        for i in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="MISSING_SEGMENT",
                    action_type="REGENERATE_SEGMENT",
                    outcome="success" if i < 4 else "failure",
                    cost=1,
                )
            )
        assert len(store.get_records()) == 5

    def test_records_are_immutable_tuple(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="Y", outcome="success", cost=1
            )
        )
        records = store.get_records()
        assert isinstance(records, tuple)

    def test_records_preserve_order(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="A", action_type="X", outcome="success", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="B", action_type="Y", outcome="failure", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="A", action_type="Z", outcome="success", cost=1
            )
        )
        records = store.get_records()
        assert records[0].drift_type == "A"
        assert records[1].drift_type == "B"
        assert records[2].drift_type == "A"


# ---------------------------------------------------------------------------
# 2.17.1 — Success rate
# ---------------------------------------------------------------------------


class TestSuccessRate:
    def test_no_history_returns_zero(self, store: RepairLearningStore) -> None:
        assert store.success_rate("MISSING_SEGMENT", "REGENERATE_SEGMENT") == 0.0

    def test_all_successes_returns_one(self, populated_store: RepairLearningStore) -> None:
        assert populated_store.success_rate("MISSING_SEGMENT", "REGENERATE_SEGMENT") == 1.0

    def test_all_failures_returns_zero(self, populated_store: RepairLearningStore) -> None:
        assert populated_store.success_rate("MISSING_SEGMENT", "RECONSTRUCT_CHAIN") == 0.0

    def test_mixed_outcomes(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="success", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        assert store.success_rate("X", "A") == 0.5

    def test_only_matches_relevant_pair(self, populated_store: RepairLearningStore) -> None:
        # Other drift/action combos should not affect the rate
        assert populated_store.success_rate("BROKEN_PARENT_LINK", "REGENERATE_SEGMENT") == 0.0


# ---------------------------------------------------------------------------
# 2.17.1 — Consecutive failures
# ---------------------------------------------------------------------------


class TestConsecutiveFailures:
    def test_no_history_returns_zero(self, store: RepairLearningStore) -> None:
        assert store.consecutive_failures("X", "Y") == 0

    def test_all_success_returns_zero(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="success", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="success", cost=1
            )
        )
        assert store.consecutive_failures("X", "A") == 0

    def test_consecutive_failures_count(self, store: RepairLearningStore) -> None:
        for _ in range(3):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        assert store.consecutive_failures("X", "A") == 3

    def test_stops_at_success(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="success", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        # Most recent is the last failure, preceded by a success → only 1 consecutive
        assert store.consecutive_failures("X", "A") == 1

    def test_different_drift_types_isolated(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="Y", action_type="A", outcome="failure", cost=1
            )
        )
        assert store.consecutive_failures("X", "A") == 1
        assert store.consecutive_failures("Y", "A") == 1


# ---------------------------------------------------------------------------
# 2.17.1 — Recurrence count
# ---------------------------------------------------------------------------


class TestRecurrenceCount:
    def test_empty_store_returns_zero(self, store: RepairLearningStore) -> None:
        assert store.recurrence_count("MISSING_SEGMENT") == 0

    def test_counts_all_occurrences(self, populated_store: RepairLearningStore) -> None:
        # 3 REGENERATE + 2 RECONSTRUCT = 5 for MISSING_SEGMENT
        assert populated_store.recurrence_count("MISSING_SEGMENT") == 5

    def test_different_drift_types(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="A", action_type="X", outcome="success", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="A", action_type="Y", outcome="failure", cost=1
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="B", action_type="X", outcome="success", cost=1
            )
        )
        assert store.recurrence_count("A") == 2
        assert store.recurrence_count("B") == 1


# ---------------------------------------------------------------------------
# 2.17.1 — Clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_removes_all_records(self, populated_store: RepairLearningStore) -> None:
        assert len(populated_store.get_records()) == 5
        populated_store.clear()
        assert len(populated_store.get_records()) == 0
        assert len(populated_store.get_counterfactuals()) == 0


# ---------------------------------------------------------------------------
# 2.17.1 / 2.17.3 — Counterfactuals
# ---------------------------------------------------------------------------


class TestCounterfactuals:
    def test_empty_store_has_no_counterfactuals(self, store: RepairLearningStore) -> None:
        assert store.get_counterfactuals() == ()

    def test_record_single_counterfactual(self, store: RepairLearningStore) -> None:
        store.record_counterfactual(
            CounterfactualEntry(
                drift_type="MISSING_SEGMENT",
                failed_action="REGENERATE_SEGMENT",
                alternative_action="RECONSTRUCT_CHAIN",
                alternative_details="Sever link instead",
            )
        )
        cfs = store.get_counterfactuals()
        assert len(cfs) == 1
        assert cfs[0].frequency == 1

    def test_duplicate_counterfactual_increments_frequency(
        self, store: RepairLearningStore
    ) -> None:
        entry = CounterfactualEntry(
            drift_type="MISSING_SEGMENT",
            failed_action="REGENERATE_SEGMENT",
            alternative_action="RECONSTRUCT_CHAIN",
        )
        store.record_counterfactual(entry)
        store.record_counterfactual(entry)
        store.record_counterfactual(entry)
        cfs = store.get_counterfactuals()
        assert len(cfs) == 1
        assert cfs[0].frequency == 3

    def test_different_alternatives_are_separate(
        self, store: RepairLearningStore
    ) -> None:
        store.record_counterfactual(
            CounterfactualEntry(
                drift_type="MISSING_SEGMENT",
                failed_action="REGENERATE_SEGMENT",
                alternative_action="RECONSTRUCT_CHAIN",
            )
        )
        store.record_counterfactual(
            CounterfactualEntry(
                drift_type="MISSING_SEGMENT",
                failed_action="REGENERATE_SEGMENT",
                alternative_action="QUARANTINE_SEGMENT",
            )
        )
        assert len(store.get_counterfactuals()) == 2


# ---------------------------------------------------------------------------
# 2.17.1 — Record metadata fields
# ---------------------------------------------------------------------------


class TestRecordMetadata:
    def test_record_stores_plan_and_subgoal_ids(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="REGENERATE_SEGMENT",
                outcome="success",
                cost=3,
                plan_id="plan-42",
                subgoal_id="sg-7",
                timestamp="2024-06-01T00:00:00Z",
            )
        )
        r = store.get_records()[0]
        assert r.plan_id == "plan-42"
        assert r.subgoal_id == "sg-7"
        assert r.timestamp == "2024-06-01T00:00:00Z"
        assert r.cost == 3

    def test_default_recurrence_is_one(self, store: RepairLearningStore) -> None:
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="Y", outcome="success", cost=1
            )
        )
        assert store.get_records()[0].recurrence == 1
