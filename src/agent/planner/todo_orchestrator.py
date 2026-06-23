"""TodoOrchestrator — S4 lifecycle manager for todo-list processing (Sprint 12a.4).

Wraps a ``TodoWorker`` inside an S4 ``Worker`` and exposes a simple
``run(db_path)`` API that creates a ``Job``, enqueues it, and runs the
full S4 pipeline (crash recovery, idempotency, multi-cycle execution).

This is a first-class capability — not a tool call target.  It replaces
the old ``planner_call`` workflow step with a direct programmatic API.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from src.agent.planner.todo_worker import TodoWorker
from src.agent.strategy_router import StrategyRouter
from src.agent.workflow.engine import WorkflowEngine
from src.gateway.normalization import ChannelMessage
from src.platform.queue.queue import Queue
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job import create_job
from src.platform.runtime.worker import WorkExecutor, Worker

logger = logging.getLogger(__name__)


class TodoOrchestrator:
    """Lifecycle manager that runs a todo list through the S4 execution pipeline.

    Creates an S4 ``Worker`` wrapping a ``TodoWorker``, then:

    1. Constructs a ``ChannelMessage`` with ``db_path`` in metadata.
    2. Creates a ``Job`` via ``create_job()``.
    3. Registers the job with the ``ControlPlane``.
    4. Pushes the job onto the ``Queue``.
    5. Calls ``Worker.process_next()`` — the S4 ``ExecutionStage`` multi-cycle
       loop iterates through all todos automatically.
    6. Returns the final result dict.

    Args:
        workflow_engine: ``WorkflowEngine`` for per-item ``todo-execute-item``
            workflow dispatch.
        strategy_router: ``StrategyRouter`` for dispatching ``llm_call`` outcomes.
        inline_tool_executor: Callable that synchronously executes tools
            (the ``_execute_tool_inline`` closure from ``composition_root``).
        queue: The ``Queue`` to use for job enqueue/dequeue.
        control_plane: The ``ControlPlane`` for job lifecycle management.
        tool_context: Optional list of OpenAI tool schemas for LLM calls.
        timeout_seconds: Maximum seconds per execution cycle (default 300).
        max_iterations_per_goal: Maximum iterations per sub-goal to prevent infinite
            loops (default 30).
    """

    def __init__(
        self,
        workflow_engine: WorkflowEngine,
        strategy_router: StrategyRouter,
        inline_tool_executor: Callable[[dict], Optional[dict]],
        *,
        queue: Queue,
        control_plane: ControlPlane,
        tool_context: Optional[list[dict]] = None,
        timeout_seconds: int = 300,
        max_iterations_per_goal: int = 30,
    ) -> None:
        self._control_plane = control_plane
        self._queue = queue

        _todo_worker = TodoWorker(
            workflow_engine=workflow_engine,
            strategy_router=strategy_router,
            inline_tool_executor=inline_tool_executor,
            tool_context=tool_context,
            max_iterations_per_goal=max_iterations_per_goal,
        )
        self._worker = Worker(
            executor=_todo_worker,
            queue=queue,
            control_plane=control_plane,
            timeout_seconds=timeout_seconds,
        )

    def run(self, db_path: str) -> dict:
        """Run the todo list at ``db_path`` through the full S4 pipeline.

        Returns:
            A dict with keys:
                - ``output``: Summary text of what was done.
                - ``done``: ``True`` (always, since the pipeline runs to completion).
                - ``cognitive_state``: Dict with ``db_path`` for resume support.
        """
        if not db_path:
            return {"done": True, "output": "No db_path provided — nothing to do."}

        channel_msg = ChannelMessage(
            input={},
            metadata={"db_path": db_path},
            channel="planner",
        )
        job = create_job(channel_msg)

        self._control_plane.register_job(job)
        self._queue.push(job)

        logger.info("TodoOrchestrator: enqueued job %s for db %s", job.job_id, db_path)

        updated_job = self._worker.process_next()
        if updated_job is None:
            return {
                "done": True,
                "output": f"No job processed — queue may be empty.",
            }

        if updated_job.result is not None:
            return updated_job.result

        state = updated_job.state.value if updated_job.state else "unknown"
        return {
            "done": True,
            "output": f"Job {updated_job.job_id} finished in state {state}, no result.",
        }
