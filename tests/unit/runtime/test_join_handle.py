"""
Tests for JoinHandle + InMemoryJoinStore.
==========================================

Covers:
- JoinHandle state machine: WAITING → COMPLETED / FAILED
- mark_child_completed / mark_child_failed idempotency
- is_ready / all_succeeded
- InMemoryJoinStore CRUD
"""

from __future__ import annotations

from src.platform.runtime.join_handle import JoinHandle, JoinHandleState
from src.platform.runtime.job_store.backends.in_memory_join_store import (
    InMemoryJoinStore,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_handle(
    child_ids: list[str] | None = None,
    **overrides,
) -> JoinHandle:
    defaults = dict(
        parent_job_id="parent-1",
        plan_id="plan-1",
        child_job_ids=child_ids or ["c1", "c2", "c3"],
    )
    defaults.update(overrides)
    return JoinHandle(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# JoinHandle state machine
# ══════════════════════════════════════════════════════════════════════════════


class TestJoinHandleInitialState:
    def test_starts_waiting(self) -> None:
        h = _make_handle()
        assert h.state == JoinHandleState.WAITING
        assert h.completed_ids == []
        assert h.failed_ids == []
        assert h.completed_at is None

    def test_is_ready_false_initially(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        assert not h.is_ready()

    def test_all_succeeded_false_initially(self) -> None:
        h = _make_handle()
        assert not h.all_succeeded()


class TestJoinHandleMarkChildCompleted:
    def test_marks_child_completed(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_completed("a")
        assert h.completed_ids == ["a"]
        assert h.state == JoinHandleState.WAITING  # not all done yet

    def test_transitions_to_completed_when_all_done(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_completed("a")
        h.mark_child_completed("b")
        assert h.state == JoinHandleState.COMPLETED
        assert h.completed_ids == ["a", "b"]
        assert h.failed_ids == []
        assert h.completed_at is not None

    def test_idempotent_mark(self) -> None:
        h = _make_handle(child_ids=["a"])
        h.mark_child_completed("a")
        h.mark_child_completed("a")  # second call should be no-op
        assert h.completed_ids == ["a"]
        assert h.state == JoinHandleState.COMPLETED

    def test_is_ready_true_when_all_completed(self) -> None:
        h = _make_handle(child_ids=["a"])
        h.mark_child_completed("a")
        assert h.is_ready()

    def test_all_succeeded_true_when_all_completed(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_completed("a")
        h.mark_child_completed("b")
        assert h.all_succeeded()


class TestJoinHandleMarkChildFailed:
    def test_marks_child_failed(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_failed("a")
        assert h.failed_ids == ["a"]
        assert h.state == JoinHandleState.WAITING

    def test_transitions_to_failed_when_all_done_with_failures(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_completed("a")
        h.mark_child_failed("b")
        assert h.state == JoinHandleState.FAILED
        assert h.failed_ids == ["b"]
        assert h.completed_ids == ["a"]
        assert h.completed_at is not None

    def test_failed_any_child_means_all_succeeded_false(self) -> None:
        h = _make_handle(child_ids=["a"])
        h.mark_child_failed("a")
        assert h.is_ready()
        assert not h.all_succeeded()
        assert h.state == JoinHandleState.FAILED

    def test_idempotent_fail_mark(self) -> None:
        h = _make_handle(child_ids=["a"])
        h.mark_child_failed("a")
        h.mark_child_failed("a")
        assert h.failed_ids == ["a"]

    def test_partial_failure_then_completion_still_fails(self) -> None:
        """If any child failed, the handle should end in FAILED state."""
        h = _make_handle(child_ids=["a", "b", "c"])
        h.mark_child_failed("a")
        h.mark_child_completed("b")
        h.mark_child_completed("c")
        assert h.state == JoinHandleState.FAILED
        assert not h.all_succeeded()


class TestJoinHandleIsReady:
    def test_ready_when_all_children_accounted(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        assert not h.is_ready()
        h.mark_child_completed("a")
        assert not h.is_ready()
        h.mark_child_completed("b")
        assert h.is_ready()

    def test_ready_with_mixed_success_failure(self) -> None:
        h = _make_handle(child_ids=["a", "b"])
        h.mark_child_completed("a")
        h.mark_child_failed("b")
        assert h.is_ready()


# ══════════════════════════════════════════════════════════════════════════════
# InMemoryJoinStore CRUD
# ══════════════════════════════════════════════════════════════════════════════


class TestInMemoryJoinStore:
    def test_save_and_get(self) -> None:
        store = InMemoryJoinStore()
        h = _make_handle()
        store.save(h)
        retrieved = store.get(h.join_handle_id)
        assert retrieved is not None
        assert retrieved.join_handle_id == h.join_handle_id
        assert retrieved.plan_id == h.plan_id

    def test_get_missing_returns_none(self) -> None:
        store = InMemoryJoinStore()
        assert store.get("nonexistent") is None

    def test_list_empty(self) -> None:
        store = InMemoryJoinStore()
        assert store.list() == []

    def test_list_returns_all(self) -> None:
        store = InMemoryJoinStore()
        h1 = _make_handle(plan_id="p1")
        h2 = _make_handle(plan_id="p2")
        store.save(h1)
        store.save(h2)
        meta = store.list()
        assert len(meta) == 2
        ids = {m["join_handle_id"] for m in meta}
        assert ids == {h1.join_handle_id, h2.join_handle_id}

    def test_delete_removes(self) -> None:
        store = InMemoryJoinStore()
        h = _make_handle()
        store.save(h)
        store.delete(h.join_handle_id)
        assert store.get(h.join_handle_id) is None

    def test_delete_missing_is_noop(self) -> None:
        store = InMemoryJoinStore()
        store.delete("nonexistent")  # should not raise

    def test_len(self) -> None:
        store = InMemoryJoinStore()
        assert len(store) == 0
        store.save(_make_handle())
        assert len(store) == 1
        store.save(_make_handle())
        assert len(store) == 2

    def test_get_returns_deep_copy(self) -> None:
        """Caller should not be able to mutate the stored object."""
        store = InMemoryJoinStore()
        h = _make_handle(child_ids=["a"])
        store.save(h)

        retrieved = store.get(h.join_handle_id)
        assert retrieved is not None
        retrieved.mark_child_completed("a")

        # Re-fetch — should still be WAITING since the stored version
        # should be independent
        second = store.get(h.join_handle_id)
        assert second is not None
        assert second.state == JoinHandleState.WAITING

    def test_save_overwrite(self) -> None:
        store = InMemoryJoinStore()
        h = _make_handle(child_ids=["a"])
        store.save(h)
        h.mark_child_completed("a")
        store.save(h)
        retrieved = store.get(h.join_handle_id)
        assert retrieved is not None
        assert retrieved.state == JoinHandleState.COMPLETED
