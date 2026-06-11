"""
Phase 2.17.5 — Tests for Pattern Recognition
=============================================

Tests for deterministic pattern detection: promotion threshold (≥80%),
demotion threshold (≥3 consecutive failures), pattern stability, and
best-action lookup.
"""

from __future__ import annotations

import pytest

from src.strategy.memory.repair.repair_learning_types import (
    RepairMemoryRecord,
    RepairPolicy,
)
from src.strategy.memory.repair.repair_learning_store import RepairLearningStore
from src.strategy.memory.repair.repair_patterns import (
    detect_patterns,
    get_best_action_for_drift,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> RepairLearningStore:
    return RepairLearningStore()


@pytest.fixture
def store_with_patterns() -> RepairLearningStore:
    """Store with clear patterns:
    - MISSING_SEGMENT + REGENERATE_SEGMENT: 8 success, 2 failure = 80% → promoted
    - MISSING_SEGMENT + RECONSTRUCT_CHAIN: 1 success, 4 failure = 20%
    - BROKEN_PARENT_LINK + RECONSTRUCT_CHAIN: 5 success, 0 failure = 100% → promoted
    - BROKEN_PARENT_LINK + QUARANTINE_SEGMENT: 0 success, 3 failure = 0% → demoted
    """
    s = RepairLearningStore()
    # MISSING_SEGMENT + REGENERATE_SEGMENT: 80%
    for _ in range(8):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="REGENERATE_SEGMENT",
                outcome="success",
                cost=1,
            )
        )
    for _ in range(2):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="REGENERATE_SEGMENT",
                outcome="failure",
                cost=1,
            )
        )
    # MISSING_SEGMENT + RECONSTRUCT_CHAIN: 20%
    s.record_outcome(
        RepairMemoryRecord(
            drift_type="MISSING_SEGMENT",
            action_type="RECONSTRUCT_CHAIN",
            outcome="success",
            cost=1,
        )
    )
    for _ in range(4):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="MISSING_SEGMENT",
                action_type="RECONSTRUCT_CHAIN",
                outcome="failure",
                cost=1,
            )
        )
    # BROKEN_PARENT_LINK + RECONSTRUCT_CHAIN: 100%
    for _ in range(5):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="BROKEN_PARENT_LINK",
                action_type="RECONSTRUCT_CHAIN",
                outcome="success",
                cost=1,
            )
        )
    # BROKEN_PARENT_LINK + QUARANTINE_SEGMENT: 0%, 3 consecutive failures
    for _ in range(3):
        s.record_outcome(
            RepairMemoryRecord(
                drift_type="BROKEN_PARENT_LINK",
                action_type="QUARANTINE_SEGMENT",
                outcome="failure",
                cost=1,
            )
        )
    return s


# ---------------------------------------------------------------------------
# 2.17.4 — Empty store
# ---------------------------------------------------------------------------


class TestEmptyStore:
    def test_empty_store_returns_empty(self, store: RepairLearningStore) -> None:
        assert detect_patterns(store) == ()

    def test_empty_store_best_action_returns_none(
        self, store: RepairLearningStore
    ) -> None:
        assert get_best_action_for_drift("MISSING_SEGMENT", store) is None


# ---------------------------------------------------------------------------
# 2.17.4 — Pattern detection
# ---------------------------------------------------------------------------


