"""TodoWorker — S4-compatible WorkExecutor for processing todo lists (Sprint 12a.3).

Each ``__call__`` invocation processes ONE todo item from the list. This lets
the S4 ExecutionStage's multi-cycle loop handle iteration and checkpointing.
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
    ) -> None:
        self._engine = workflow_engine
        self._strategy_router = strategy_router
        self._inline_tool = inline_tool_executor
        self._tool_context = tool_context or []

    @deadcode_ignore
    def __call__(
        self,
        payload: dict,
        execution_context: Any = None,
        resume_token: Any = None,
        **kwargs: Any,
    ) -> dict:
        """Process ONE todo item.

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
        # execution_context may be a dict (from ExecutionStage's .to_dict())
        # or an ExecutionContext object (from direct calls / tests).
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
            else:
                # Mark in_progress (no-op if already in_progress from crash resume).
                store.mark_in_progress(item.id)

                # 3. Run the per-item workflow.
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

    # ── per-item workflow dispatch ──────────────────────────────────────

    def _run_item_workflow(
        self,
        item: Any,
        store: TodoStore,
        conn: sqlite3.Connection,
    ) -> str:
        """Run the ``todo-execute-item`` workflow for a single todo.

        Starts the workflow with ``item`` in the initial context, then
        dispatches ``llm_call`` and ``tool_execute`` outcomes until the
        workflow completes or fails.
        """
        wf_state = self._engine.start_workflow(
            _TODO_EXECUTE_ITEM_WORKFLOW,
            context={
                "todo_id": item.id,
                "todo_title": item.title,
                "todo_description": item.description,
                "deps": item.depends_on,
                "db_path": conn.execute("PRAGMA database_list").fetchone()["file"],
            },
        )

        while True:
            wf_state, outcome = self._engine.step(wf_state)

            if outcome.type == "completed":
                # Detect completion-via-failure: when a step's on_failure
                # transition points to __end__, the engine returns "completed"
                # but the step_results record the error.  Treat that as a
                # failure so the todo gets retried instead of marked done.
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

            if outcome.type == "waiting_for_input":
                raise _StepFailedError(
                    f"Workflow step '{outcome.step_id}' requested user_input — "
                    "not supported in todo-execute-item."
                )

            if outcome.type in ("sub_workflow",):
                raise _StepFailedError(
                    f"Outcome '{outcome.type}' not yet supported in "
                    f"todo-execute-item (step '{outcome.step_id}')."
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


# ── internal error type ──────────────────────────────────────────────────


class _StepFailedError(Exception):
    """Raised when a per-item workflow step fails."""
    pass
