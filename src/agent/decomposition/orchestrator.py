"""
Decomposition Orchestrator — Agent Task Decomposition
=======================================================

Central orchestrator for the fan-out/fan-in lifecycle.  Owns the
decomposition flow from validated plan → enqueue → join handle →
merge.

Responsibilities (Sections 5–8 of ROADMAP-agent-decomposition.md):
  - ``fan_out()``:       Enqueue one ``Job`` per subtask, create
                         ``JoinHandle``, enqueue ``ContinuationJob``.
  - ``fan_in()``:        Collect child results, execute merge strategy,
                         return ``MergeResult``.
  - ``cancel()``:        Cancel all subtask jobs for a given plan.
  - ``parallelize()``:   Synchronously run N items in parallel via
                         fan-out/fan-in and return merged + per-agent results.
"""

from __future__ import annotations

import time as _time
import uuid
from collections.abc import Callable
from typing import Any

from src.agent.decomposition.dag_validator import validate_dag
from src.agent.decomposition.merge import execute_merge
from src.agent.types.decomposition import (
    DecompositionPlan,
    FanOutResult,
    MergeResult,
    SubtaskSpec,
)
from src.platform.runtime.join_handle import JoinHandle, JoinHandleState
from src.platform.runtime.job_store.join_store import JoinStore


