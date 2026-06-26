"""Dependency-aware scheduling — BLOCKED state resolution for Stratum-4.

Pure functions that handle:

- Finding the ``JoinHandle`` for a given ``plan_id``
- Transitioning BLOCKED→PENDING sibling jobs once their ``depends_on``
  dependencies are satisfied
- Updating ``JoinHandle`` state (child success / failure) and propagating
  failure to sibling jobs

These are called from a post-execution hook (``on_job_complete``) on the
S4 ``Worker``; they can also be used standalone by the Supervisor's
polling loop.
"""

from __future__ import annotations

from src.platform.queue.queue import Queue
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState, transition
from src.platform.runtime.job_store.job_store import JobStore
from src.platform.runtime.job_store.join_store import JoinStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_join_handle(
    plan_id: str,
    join_store: JoinStore,
) -> str | None:
    """Scan *join_store* for a handle matching ``plan_id``.

    Since the abstract ``JoinStore.list()`` interface returns only metadata
    dicts (not ``JoinHandle`` objects), we scan the store.  Production
    back-ends should add a ``plan_id`` index.
    """
    for entry in join_store.list():
        handle = join_store.get(entry["join_handle_id"])
        if handle is not None and handle.plan_id == plan_id:
            return handle.join_handle_id
    return None


def _all_deps_satisfied(
    job: Job,
    *,
    job_store: JobStore,
) -> bool:
    """Return ``True`` when every job in ``job.depends_on`` is SUCCEEDED."""
    for dep_id in job.depends_on:
        dep = job_store.get(dep_id)
        if dep is None or dep.state != JobState.SUCCEEDED:
            return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def handle_child_success(
    child_job_id: str,
    *,
    job_store: JobStore,
    join_store: JoinStore,
    queue: Queue,
) -> None:
    """Process a successful subtask completion.

    1. Finds the ``JoinHandle`` for this child's plan.
    2. Calls ``mark_child_completed()`` on the handle.
    3. Scans for BLOCKED sibling jobs whose ``depends_on`` is now
       satisfied and transitions them ``BLOCKED→PENDING``, pushing
       them onto *queue*.
    """
    child = job_store.get(child_job_id)
    if child is None or child.plan_id is None:
        return

    # 1. Locate the JoinHandle for this plan
    handle_id = _find_join_handle(child.plan_id, join_store)
    if handle_id is None:
        return

    # 2. Atomically record the completion (read→modify→save under lock)
    join_store.record_child_completed(handle_id, child_job_id)

    # 3. Unblock sibling BLOCKED jobs whose deps are now satisfied
    for meta in job_store.list():
        sibling = job_store.get(meta["job_id"])
        if sibling is None:
            continue
        if sibling.plan_id != child.plan_id:
            continue
        if sibling.state != JobState.BLOCKED:
            continue
        if not sibling.depends_on:
            # No deps means this shouldn't be BLOCKED — skip.
            continue

        if _all_deps_satisfied(sibling, job_store=job_store):
            sibling.state = transition(sibling.state, JobState.PENDING)
            job_store.save(sibling)
            queue.push(sibling)


def handle_child_failure(
    child_job_id: str,
    *,
    job_store: JobStore,
    join_store: JoinStore,
    queue: Queue,  # noqa: ARG001 — kept for API consistency
) -> None:
    """Process a failed subtask.

    1. Finds the ``JoinHandle`` for this child's plan.
    2. Calls ``record_child_failed()`` on the handle.
    3. Cancels all other subtask jobs in the same plan by transitioning
       them ``BLOCKED/PENDING→FAILED`` (no-op if already terminal).
    4. Records each cancelled sibling on the ``JoinHandle`` via
       ``record_child_failed()`` so the handle's completion count
       advances — workers skip already-failed jobs without calling
       ``on_job_complete``, so the handle would otherwise stall.
    """
    from src.platform.runtime.diagnostics import diag
    diag(f"handle_child_failure({child_job_id})")

    child = job_store.get(child_job_id)
    if child is None or child.plan_id is None:
        diag(f"  child=None or plan_id=None (child={'None' if child is None else child.job_id}, plan={child.plan_id if child else 'N/A'})")
        return

    diag(f"  child: state={child.state}, result_type={type(child.result).__name__}, result_keys={list(child.result.keys()) if child.result else None}")

    # 1. Locate the JoinHandle
    handle_id = _find_join_handle(child.plan_id, join_store)
    if handle_id is None:
        return

    # 2. Atomically record the failure (read→modify→save under lock)
    join_store.record_child_failed(handle_id, child_job_id)

    # Re-read handle for the sibling-cancellation step below (safe because
    # we need the child_job_ids list, which is stable after creation).
    handle = join_store.get(handle_id)
    if handle is None:
        return

    # 3. Cancel remaining siblings and record each on the join handle.
    #    Workers skip already-failed jobs without calling on_job_complete,
    #    so the join handle would never learn about these failures without
    #    us recording them here.
    #    RUNNING siblings are NOT pre-recorded — their own on_job_complete
    #    callback will update the handle when they finish.
    for sibling_id in handle.child_job_ids:
        if sibling_id == child_job_id:
            continue
        sibling = job_store.get(sibling_id)
        if sibling is None:
            continue
        if sibling.state in (JobState.BLOCKED, JobState.PENDING):
            sibling.state = transition(sibling.state, JobState.FAILED)
            job_store.save(sibling)
            # Record on the handle so its completion count advances.
            join_store.record_child_failed(handle_id, sibling_id)
