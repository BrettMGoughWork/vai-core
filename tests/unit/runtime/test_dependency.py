"""
Tests for dependency-aware dispatch (handle_child_success / handle_child_failure).
==================================================================================

Uses real InMemoryJobStore, InMemoryJoinStore, and InMemoryQueue for
integration-style testing of the pure dependency functions.
"""

from __future__ import annotations

from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
from src.platform.runtime.job_store.backends.in_memory_join_store import (
    InMemoryJoinStore,
)
from src.platform.runtime.job_store.job_store import InMemoryJobStore
from src.platform.runtime.join_handle import JoinHandle
from src.platform.runtime.scheduling.dependency import (
    handle_child_failure,
    handle_child_success,
)
from src.gateway.normalization import ChannelMessage


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _job(
    job_id: str,
    plan_id: str | None = "plan-1",
    state: JobState = JobState.SUCCEEDED,
    depends_on: list[str] | None = None,
) -> Job:
    return Job(
        job_id=job_id,
        plan_id=plan_id,
        state=state,
        depends_on=depends_on or [],
        payload=ChannelMessage(input={"text": f"job {job_id}"}),
    )


def _setup(
    child_ids: list[str],
    plan_id: str = "plan-1",
    parent_job_id: str = "parent-1",
) -> tuple[InMemoryJobStore, InMemoryJoinStore, InMemoryQueue, str]:
    """Create a store with a JoinHandle, parent, and child jobs.

    Returns (job_store, join_store, queue, handle_id).
    """
    job_store = InMemoryJobStore()
    join_store = InMemoryJoinStore()
    queue = InMemoryQueue()

    handle = JoinHandle(
        parent_job_id=parent_job_id,
        plan_id=plan_id,
        child_job_ids=list(child_ids),
    )
    handle_id = handle.join_handle_id
    join_store.save(handle)

    for cid in child_ids:
        job_store.save(_job(job_id=cid, plan_id=plan_id))

    return job_store, join_store, queue, handle_id


# ══════════════════════════════════════════════════════════════════════════════
# handle_child_success
# ══════════════════════════════════════════════════════════════════════════════