class DecompositionOrchestrator:
    """Orchestrates decomposition fan-out and fan-in.

    Does **not** depend on the scheduler or queue API directly —
    those are injected via callbacks to keep this class testable.
    """

    def __init__(
        self,
        join_store: JoinStore,
        *,
        enqueue_fn: Any | None = None,
        enqueue_continuation_fn: Any | None = None,
    ) -> None:
        """
        Args:
            join_store:  Persistent store for ``JoinHandle`` objects.
            enqueue_fn:  Callable ``(job_dict: dict) -> str`` returning job_id.
                         Injected to avoid direct queue dependency.
            enqueue_continuation_fn:  Callable for the continuation job.
        """
        self._join_store = join_store
        self._enqueue_fn = enqueue_fn
        self._enqueue_continuation_fn = enqueue_continuation_fn

    # ── Fan-out ──────────────────────────────────────────────────────────

    def fan_out(
        self,
        plan: DecompositionPlan,
        parent_job_id: str,
    ) -> FanOutResult:
        """Fan out a validated ``DecompositionPlan`` into jobs.

        Args:
            plan:           Validated decomposition plan.
            parent_job_id:  The parent job that spawned the decomposition.

        Returns:
            A ``FanOutResult`` with child job ids, join handle id, and
            continuation job id.

        Raises:
            DagValidationError: If the plan's DAG is invalid.
        """
        validate_dag(plan.subtasks)

        # 1. Enqueue one job per subtask
        child_job_ids = self._enqueue_subtasks(plan, parent_job_id)

        # 2. Create JoinHandle
        handle = JoinHandle(
            parent_job_id=parent_job_id,
            plan_id=plan.plan_id,
            child_job_ids=child_job_ids,
            merge_strategy=plan.merge_strategy,
            merge_agent_id=plan.merge_agent_id,
        )
        self._join_store.save(handle)

        # 3. Enqueue ContinuationJob (depends on all child jobs)
        continuation_job_id = self._enqueue_continuation(
            plan=plan,
            parent_job_id=parent_job_id,
            join_handle_id=handle.join_handle_id,
            child_job_ids=child_job_ids,
        )

        return FanOutResult(
            child_job_ids=child_job_ids,
            join_handle_id=handle.join_handle_id,
            continuation_job_id=continuation_job_id,
        )

    # ── Fan-in ────────────────────────────────────────────────────────────

    def fan_in(
        self,
        join_handle_id: str,
        child_results: dict[str, dict[str, Any]],
        parent_context: dict[str, Any] | None = None,
    ) -> MergeResult:
        """Execute fan-in merge for a completed join handle.

        Args:
            join_handle_id:  The handle tracking the fan-out.
            child_results:   Map of ``subtask_id → job_result_dict``.
            parent_context:  Optional parent agent context for merge.

        Returns:
            A ``MergeResult`` with the merged output.
        """
        handle = self._join_store.get(join_handle_id)
        if handle is None:
            raise ValueError(f"JoinHandle not found: {join_handle_id}")

        if handle.state == JoinHandleState.WAITING:
            raise ValueError(
                f"Cannot fan-in on JoinHandle {join_handle_id}: "
                f"children not yet complete (state={handle.state.value})"
            )

        parent_task = ""
        if parent_context and "task" in parent_context:
            parent_task = parent_context["task"]

        merged = execute_merge(
            strategy=handle.merge_strategy,
            child_results=child_results,
            parent_task=parent_task,
        )

        # Mark handle DONE
        handle.state = JoinHandleState.COMPLETED
        self._join_store.save(handle)

        return merged

    # ── Cancel ────────────────────────────────────────────────────────────

    def cancel(self, plan_id: str) -> list[str]:
        """Cancel all subtask jobs for a given plan.

        Returns the list of cancelled child job IDs.
        """
        # Walk join store to find handles matching this plan
        cancelled: list[str] = []
        for entry in self._join_store.list():
            handle = self._join_store.get(entry["join_handle_id"])
            if handle is None or handle.plan_id != plan_id:
                continue
            if handle.state == JoinHandleState.WAITING:
                handle.state = JoinHandleState.FAILED
                self._join_store.save(handle)
            cancelled.extend(handle.child_job_ids)
        return cancelled

    # ── Parallelize ────────────────────────────────────────────────────────

    def parallelize(
        self,
        parent_job_id: str,
        items: list[tuple[str, str]],
        *,
        job_store_get: Callable[[str], Any],
        parent_task: str = "",
        merge_strategy: str = "concat",
        merge_agent_id: str | None = None,
        merge_prompt_template: str | None = None,
        poll_interval_seconds: float = 0.1,
        poll_timeout_seconds: float = 120.0,
    ) -> tuple[MergeResult, dict[str, dict[str, Any]]]:
        """Execute N items in parallel via fan-out/fan-in.

        Each item becomes a fully parallel subtask (no dependencies).  The
        worker pool is driven independently — this method only polls the
        join store until all children complete or the timeout expires.

        Args:
            parent_job_id:    Unique ID for this parallel batch.
            items:            List of ``(agent_id, description)`` tuples.
            job_store_get:    Callable ``(job_id) -> Job | None`` to retrieve
                              completed job results.
            parent_task:      Description of the parent task (merge context).
            merge_strategy:   Merge strategy (default ``"concat"``).
            merge_agent_id:   Optional agent for custom merge strategy.
            merge_prompt_template:  Optional prompt template for LLM merge.
            poll_interval_seconds:  Seconds between poll checks (default 0.1).
            poll_timeout_seconds:   Max wall-clock seconds (default 120).

        Returns:
            Tuple of ``(merged, agent_results)`` where *merged* is the
            ``MergeResult`` from fan-in, and *agent_results* maps
            ``agent_id -> job_result_dict``.

        Raises:
            RuntimeError: If the JoinHandle enters FAILED or disappears.
            TimeoutError: If poll timeout is reached before completion.
        """
        # 1. Build subtasks — all fully parallel (depends_on=[])
        subtasks: list[SubtaskSpec] = []
        for agent_id, description in items:
            subtasks.append(
                SubtaskSpec(
                    id=str(uuid.uuid4()),
                    description=description,
                    target_agent_id=agent_id,
                    depends_on=[],
                )
            )

        # 2. Create plan
        plan = DecompositionPlan(
            plan_id=str(uuid.uuid4()),
            parent_task=parent_task,
            subtasks=subtasks,
            merge_strategy=merge_strategy,
            merge_agent_id=merge_agent_id,
            merge_prompt_template=merge_prompt_template,
        )

        # 3. Fan-out
        fan_out_result = self.fan_out(plan, parent_job_id)

        # 4. Poll loop — wait for pool workers to drain children
        deadline = _time.monotonic() + poll_timeout_seconds
        while _time.monotonic() < deadline:
            handle = self._join_store.get(fan_out_result.join_handle_id)
            if handle is None:
                raise RuntimeError(
                    f"JoinHandle {fan_out_result.join_handle_id} "
                    f"disappeared during parallelize"
                )
            if handle.state == JoinHandleState.COMPLETED:
                break
            if handle.state == JoinHandleState.FAILED:
                    from src.platform.runtime.diagnostics import diag as _diag
                    _diag(f"PARALLELIZE FAILED: handle_id={fan_out_result.join_handle_id}, "
                          f"failed_ids={list(handle.failed_ids or [])}, "
                          f"completed_ids={len(handle.completed_ids or [])}, "
                          f"total={len(handle.child_job_ids)}, "
                          f"orphan={[cid for cid in handle.child_job_ids if cid not in (handle.completed_ids or []) and cid not in (handle.failed_ids or [])]}")
                    # Collect error info from each failed child for debugging
                    child_errors: list[str] = []
                    for cid in (handle.failed_ids or []):
                        job = job_store_get(cid)
                        if job is not None:
                            _diag(f"  failed child {cid}: state={job.state}, "
                                  f"result_type={type(job.result).__name__}, "
                                  f"result_keys={list(job.result.keys()) if job.result else None}")
                            child_errors.append(
                                f"  {cid}: {job.result.get('error_type', '?')}: "
                                f"{job.result.get('message', '?')}"
                            )
                    detail = (
                        "\n".join(child_errors) if child_errors
                        else "  (no child error metadata)"
                    )
                    raise RuntimeError(
                        f"JoinHandle {fan_out_result.join_handle_id} "
                        f"entered FAILED state during parallelize\n"
                        f"Child job errors:\n{detail}"
                    )
            _time.sleep(poll_interval_seconds)
        else:
            # Timeout reached
            self.cancel(plan.plan_id)
            raise TimeoutError(
                f"parallelize() timed out after {poll_timeout_seconds}s "
                f"for plan {plan.plan_id}"
            )

        # 5. Collect child results from JobStore — keyed by agent_id
        agent_results: dict[str, dict[str, Any]] = {}
        child_results: dict[str, dict[str, Any]] = {}
        for (agent_id, _), subtask_id, job_id in zip(
            items,
            (s.id for s in plan.subtasks),
            fan_out_result.child_job_ids,
        ):
            child_job = job_store_get(job_id)
            if child_job is not None and child_job.result is not None:
                child_results[subtask_id] = child_job.result
                agent_results[agent_id] = child_job.result

        # 6. Fan-in (merge)
        merged = self.fan_in(
            join_handle_id=fan_out_result.join_handle_id,
            child_results=child_results,
            parent_context={"task": parent_task},
        )

        return merged, agent_results

    # ── Internal helpers ──────────────────────────────────────────────────

    def _enqueue_subtasks(
        self,
        plan: DecompositionPlan,
        parent_job_id: str,
    ) -> list[str]:
        """Enqueue one job per subtask (Section 5.3)."""
        if self._enqueue_fn is None:
            # Pure in-memory: generate synthetic IDs for testing
            return [str(uuid.uuid4()) for _ in plan.subtasks]

        child_job_ids: list[str] = []
        for subtask in plan.subtasks:
            job = {
                "job_id": str(uuid.uuid4()),
                "job_type": "subtask",
                "parent_job_id": parent_job_id,
                "plan_id": plan.plan_id,
                "subtask_id": subtask.id,
                "subtask_description": subtask.description,
                "target_agent_id": subtask.target_agent_id,
                "target_skill_id": subtask.target_skill_id,
                "arguments": subtask.arguments,
                "depends_on": subtask.depends_on,
                "priority": subtask.priority,
                "max_retries": subtask.max_retries,
                "timeout_seconds": subtask.timeout_seconds,
            }
            job_id = self._enqueue_fn(job)
            child_job_ids.append(job_id)
        return child_job_ids

    def _enqueue_continuation(
        self,
        plan: DecompositionPlan,
        parent_job_id: str,
        join_handle_id: str,
        child_job_ids: list[str] | None = None,
    ) -> str:
        """Enqueue the continuation job (Section 8.1).

        The continuation job is automatically BLOCKED until all child
        jobs succeed — ``child_job_ids`` are set as ``depends_on`` so
        the BLOCKED dispatch filter in ``_make_decomp_enqueue_fn()``
        holds it back until ``handle_child_success()`` unblocks it.
        """
        if self._enqueue_continuation_fn is None:
            return str(uuid.uuid4())

        continuation = {
            "job_id": str(uuid.uuid4()),
            "job_type": "continuation",
            "parent_job_id": parent_job_id,
            "plan_id": plan.plan_id,
            "join_handle_id": join_handle_id,
            "merge_strategy": plan.merge_strategy,
            "merge_agent_id": plan.merge_agent_id,
            "merge_prompt_template": plan.merge_prompt_template,
            "depends_on": child_job_ids or [],
        }
        return self._enqueue_continuation_fn(continuation)


