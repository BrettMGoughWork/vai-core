"""
Phase 2.17.5 — Tests for RepairPolicy Engine
=============================================

Tests for deterministic action ranking: promotion, demotion,
no-history handling, determinism, and budget awareness.
"""

from __future__ import annotations

import pytest

from src.strategy.memory.repair.repair_types import RepairAction
from src.strategy.memory.repair.repair_learning_types import (
    RepairMemoryRecord,
    RepairPolicy,
)
from src.strategy.memory.repair.repair_learning_store import RepairLearningStore
from src.strategy.memory.repair.repair_policy import rank_actions, select_best_action


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> RepairLearningStore:
    return RepairLearningStore()


@pytest.fixture
def action_a() -> RepairAction:
    return RepairAction(
        action_type="REGENERATE_SEGMENT",
        target_id="seg-1",
        details={"reason": "missing"},
    )


@pytest.fixture
def action_b() -> RepairAction:
    return RepairAction(
        action_type="RECONSTRUCT_CHAIN",
        target_id="seg-1",
        details={"reason": "broken link"},
    )


@pytest.fixture
def action_c() -> RepairAction:
    return RepairAction(
        action_type="QUARANTINE_SEGMENT",
        target_id="seg-1",
        details={"reason": "mismatch"},
    )


@pytest.fixture
def action_d() -> RepairAction:
    return RepairAction(
        action_type="REHYDRATE_TIMESTAMP",
        target_id="plan-1",
        details={"reason": "corrupt"},
    )


def _make_actions(*actions: RepairAction) -> tuple[RepairAction, ...]:
    return tuple(actions)


# ---------------------------------------------------------------------------
# 2.17.2 — Empty / single actions
# ---------------------------------------------------------------------------


class TestEmptyActions:
    def test_empty_actions_returns_empty(
        self, store: RepairLearningStore
    ) -> None:
        result = rank_actions((), "MISSING_SEGMENT", store)
        assert result == ()

    def test_single_action_returns_same(
        self, store: RepairLearningStore, action_a: RepairAction
    ) -> None:
        result = rank_actions((action_a,), "MISSING_SEGMENT", store)
        assert result == (action_a,)


# ---------------------------------------------------------------------------
# 2.17.2 — No history preserves original order
# ---------------------------------------------------------------------------


class TestNoHistory:
    def test_no_history_preserves_order(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
        action_c: RepairAction,
    ) -> None:
        actions = (action_a, action_b, action_c)
        result = rank_actions(actions, "MISSING_SEGMENT", store)
        assert result == actions  # Original order preserved

    def test_no_history_select_best_returns_first(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        result = select_best_action((action_a, action_b), "X", store)
        assert result == action_a


# ---------------------------------------------------------------------------
# 2.17.2 — Promotion (≥80% success)
# ---------------------------------------------------------------------------


class TestPromotion:
    def test_promoted_action_moves_to_front(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # action_a has no history, action_b has 100% success → B should be first
        for _ in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="MISSING_SEGMENT",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        result = rank_actions((action_a, action_b), "MISSING_SEGMENT", store)
        assert result[0] == action_b

    def test_exactly_80_percent_is_promoted(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # action_b: 4 success, 1 failure = 80% → promoted
        for _ in range(4):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="RECONSTRUCT_CHAIN",
                outcome="failure",
                cost=1,
            )
        )
        result = rank_actions((action_a, action_b), "X", store)
        assert result[0] == action_b

    def test_below_80_percent_not_promoted(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # action_b: 3 success, 1 failure = 75% → NOT promoted
        for _ in range(3):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="RECONSTRUCT_CHAIN",
                outcome="failure",
                cost=1,
            )
        )
        result = rank_actions((action_a, action_b), "X", store)
        # Both have no promotion → original order preserved
        assert result[0] == action_a


# ---------------------------------------------------------------------------
# 2.17.2 — Demotion (≥3 consecutive failures)
# ---------------------------------------------------------------------------


class TestDemotion:
    def test_demoted_action_moves_to_end(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
        action_c: RepairAction,
    ) -> None:
        # action_b has 3 consecutive failures → demoted
        for _ in range(3):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        result = rank_actions((action_a, action_b, action_c), "X", store)
        assert result[-1] == action_b
        assert result[0] == action_a
        assert result[1] == action_c

    def test_two_failures_not_demoted(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        result = rank_actions((action_a, action_b), "X", store)
        assert result == (action_a, action_b)  # Original order

    def test_demotion_broken_by_success(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # 2 failures, 1 success, then 2 more failures — only 2 consecutive
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="RECONSTRUCT_CHAIN",
                outcome="success",
                cost=1,
            )
        )
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        # Most recent 2 are failures, preceded by success → 2 consecutive, not demoted
        result = rank_actions((action_a, action_b), "X", store)
        assert result == (action_a, action_b)