class TestDetectPatterns:
    def test_detects_all_combinations(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        # 4 unique (drift_type, action_type) combos
        assert len(patterns) == 4

    def test_promoted_patterns_flagged(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        promoted = [p for p in patterns if p.promoted]
        # BROKEN_PARENT_LINK + RECONSTRUCT_CHAIN (100%)
        # MISSING_SEGMENT + REGENERATE_SEGMENT (80%)
        assert len(promoted) == 2

    def test_demoted_patterns_flagged(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        demoted = [p for p in patterns if p.demoted]
        # Two combos have ≥3 consecutive trailing failures:
        #   MISSING_SEGMENT + RECONSTRUCT_CHAIN (1 success then 4 failures)
        #   BROKEN_PARENT_LINK + QUARANTINE_SEGMENT (3 failures)
        assert len(demoted) == 2
        demoted_keys = {(d.drift_type, d.best_action) for d in demoted}
        assert ("MISSING_SEGMENT", "RECONSTRUCT_CHAIN") in demoted_keys
        assert ("BROKEN_PARENT_LINK", "QUARANTINE_SEGMENT") in demoted_keys

    def test_success_rate_computation(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        by_key = {(p.drift_type, p.best_action): p for p in patterns}

        regen = by_key[("MISSING_SEGMENT", "REGENERATE_SEGMENT")]
        assert regen.success_rate == pytest.approx(0.8)
        assert regen.sample_count == 10

        recon = by_key[("MISSING_SEGMENT", "RECONSTRUCT_CHAIN")]
        assert recon.success_rate == pytest.approx(0.2)
        assert recon.sample_count == 5


# ---------------------------------------------------------------------------
# 2.17.4 — Sorting
# ---------------------------------------------------------------------------


class TestPatternSorting:
    def test_promoted_sort_before_non_promoted(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        # First two should be promoted
        assert patterns[0].promoted
        assert patterns[1].promoted
        # Remaining should be non-promoted
        assert not patterns[2].promoted
        assert not patterns[3].promoted

    def test_promoted_sorted_by_success_rate(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        patterns = detect_patterns(store_with_patterns)
        promoted = [p for p in patterns if p.promoted]
        # 100% before 80%
        assert promoted[0].success_rate > promoted[1].success_rate


# ---------------------------------------------------------------------------
# 2.17.4 — Best action lookup
# ---------------------------------------------------------------------------


class TestGetBestActionForDrift:
    def test_returns_promoted_not_demoted(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        # MISSING_SEGMENT: REGENERATE is promoted, RECONSTRUCT_CHAIN is not
        best = get_best_action_for_drift("MISSING_SEGMENT", store_with_patterns)
        assert best == "REGENERATE_SEGMENT"

    def test_returns_promoted_for_clear_winner(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        # BROKEN_PARENT_LINK: RECONSTRUCT_CHAIN is promoted and not demoted
        best = get_best_action_for_drift("BROKEN_PARENT_LINK", store_with_patterns)
        assert best == "RECONSTRUCT_CHAIN"

    def test_returns_none_for_unknown_drift(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        assert get_best_action_for_drift("UNKNOWN_DRIFT", store_with_patterns) is None


# ---------------------------------------------------------------------------
# 2.17.4 — Pattern promotion at exactly 80%
# ---------------------------------------------------------------------------


class TestPromotionBoundary:
    def test_exactly_80_percent_is_promoted(self, store: RepairLearningStore) -> None:
        for _ in range(4):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="A",
                    outcome="success",
                    cost=1,
                )
            )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X", action_type="A", outcome="failure", cost=1
            )
        )
        patterns = detect_patterns(store)
        assert len(patterns) == 1
        assert patterns[0].promoted

    def test_79_percent_not_promoted(self, store: RepairLearningStore) -> None:
        for _ in range(79):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="A",
                    outcome="success",
                    cost=1,
                )
            )
        for _ in range(21):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        # 79/100 = 79% → not promoted
        patterns = detect_patterns(store)
        assert len(patterns) == 1
        assert not patterns[0].promoted


# ---------------------------------------------------------------------------
# 2.17.4 — Pattern demotion boundary
# ---------------------------------------------------------------------------


class TestDemotionBoundary:
    def test_three_consecutive_failures_demoted(self, store: RepairLearningStore) -> None:
        for _ in range(3):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        patterns = detect_patterns(store)
        assert patterns[0].demoted

    def test_two_consecutive_failures_not_demoted(
        self, store: RepairLearningStore
    ) -> None:
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        patterns = detect_patterns(store)
        assert not patterns[0].demoted


# ---------------------------------------------------------------------------
# 2.17.4 — Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_data_same_patterns(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        p1 = detect_patterns(store_with_patterns)
        p2 = detect_patterns(store_with_patterns)
        assert p1 == p2

    def test_same_data_same_best_action(
        self, store_with_patterns: RepairLearningStore
    ) -> None:
        a1 = get_best_action_for_drift("MISSING_SEGMENT", store_with_patterns)
        a2 = get_best_action_for_drift("MISSING_SEGMENT", store_with_patterns)
        assert a1 == a2


# ---------------------------------------------------------------------------
# 2.17.4 — Custom policy
# ---------------------------------------------------------------------------


class TestCustomPolicy:
    def test_custom_threshold_changes_promotion(self, store: RepairLearningStore) -> None:
        # 60% success → not promoted with default (0.8), promoted with custom (0.5)
        for _ in range(6):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="success", cost=1
                )
            )
        for _ in range(4):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        # Default: 60% → not promoted
        patterns_default = detect_patterns(store)
        assert not patterns_default[0].promoted

        # Custom: 60% ≥ 50% → promoted
        custom = RepairPolicy(success_threshold=0.5)
        patterns_custom = detect_patterns(store, custom)
        assert patterns_custom[0].promoted

    def test_custom_threshold_changes_demotion(self, store: RepairLearningStore) -> None:
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X", action_type="A", outcome="failure", cost=1
                )
            )
        # Default (3) → not demoted
        assert not detect_patterns(store)[0].demoted

        # Custom (2) → demoted
        custom = RepairPolicy(failure_threshold=2)
        assert detect_patterns(store, custom)[0].demoted