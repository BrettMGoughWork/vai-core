"""TodoWorker — S4-compatible WorkExecutor for processing todo lists (Sprint 12a.3 / 12b.9).

Each ``__call__`` invocation processes ONE todo item from the list.  For
``type='task'`` items this is a single workflow run (as in Sprint 12a).
For ``type='goal'`` items the worker enters an *inner ReAct loop*:
reflect → plan next task → execute → assess → repeat until the
completion criterion is met (or ``max_iterations_per_goal`` is hit).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Callable, Dict, Optional

from src.agent.strategy_router import RouterOutcome, StrategyRouter
from src.agent.workflow.engine import (
    StepOutcome,
    WorkflowEngine,
    WorkflowExecutionState,
)
from src.capabilities.planner.todo_store import TodoStore
from src.domain._markers import deadcode_ignore

logger = logging.getLogger(__name__)

# Per-item workflow ID — registered in the workflow registry.
_TODO_EXECUTE_ITEM_WORKFLOW = "todo-execute-item"
# Inner ReAct loop workflow for sub-goals.
_SUBGOAL_EXECUTE_LOOP_WORKFLOW = "subgoal-execute-loop"

# Default maximum iterations per sub-goal (guardrail against infinite loops).
_DEFAULT_MAX_ITERATIONS_PER_GOAL = 30

# ── Context-template rendering ────────────────────────────────────────────

_CONTEXT_RE = re.compile(r"\{context\.(\w+)\}")
_RESULT_RE = re.compile(r"\{result\.(\w+)\}")


def _render_context_templates(
    config: Dict[str, Any],
    context: Dict[str, Any],
    step_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace ``{context.X}`` and ``{result.X}`` placeholders in config values."""
    rendered: Dict[str, Any] = {}
    for key, raw_value in config.items():
        if not isinstance(raw_value, str):
            rendered[key] = raw_value
            continue
        s = raw_value
        s = _CONTEXT_RE.sub(
            lambda m: str(context.get(m.group(1), "")), s,
        )
        s = _RESULT_RE.sub(
            lambda m: str(step_results.get(m.group(1), "")), s,
        )
        rendered[key] = s
    return rendered


# ── TodoWorker ────────────────────────────────────────────────────────────