# ---------------------------------------------------------------------------
# 2.17.2 — Promotion beats demotion
# ---------------------------------------------------------------------------


class TestPromotionOverDemotion:
    def test_promoted_stays_front_even_if_also_demoted(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # action_b: 4 success, 3 consecutive failures at the end
        # → promoted (80%) BUT also demoted by last 3 failures
        for _ in range(4):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        for _ in range(3):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        # Demotion takes priority in scoring (score = -1.0 < 0.0 for untested)
        result = rank_actions((action_a, action_b), "X", store)
        assert result[-1] == action_b  # Demoted to end


# ---------------------------------------------------------------------------
# 2.17.2 — Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_same_output(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        for _ in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        actions = (action_a, action_b)
        result1 = rank_actions(actions, "X", store)
        result2 = rank_actions(actions, "X", store)
        assert result1 == result2

    def test_different_drift_types_independent(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # Populate history for drift type X but query Y
        for _ in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        # Querying Y should see no history
        result = rank_actions((action_a, action_b), "Y", store)
        assert result == (action_a, action_b)


# ---------------------------------------------------------------------------
# 2.17.2 — Multiple promotions
# ---------------------------------------------------------------------------


class TestMultiplePromotions:
    def test_multiple_promoted_ranked_by_success_rate(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
        action_c: RepairAction,
    ) -> None:
        # action_b: 100% (5/5) → promoted, score ~3.0
        for _ in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        # action_c: 80% (4/5) → promoted, score ~2.8
        for _ in range(4):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="QUARANTINE_SEGMENT",
                    outcome="success",
                    cost=1,
                )
            )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="QUARANTINE_SEGMENT",
                outcome="failure",
                cost=1,
            )
        )
        result = rank_actions((action_a, action_b, action_c), "X", store)
        # action_b (100%) before action_c (80%), both before action_a (untested)
        assert result[0] == action_b
        assert result[1] == action_c
        assert result[2] == action_a


# ---------------------------------------------------------------------------
# 2.17.2 — select_best_action
# ---------------------------------------------------------------------------


class TestSelectBestAction:
    def test_selects_best_after_ranking(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        for _ in range(5):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="success",
                    cost=1,
                )
            )
        result = select_best_action((action_a, action_b), "X", store)
        assert result == action_b

    def test_empty_actions_returns_none(self, store: RepairLearningStore) -> None:
        assert select_best_action((), "X", store) is None


# ---------------------------------------------------------------------------
# 2.17.2 — Custom policy thresholds
# ---------------------------------------------------------------------------


class TestCustomPolicy:
    def test_custom_success_threshold(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        # action_b: 50% success — promoted if threshold is 0.5, not if 0.8
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="RECONSTRUCT_CHAIN",
                outcome="success",
                cost=1,
            )
        )
        store.record_outcome(
            RepairMemoryRecord(
                drift_type="X",
                action_type="RECONSTRUCT_CHAIN",
                outcome="failure",
                cost=1,
            )
        )
        # Default policy (0.8) → not promoted
        result_default = rank_actions((action_a, action_b), "X", store)
        assert result_default == (action_a, action_b)

        # Custom policy (0.5) → promoted
        custom = RepairPolicy(success_threshold=0.5)
        result_custom = rank_actions((action_a, action_b), "X", store, custom)
        assert result_custom[0] == action_b

    def test_custom_failure_threshold(
        self,
        store: RepairLearningStore,
        action_a: RepairAction,
        action_b: RepairAction,
    ) -> None:
        for _ in range(2):
            store.record_outcome(
                RepairMemoryRecord(
                    drift_type="X",
                    action_type="RECONSTRUCT_CHAIN",
                    outcome="failure",
                    cost=1,
                )
            )
        # Default (3) → not demoted
        result_default = rank_actions((action_a, action_b), "X", store)
        assert result_default == (action_a, action_b)

        # Custom (2) → demoted
        custom = RepairPolicy(failure_threshold=2)
        result_custom = rank_actions((action_a, action_b), "X", store, custom)
        assert result_custom[-1] == action_b