class TestHandleChildSuccess:
    def test_marks_child_completed_on_join_handle(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        handle = join_store.get(handle_id)
        assert handle is not None
        assert "a" in handle.completed_ids

    def test_unblocks_blocked_siblings(self) -> None:
        """A succeeds → B (BLOCKED, depends on A) → unblocked to PENDING."""
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        # B depends on A
        b = _job("b", state=JobState.BLOCKED, depends_on=["a"], plan_id="plan-1")
        job_store.save(b)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        assert b_reloaded is not None
        assert b_reloaded.state == JobState.PENDING

    def test_pushes_unblocked_job_to_queue(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        b = _job("b", state=JobState.BLOCKED, depends_on=["a"], plan_id="plan-1")
        job_store.save(b)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        assert len(queue) > 0
        popped = queue.pop()
        assert popped is not None
        assert popped.job_id == "b"

    def test_does_not_unblock_jobs_with_unmet_deps(self) -> None:
        """A succeeds, C depends on A AND B (still pending) → remains BLOCKED."""
        job_store, join_store, queue, handle_id = _setup(["a", "b", "c"])
        # B is still pending (hasn't completed yet)
        b = _job("b", state=JobState.PENDING, depends_on=[], plan_id="plan-1")
        job_store.save(b)
        # C depends on both A and B
        c = _job("c", state=JobState.BLOCKED, depends_on=["a", "b"], plan_id="plan-1")
        job_store.save(c)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        c_reloaded = job_store.get("c")
        assert c_reloaded is not None
        assert c_reloaded.state == JobState.BLOCKED

    def test_noop_when_child_not_found(self) -> None:
        job_store, join_store, queue, _ = _setup(["a"])
        handle_child_success(
            "nonexistent", job_store=job_store, join_store=join_store, queue=queue
        )
        # Should not raise

    def test_noop_when_child_has_no_plan_id(self) -> None:
        job_store, join_store, queue, _ = _setup(["a"])
        no_plan = _job("orphan", plan_id=None)
        job_store.save(no_plan)
        handle_child_success(
            "orphan", job_store=job_store, join_store=join_store, queue=queue
        )
        # Should not raise

    def test_skips_non_blocked_siblings(self) -> None:
        """Only BLOCKED siblings should be unblocked, not RUNNING or FAILED ones."""
        job_store, join_store, queue, handle_id = _setup(["a", "b", "c"])
        b = _job("b", state=JobState.RUNNING, depends_on=["a"], plan_id="plan-1")
        c = _job("c", state=JobState.FAILED, depends_on=["a"], plan_id="plan-1")
        job_store.save(b)
        job_store.save(c)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        c_reloaded = job_store.get("c")
        assert b_reloaded is not None and b_reloaded.state == JobState.RUNNING
        assert c_reloaded is not None and c_reloaded.state == JobState.FAILED

    def test_marks_join_handle_completed_when_all_children_done(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a"])
        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        handle = join_store.get(handle_id)
        assert handle is not None
        assert handle.state.value == "completed"

    def test_blocked_job_with_no_depends_on_not_unblocked(self) -> None:
        """BLOCKED job with empty depends_on should not be unblocked (shouldn't happen)."""
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        b = _job("b", state=JobState.BLOCKED, depends_on=[], plan_id="plan-1")
        job_store.save(b)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        assert b_reloaded is not None
        assert b_reloaded.state == JobState.BLOCKED  # unchanged

    def test_sibling_in_different_plan_not_affected(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"], plan_id="plan-1")
        other = _job("c", state=JobState.BLOCKED, depends_on=["x"], plan_id="plan-2")
        job_store.save(other)

        handle_child_success("a", job_store=job_store, join_store=join_store, queue=queue)

        other_reloaded = job_store.get("c")
        assert other_reloaded is not None
        assert other_reloaded.state == JobState.BLOCKED  # unchanged


# ══════════════════════════════════════════════════════════════════════════════
# handle_child_failure
# ══════════════════════════════════════════════════════════════════════════════


class TestHandleChildFailure:
    def test_marks_child_failed_on_join_handle(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        handle = join_store.get(handle_id)
        assert handle is not None
        assert "a" in handle.failed_ids

    def test_cancels_pending_siblings(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        b = _job("b", state=JobState.PENDING, plan_id="plan-1")
        job_store.save(b)

        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        assert b_reloaded is not None
        assert b_reloaded.state == JobState.FAILED

    def test_cancels_blocked_siblings(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a", "b"])
        b = _job("b", state=JobState.BLOCKED, plan_id="plan-1")
        job_store.save(b)

        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        assert b_reloaded is not None
        assert b_reloaded.state == JobState.FAILED

    def test_does_not_cancel_other_plan_jobs(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a"], plan_id="plan-1")
        other = _job("b", state=JobState.PENDING, plan_id="plan-2")
        job_store.save(other)

        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        other_reloaded = job_store.get("b")
        assert other_reloaded is not None
        assert other_reloaded.state == JobState.PENDING  # unchanged

    def test_does_not_affect_already_terminal_siblings(self) -> None:
        """Already SUCCEEDED/FAILED siblings should be left alone."""
        job_store, join_store, queue, handle_id = _setup(["a", "b", "c"])
        b = _job("b", state=JobState.SUCCEEDED, plan_id="plan-1")
        c = _job("c", state=JobState.FAILED, plan_id="plan-1")
        job_store.save(b)
        job_store.save(c)

        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        b_reloaded = job_store.get("b")
        c_reloaded = job_store.get("c")
        assert b_reloaded is not None and b_reloaded.state == JobState.SUCCEEDED
        assert c_reloaded is not None and c_reloaded.state == JobState.FAILED

    def test_noop_when_child_not_found(self) -> None:
        job_store, join_store, queue, _ = _setup(["a"])
        handle_child_failure(
            "nonexistent", job_store=job_store, join_store=join_store, queue=queue
        )
        # Should not raise

    def test_noop_when_child_has_no_plan_id(self) -> None:
        job_store, join_store, queue, _ = _setup(["a"])
        orphan = _job("orphan", plan_id=None)
        job_store.save(orphan)
        handle_child_failure(
            "orphan", job_store=job_store, join_store=join_store, queue=queue
        )
        # Should not raise

    def test_marks_join_handle_failed_when_all_children_done(self) -> None:
        job_store, join_store, queue, handle_id = _setup(["a"])
        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        handle = join_store.get(handle_id)
        assert handle is not None
        assert handle.state.value == "failed"

    def test_records_cancelled_siblings_on_handle(self) -> None:
        """When a child fails, remaining siblings are recorded on the join
        handle so it advances to FAILED even though workers will skip the
        cancelled jobs (without calling on_job_complete)."""
        job_store, join_store, queue, handle_id = _setup(["a", "b", "c"])
        b = _job("b", state=JobState.PENDING, plan_id="plan-1")
        job_store.save(b)
        c = _job("c", state=JobState.BLOCKED, plan_id="plan-1")
        job_store.save(c)

        handle_child_failure("a", job_store=job_store, join_store=join_store, queue=queue)

        handle = join_store.get(handle_id)
        assert handle is not None
        # All 3 children accounted for (one original failure + 2 cancelled)
        assert "a" in handle.failed_ids
        assert "b" in handle.failed_ids
        assert "c" in handle.failed_ids
        assert handle.state.value == "failed"