class TodoWorker:
    """Processes todo-list items one at a time via the ``todo-execute-item`` workflow.

    Implements the ``WorkExecutor`` signature so it can be passed to
    ``Worker(executor=todo_worker, ...)``.

    Each ``__call__`` cycles through:

    1. Open the SQLite DB identified by ``db_path`` (from ``cognitive_state`` or
       ``payload.metadata.db_path``).
    2. Call ``TodoStore.get_next_pending()`` to select the next ready item.
    3. Run the ``todo-execute-item`` workflow for that single item.
    4. Update the todo status (done / failed with retry) and return.

    The S4 ExecutionStage's loop calls the executor repeatedly until
    ``done=True``, checkpointing between each cycle for crash recovery.

    Args:
        workflow_engine: WorkflowEngine used to start & step through the
            per-item ``todo-execute-item`` workflow.
        strategy_router: StrategyRouter for dispatching ``llm_call`` outcomes.
        inline_tool_executor: Callable that synchronously executes tools
            (the ``_execute_tool_inline`` closure from ``composition_root``).
        tool_context: Optional list of OpenAI tool schemas to expose to
            LLM calls. Defaults to empty list.
    """

    def __init__(
        self,
        workflow_engine: WorkflowEngine,
        strategy_router: StrategyRouter,
        inline_tool_executor: Callable[[dict], Optional[dict]],
        *,
        tool_context: Optional[list[dict]] = None,
        max_iterations_per_goal: int = _DEFAULT_MAX_ITERATIONS_PER_GOAL,
    ) -> None:
        self._engine = workflow_engine
        self._strategy_router = strategy_router
        self._inline_tool = inline_tool_executor
        self._tool_context = tool_context or []
        self._max_iterations_per_goal = max_iterations_per_goal

    @deadcode_ignore
    def __call__(
        self,
        payload: dict,
        execution_context: Any = None,
        resume_token: Any = None,
        **kwargs: Any,
    ) -> dict:
        """Process ONE todo item.

        For ``type='task'`` items: runs ``todo-execute-item`` once and
        returns.  For ``type='goal'`` items: enters the inner ReAct
        loop that dynamically decomposes and executes tasks until the
        completion criterion is met.

        Returns:
            ``{"done": True, "output": str}`` when all items are processed.
            ``{"done": False, ...}`` when more work remains. The
            ``cognitive_state`` dict persists ``db_path`` across cycles.
        """
        # Normalize payload — S4 ExecutionStage passes job.payload (ChannelMessage),
        # but direct callers (e.g. tests) may pass a plain dict.
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump()

        # 1. Determine db_path from cognitive_state (resume) or payload (fresh).
        cognitive_state: dict = {}
        if execution_context is not None:
            if isinstance(execution_context, dict):
                cognitive_state = execution_context.get("cognitive_state", {})
            elif hasattr(execution_context, "cognitive_state"):
                cognitive_state = execution_context.cognitive_state or {}

        db_path = cognitive_state.get("db_path")
        if db_path is None:
            metadata = payload.get("metadata", {})
            db_path = metadata.get("db_path")
            if db_path is None:
                db_path = payload.get("input", {}).get("db_path")
        if db_path is None:
            return {
                "done": True,
                "output": "No db_path in payload or cognitive_state — nothing to do.",
            }

        # 2. Open DB, ensure tables, and select the next pending item.
        item = None
        result_text = ""
        has_more = False
        conn = None
        store = None

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            store = TodoStore(conn)
            store.ensure_tables()
            item = store.get_next_pending()

            if item is None:
                total = store.total_count()
                done = store.done_count()
                failed = total - done
                result_text = (
                    f"Todo list complete.  {done}/{total} done, {failed} failed."
                )
            elif item.type == "goal":
                # Sub-goal: enter the inner ReAct loop.
                store.mark_in_progress(item.id)
                result_text = self._run_goal_inner_loop(item, store)
            else:
                # Task: single-shot execution (Sprint 12a behavior).
                store.mark_in_progress(item.id)
                result_text = self._run_item_workflow(item, store, conn)
                store.mark_done(item.id)

            has_more = store.has_work_remaining()

        except _StepFailedError as e:
            has_retries = store.mark_failed(item.id if item else "", str(e)) if store else False
            result_text = f"FAILED: {e}"
            if has_retries:
                logger.info("Todo %s failed — retries remain, re-queued.", item.id if item else "?")
            else:
                logger.warning("Todo %s failed — retries exhausted.", item.id if item else "?")
            has_more = store.has_work_remaining() if store else False

        except Exception as e:
            if store is not None and item is not None:
                has_retries = store.mark_failed(item.id, str(e))
                result_text = f"FAILED (unexpected): {e}"
                if not has_retries:
                    logger.warning(
                        "Todo %s failed with unexpected error, retries exhausted.", item.id,
                    )
            else:
                result_text = f"ERROR: {e}"
            has_more = store.has_work_remaining() if store else False

        finally:
            if conn is not None:
                conn.close()

        # 4. Build response.
        label = f"[{item.id}] {item.title}" if item else "(no item)"
        output = f"{label}: {result_text}" if result_text else label

        return {
            "done": not has_more,
            "output": output,
            "cognitive_state": {"db_path": db_path},
        }

    # ── goal inner loop ───────────────────────────────────────────────────

    def _run_goal_inner_loop(
        self,
        goal: Any,
        store: TodoStore,
    ) -> str:
        """Inner ReAct loop for a sub-goal.

        Iterates up to ``max_iterations_per_goal`` times.  Each iteration:
        1. Runs ``subgoal-execute-loop`` workflow (anchor → adviser →
           create_task → execute_task → assess).
        2. Parses the adviser's output for ``COMPLETE: YES/NO``.
        3. Appends the task outcome to the goal's description (progress
           compaction).
        4. If COMPLETE → mark goal done and return.
        5. If max iterations reached → mark goal failed and return.

        Returns a human-readable summary string.
        """
        db_path = store._conn.execute(
            "PRAGMA database_list"
        ).fetchone()["file"]

        # Build the initial progress log from the goal's description.
        progress_parts: list[str] = [f"Goal: {goal.title}\n"]

        for iteration in range(1, self._max_iterations_per_goal + 1):
            logger.info(
                "Goal '%s' — inner loop iteration %d/%d",
                goal.id, iteration, self._max_iterations_per_goal,
            )

            # Run one iteration of the subgoal-execute-loop workflow.
            progress_text = "\n".join(progress_parts)
            iter_context = {
                "goal_id": goal.id,
                "goal_title": goal.title,
                "goal_description": goal.description,
                "completion_criterion": goal.completion_criterion or "",
                "progress_log": progress_text,
                "state_context": "",
                "db_path": db_path,
            }

            try:
                iter_result, adviser_output = self._run_subgoal_iteration(
                    iter_context, store,
                )
            except _StepFailedError:
                # A step within the iteration failed — let the outer handler
                # decide retry.  Return the failure so the goal gets retried.
                raise

            # Append progress.
            if iter_result:
                progress_parts.append(iter_result)
                store.append_progress(goal.id, iter_result)

            # Parse the adviser output for the COMPLETE signal.
            is_complete = self._parse_complete_signal(adviser_output)

            if is_complete:
                logger.info(
                    "Goal '%s' — adviser reports COMPLETE after %d iteration(s).",
                    goal.id, iteration,
                )
                store.mark_done(goal.id)
                return (
                    f"Goal completed in {iteration} iteration(s). "
                    f"Last adviser: {adviser_output[:200]}"
                )

        # Max iterations exhausted.
        reason = (
            f"Max iterations ({self._max_iterations_per_goal}) reached "
            f"for goal '{goal.id}'.  Last iteration output: "
            f"{progress_parts[-1] if len(progress_parts) > 1 else 'none'}"
        )
        logger.warning("Goal '%s' — %s", goal.id, reason)
        store.mark_failed(goal.id, reason)
        raise _StepFailedError(reason)

    def _run_subgoal_iteration(
        self,
        context: dict,
        store: TodoStore,
    ) -> tuple[str | None, str]:
        """Run one iteration of ``subgoal-execute-loop``.

        Returns:
            ``(progress_summary, adviser_output)`` where
            ``progress_summary`` is the one-line task outcome from the
            assess step (or None if the iteration failed early) and
            ``adviser_output`` is the raw output from the adviser step
            (used for COMPLETE parsing).
        """
        wf_state = self._engine.start_workflow(
            _SUBGOAL_EXECUTE_LOOP_WORKFLOW,
            context=context,
        )

        adviser_output = ""
        progress_summary: str | None = None

        while True:
            wf_state, outcome = self._engine.step(wf_state)

            if outcome.type == "completed":
                # Collect outputs from key steps.
                adviser_output = str(
                    wf_state.step_results.get("anchor_and_reflect", "")
                )
                progress_summary = str(
                    wf_state.step_results.get("assess_task_outcome", "")
                )
                return progress_summary, adviser_output

            if outcome.type == "failed":
                error = outcome.error or wf_state.error or "Unknown workflow failure"
                raise _StepFailedError(error)

            if outcome.type == "continue":
                continue

            if outcome.type == "llm_call":
                wf_state = self._dispatch_llm_call(wf_state, outcome)
                # Capture adviser output when the anchor_and_reflect step completes.
                if outcome.step_id == "anchor_and_reflect":
                    adviser_output = str(
                        wf_state.step_results.get("anchor_and_reflect", "")
                    )
                continue

            if outcome.type == "tool_execute":
                wf_state = self._dispatch_tool_execute(wf_state, outcome)
                continue

            if outcome.type == "sub_workflow":
                wf_state = self._dispatch_sub_workflow(wf_state, outcome)
                continue

            if outcome.type == "waiting_for_input":
                raise _StepFailedError(
                    f"Workflow step '{outcome.step_id}' requested user_input — "
                    f"not supported in subgoal-execute-loop."
                )

    # ── per-item workflow dispatch ──────────────────────────────────────

    def _run_item_workflow(
        self,
        item: Any,
        store: TodoStore,
        conn: sqlite3.Connection,
    ) -> str:
        """Run the ``todo-execute-item`` workflow for a single task.

        Starts the workflow with ``item`` in the initial context, then
        dispatches ``llm_call`` and ``tool_execute`` outcomes until the
        workflow completes or fails.  Includes parent-goal context if
        this task belongs to a sub-goal.
        """
        context: dict = {
            "todo_id": item.id,
            "todo_title": item.title,
            "todo_description": item.description,
            "deps": item.depends_on,
            "db_path": conn.execute("PRAGMA database_list").fetchone()["file"],
        }

        # If this task has a parent goal, enrich the context.
        if item.parent_goal_id:
            parent = store.get(item.parent_goal_id)
            if parent is not None:
                context["parent_goal_id"] = parent.id
                context["parent_goal_title"] = parent.title
                context["parent_goal_criterion"] = parent.completion_criterion or ""
                context["progress_log"] = parent.description

        wf_state = self._engine.start_workflow(
            _TODO_EXECUTE_ITEM_WORKFLOW,
            context=context,
        )

        return self._run_workflow_to_completion(wf_state)

    def _run_workflow_to_completion(
        self,
        wf_state: WorkflowExecutionState,
    ) -> str:
        """Run a workflow to completion, dispatching all outcome types.

        Used for ``todo-execute-item`` and child workflows started by
        ``sub_workflow`` steps.  Returns the final result text.
        """
        while True:
            wf_state, outcome = self._engine.step(wf_state)

            if outcome.type == "completed":
                for _step_id, _result in wf_state.step_results.items():
                    if isinstance(_result, dict) and _result.get("status") in (
                        "failed",
                        "timeout",
                    ):
                        raise _StepFailedError(
                            _result.get("error", f"Step '{_step_id}' failed")
                        )
                final_text = str(
                    wf_state.step_results.get(outcome.step_id or "", "Done.")
                )
                return final_text

            if outcome.type == "failed":
                error = outcome.error or wf_state.error or "Unknown workflow failure"
                raise _StepFailedError(error)

            if outcome.type == "continue":
                continue

            if outcome.type == "llm_call":
                wf_state = self._dispatch_llm_call(wf_state, outcome)
                continue

            if outcome.type == "tool_execute":
                wf_state = self._dispatch_tool_execute(wf_state, outcome)
                continue

            if outcome.type == "sub_workflow":
                wf_state = self._dispatch_sub_workflow(wf_state, outcome)
                continue

            if outcome.type == "waiting_for_input":
                raise _StepFailedError(
                    f"Workflow step '{outcome.step_id}' requested user_input — "
                    "not supported in todo-execute-item."
                )

    # ── outcome dispatchers ─────────────────────────────────────────────

    def _dispatch_llm_call(
        self,
        wf_state: WorkflowExecutionState,
        outcome: StepOutcome,
    ) -> WorkflowExecutionState:
        """Dispatch an ``llm_call`` outcome via the StrategyRouter.

        Renders ``{context.X}`` / ``{result.X}`` placeholders in the step
        config before routing.
        """
        rendered_config = _render_context_templates(
            outcome.config,
            wf_state.context,
            wf_state.step_results,
        )
        router_outcome = RouterOutcome(
            type="llm_call",
            payload={
                "prompt": rendered_config,
                "backend": "conversational",
                "memory": {},
                "plan_context": {},
                "tool_context": self._tool_context,
            },
            step_id=outcome.step_id,
        )
        result = self._strategy_router.route(router_outcome)
        if result.get("error") is None:
            wf_state, _ = self._engine.resume_with_result(
                wf_state, outcome.step_id, result["output"],
            )
        else:
            wf_state, _ = self._engine.fail_step(
                wf_state, outcome.step_id, result["error"],
            )
        return wf_state

    def _dispatch_tool_execute(
        self,
        wf_state: WorkflowExecutionState,
        outcome: StepOutcome,
    ) -> WorkflowExecutionState:
        """Dispatch a ``tool_execute`` outcome via the inline tool executor."""
        config = outcome.config
        try:
            result = self._inline_tool(config)
        except Exception as e:
            result = None
            logger.warning(
                "Inline tool executor raised for %s: %s",
                config.get("tool_name", config.get("skill_name", "?")),
                e,
            )

        if result is not None:
            wf_state, _ = self._engine.resume_with_result(
                wf_state, outcome.step_id, result,
            )
        else:
            wf_state, _ = self._engine.fail_step(
                wf_state, outcome.step_id,
                f"Tool '{config.get('tool_name', '?')}' not available inline.",
            )
        return wf_state

    def _dispatch_sub_workflow(
        self,
        wf_state: WorkflowExecutionState,
        outcome: StepOutcome,
    ) -> WorkflowExecutionState:
        """Dispatch a ``sub_workflow`` outcome.

        Starts the child workflow, runs it to completion, then resumes
        the parent workflow with the child's result as the step result.
        """
        child_wf_id = outcome.workflow_id
        if child_wf_id is None:
            wf_state, _ = self._engine.fail_step(
                wf_state, outcome.step_id,
                "sub_workflow outcome missing workflow_id",
            )
            return wf_state

        # Build child context from the step config's ``context`` dict,
        # with template rendering applied.
        child_config = outcome.config or {}
        child_context_raw = child_config.get("context", {})
        child_context = _render_context_templates(
            child_context_raw,
            wf_state.context,
            wf_state.step_results,
        )

        logger.debug(
            "Starting child workflow '%s' from step '%s'",
            child_wf_id, outcome.step_id,
        )

        try:
            child_state = self._engine.start_workflow(
                child_wf_id, context=child_context,
            )
            child_result = self._run_workflow_to_completion(child_state)
        except _StepFailedError as e:
            wf_state, _ = self._engine.fail_step(
                wf_state, outcome.step_id, str(e),
            )
            return wf_state

        wf_state, _ = self._engine.resume_with_result(
            wf_state, outcome.step_id, child_result,
        )
        return wf_state

    # ── adviser output parsing ──────────────────────────────────────────

    @staticmethod
    def _parse_complete_signal(adviser_output: str) -> bool:
        """Parse the adviser's output for the COMPLETE signal.

        Looks for ``COMPLETE: YES`` (case-insensitive, whitespace-tolerant).
        Any other value (``NO``, missing, ambiguous) is treated as NOT complete.

        Returns ``True`` only when the adviser **explicitly and verifiably**
        signals completion.
        """
        if not adviser_output:
            return False
        # Match "COMPLETE: YES" with flexible whitespace and case.
        match = re.search(
            r"COMPLETE\s*:\s*YES",
            adviser_output,
            re.IGNORECASE,
        )
        return match is not None


# ── internal error type ──────────────────────────────────────────────────


class _StepFailedError(Exception):
    """Raised when a per-item workflow step fails."""
    pass
