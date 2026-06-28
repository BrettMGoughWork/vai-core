"""
DevSquad Pipeline Driver — synchronous workflow executor.

Drives a workflow (and any chained workflows triggered by events
published during execution) to completion — all in-process, without
the Supervisor's async cognitive loop.

Works by:
1. Starting workflows directly via the engine (bypassing the EventBus)
2. Stepping through each workflow, handling LLM calls and tool execution
3. Intercepting ``publish_event`` tool results to find the next
   workflow(s) in the chain and queueing them
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.agent.strategy_router import RouterOutcome
from src.agent.workflow import WorkflowEngine, WorkflowInstanceStore, WorkflowStatus
from src.agent.workflow.engine import WorkflowExecutionState

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 200


def _render_templates(config: Any, context: dict, step_results: dict) -> Any:
    """Resolve ``{{ placeholder }}`` values in a step config dict.

    Delegates to ``composition_root._render_template()`` which correctly
    handles ``input.*``, ``context.*``, and ``steps.*`` prefixes, plus
    Jinja2-style pipe filters (``| default('')``, ``| length``).
    """
    # Lazy import to avoid circular dependency at module level
    from src.agent.composition_root import _render_template as _rt
    return _rt(config, context, step_results)


class PipelineDriver:
    """Synchronous workflow chain executor.

    Usage::

        driver = PipelineDriver(engine, strategy_router, inline_tool_executor)
        results = driver.run_pipeline(initial_payload)
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        strategy_router: Any,
        inline_tool_executor: Any,
        prompt_registry: Any = None,
    ) -> None:
        self._engine = engine
        self._strategy_router = strategy_router
        self._inline_tool_executor = inline_tool_executor
        self._prompt_registry = prompt_registry
        self._store = WorkflowInstanceStore()
        self._results: list[dict[str, Any]] = []
        self._pending: list[WorkflowExecutionState] = []
        self._wf_registry: Any = None  # resolved lazily

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        initial_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Start all workflows that trigger on a ``sprint.init``-like event
        and drive the full chain to completion.

        Args:
            initial_payload:
                Context dict (project_id, title, requirement, etc.)
                passed into the first workflow.

        Returns:
            List of result dicts, one per workflow instance that ran.
        """
        self._results.clear()
        self._pending.clear()

        # Resolve the workflow registry from composition_root
        from src.agent.composition_root import wf_registry as _wf_registry
        self._wf_registry = _wf_registry

        # Find the first workflow(s) via the event trigger mapping.
        # Use "sprint.init" as the trigger event name.
        trigger_event = "sprint.init"
        matches = self._wf_registry.find_by_trigger(trigger_event)
        for defn in matches:
            state = self._engine.start_workflow(
                defn.workflow_id,
                context=dict(initial_payload),
            )
            self._store.save(state)
            self._pending.append(state)
            logger.info(
                "PipelineDriver: queued %s (execution=%s)",
                defn.workflow_id, state.execution_id,
            )

        # Process queue — new workflows may be added by chained events
        while self._pending:
            state = self._pending.pop(0)
            result = self._run_single(state)
            self._results.append(result)

            # Emit a JSON progress line so the sliding-wall timeout
            # in CLIPrimitive sees activity after each workflow.
            print(
                json.dumps(
                    {
                        "progress": "workflow_completed",
                        "workflow": state.workflow_id,
                        "status": result.get("status", "?"),
                    }
                )
            )

        return self._results

    # ------------------------------------------------------------------
    # Internal: single-workflow runner
    # ------------------------------------------------------------------

    def _run_single(self, state: WorkflowExecutionState) -> dict[str, Any]:
        """Step *state* to completion (or blocking point).

        When a ``publish_event`` tool fires, the EventBus calls the
        TriggerRouter synchronously.  That creates new workflow states
        via ``engine.start_workflow()``, but does NOT store or step
        them.  Our store intercept uses ``_capture_engine_starts()``
        to catch those new states.
        """
        # Wrap engine.start_workflow to capture chained workflow states
        original_start = self._engine.start_workflow
        self._engine.start_workflow = self._make_capturing_start(original_start)

        try:
            iteration = 0
            while iteration < _MAX_ITERATIONS:
                iteration += 1
                state, outcome = self._engine.step(state)
                self._store.save(state)

                if outcome.type == "continue":
                    continue

                if outcome.type == "completed":
                    return self._result("completed", state)

                if outcome.type == "failed":
                    return self._result("failed", state, error=outcome.error)

                if outcome.type == "waiting_for_input":
                    return self._result("waiting_for_input", state, prompt=outcome.prompt)

                if outcome.type == "llm_call":
                    self._handle_llm_call(state, outcome)
                    continue

                if outcome.type == "tool_execute":
                    self._handle_tool_execute(state, outcome)
                    continue

                if outcome.type == "sub_workflow":
                    self._handle_sub_workflow(state, outcome)
                    continue

                # Graceful fallback for unsupported outcome types
                # (e.g. council_deliberate, user_input from review/accepance workflows)
                return self._result(
                    "failed", state,
                    error=(
                        f"PipelineDriver does not support outcome type "
                        f"{outcome.type!r} (step {outcome.step_id}). "
                        f"This step requires a Supervisor cognitive loop."
                    ),
                )

            return self._result(
                "max_iterations", state,
                error=f"Exceeded {_MAX_ITERATIONS} iterations",
            )
        finally:
            self._engine.start_workflow = original_start

    # ------------------------------------------------------------------
    # Outcome handlers
    # ------------------------------------------------------------------

    def _handle_llm_call(self, state: WorkflowExecutionState, outcome: Any) -> None:
        """Resolve templates, route via StrategyRouter, resume step."""
        config = self._resolve_step_config(outcome.config, state)

        if self._is_agent_step(config):
            self._handle_agent_step(state, outcome, config)
            return

        self._handle_llm_route(state, outcome, config)

    def _resolve_step_config(
        self,
        config: Any,
        state: WorkflowExecutionState,
    ) -> Any:
        """Render templates and resolve prompt_template references."""
        config = _render_templates(config, state.context, state.step_results)
        if isinstance(config, dict):
            config.pop("pattern_instructions", None)

            prompt_id = config.pop("prompt_template", None)
            if prompt_id is not None and self._prompt_registry is not None:
                template = self._prompt_registry.get(prompt_id)
                if template is not None:
                    prompt_context: dict[str, str] = {}
                    for d in (state.context, state.step_results, config.get("context", {})):
                        if isinstance(d, dict):
                            for k, v in d.items():
                                prompt_context[k] = str(v) if v is not None else ""
                    if "project_id" not in prompt_context:
                        prompt_context["project_id"] = ""
                    system = template.system_prompt
                    user = template.user_prompt
                    for key, val in prompt_context.items():
                        ph = f"{{{key}}}"
                        if ph in system:
                            system = system.replace(ph, str(val))
                        if ph in user:
                            user = user.replace(ph, str(val))
                    config["system_prompt"] = system
                    config["user_prompt"] = user
                    config["message"] = user
                else:
                    logger.warning(
                        "prompt_template '%s' not found in PromptRegistry",
                        prompt_id,
                    )
        return config

    @staticmethod
    def _is_agent_step(config: Any) -> bool:
        """Check if the step config targets the engineer agent (tool-calling path)."""
        return (
            isinstance(config, dict)
            and config.get("job_family") == "job-family-engineer"
        )

    def _handle_agent_step(self, state: WorkflowExecutionState, outcome: Any, config: Any) -> None:
        """Execute an engineer tool-calling step and write a summary artifact."""
        from src.runtime.llm.client import _llm_transport as _agent_transport

        if _agent_transport is None:
            logger.error(
                "Agent step %s requires LLM transport, but none is configured. "
                "Failing step.",
                outcome.step_id,
            )
            state, _ = self._engine.fail_step(
                state, outcome.step_id,
                "LLM transport not available for agent step",
            )
            self._store.save(state)
            return

        _env_projects_root = os.environ.get(
            "DEVSQUAD_PROJECTS_ROOT", ".\\projects",
        )
        _agent_project_id = state.context.get("project_id", "")
        _agent_project_dir = (
            Path(_env_projects_root) / _agent_project_id
        )

        from src.devsquad.agentic_step import execute_agentic_step

        _agent_output = execute_agentic_step(
            config,
            project_dir=_agent_project_dir,
            llm_transport=_agent_transport,
        )

        logger.info(
            "Agent step %s completed: %d characters of output.",
            outcome.step_id,
            len(_agent_output),
        )

        # Write a summary artifact (the engineer's real output is files
        # in the project directory; the artifact is a human-readable report)
        project_id = state.context.get("project_id", "")
        summary = self._build_agent_artifact_summary(_agent_output, _agent_project_dir)
        self._write_output_artifact(config, summary, project_id)

        if _agent_output:
            state, _ = self._engine.resume_with_result(
                state, outcome.step_id, _agent_output,
            )
        else:
            state, _ = self._engine.fail_step(
                state, outcome.step_id,
                "Agent step returned empty output",
            )
        self._store.save(state)

    def _handle_llm_route(self, state: WorkflowExecutionState, outcome: Any, config: Any) -> None:
        """Route a non-agent LLM call through the StrategyRouter."""
        wrapped_payload: dict[str, Any] = {
            "prompt": dict(config) if isinstance(config, dict) else {},
            "backend": "conversational",
            "memory": {},
        }
        router_outcome = RouterOutcome(
            type=outcome.type,
            payload=wrapped_payload,
            step_id=outcome.step_id,
        )
        result = self._strategy_router.route(router_outcome)

        if result.get("error") is None:
            project_id = state.context.get("project_id", "")
            self._write_output_artifact(config, result.get("output", ""), project_id)
            state, _ = self._engine.resume_with_result(
                state, outcome.step_id, result["output"],
            )
        else:
            state, _ = self._engine.fail_step(
                state, outcome.step_id, result["error"],
            )
        self._store.save(state)

    def _handle_tool_execute(self, state: WorkflowExecutionState, outcome: Any) -> None:
        """Execute a tool inline and resume the step."""
        config = outcome.config
        tool_name = ""
        if isinstance(config, dict):
            tool_name = config.get("tool") or config.get("skill_name") or ""

        inline_result: Any = None
        if self._inline_tool_executor is not None:
            try:
                inline_result = self._inline_tool_executor(
                    config, state.context, state.step_results,
                )
            except Exception as exc:
                logger.warning("inline tool %r failed: %s", tool_name, exc)
                inline_result = None

        if inline_result is not None:
            state, _ = self._engine.resume_with_result(
                state, outcome.step_id, inline_result,
            )
            self._store.save(state)
        else:
            state, _ = self._engine.fail_step(
                state, outcome.step_id,
                f"Inline tool {tool_name!r} returned no result",
            )
            self._store.save(state)

    def _handle_sub_workflow(self, state: WorkflowExecutionState, outcome: Any) -> None:
        """Start a sub-workflow inline and queue it."""
        sub_id = outcome.workflow_id or ""
        try:
            sub_state = self._engine.start_workflow(
                sub_id, context=dict(state.context),
            )
            self._store.save(sub_state)
            self._pending.append(sub_state)
        except ValueError as exc:
            state, _ = self._engine.fail_step(
                state, outcome.step_id, str(exc),
            )
            self._store.save(state)

    def _write_output_artifact(
        self,
        config: dict[str, Any],
        output: Any,
        project_id: str,
    ) -> None:
        """Write LLM output to the artifact path specified in step config.

        Supports ``output_artifact`` keys with ``/projects/`` prefix that
        are resolved against the ``DEVSQUAD_PROJECTS_ROOT`` environment
        variable (default: ``.\\projects``).
        """
        artifact_path = config.get("output_artifact", "") if isinstance(config, dict) else ""
        if not artifact_path:
            return

        projects_root = os.environ.get("DEVSQUAD_PROJECTS_ROOT", ".\\projects")
        if artifact_path.startswith("/projects/"):
            relative = artifact_path[len("/projects/"):]
            full_path = Path(projects_root) / relative
        else:
            full_path = Path(artifact_path)

        full_path.parent.mkdir(parents=True, exist_ok=True)
        # Extract message content from S5 response envelope
        # (output is {"is_complete": ..., "message": "...", "confidence": ...})
        if isinstance(output, dict) and "message" in output:
            content_text = output["message"] if isinstance(output["message"], str) else str(output["message"])
        else:
            content_text = output if isinstance(output, str) else str(output)
        full_path.write_text(content_text, encoding="utf-8")
        logger.info(
            "Wrote artifact to %s (%d bytes)",
            full_path, len(content_text),
        )

    def _build_agent_artifact_summary(
        self,
        agent_output: str,
        project_dir: Path,
    ) -> str:
        """Build a human-readable summary for the engineer step artifact.

        The engineer's real output is files written to the project directory
        via tool calls.  This method creates a markdown report combining the
        LLM's final text response with a listing of files created/modified.
        """
        if not project_dir.exists():
            return agent_output

        file_entries: list[str] = []
        try:
            all_files = sorted(project_dir.rglob("*"))
            for f in all_files:
                if f.is_file():
                    rel = f.relative_to(project_dir)
                    try:
                        size = f.stat().st_size
                        file_entries.append(f"- 📄 `{rel}` ({size} bytes)")
                    except OSError:
                        file_entries.append(f"- `{rel}`")
        except Exception:
            pass

        if not file_entries:
            return agent_output

        header = (
            "## Summary\n\n"
            f"**Agent output:** {len(agent_output)} characters\n\n"
            "---\n\n"
            f"{agent_output}\n\n"
            "---\n\n"
            f"## Files Created/Modified ({len(file_entries)} total)\n\n"
        )
        body = "\n".join(file_entries[:100])
        if len(file_entries) > 100:
            body += f"\n\n... and {len(file_entries) - 100} more files"

        return header + body

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_capturing_start(
        self, original_start: Any,
    ) -> Any:
        """Return a wrapper around ``engine.start_workflow`` that stores new
        states in our instance store and enqueues them in ``_pending``."""

        def capturing_start(workflow_id: str, **kwargs: Any) -> WorkflowExecutionState:
            state = original_start(workflow_id, **kwargs)
            # Check if this workflow's trigger matches a chain event
            # (i.e. was it started by the TriggerRouter via EventBus?)
            # We always store + enqueue to be safe.
            self._store.save(state)
            already = any(
                p.execution_id == state.execution_id for p in self._pending
            )
            already_done = any(
                r.get("execution_id") == state.execution_id
                for r in self._results
            )
            if not already and not already_done:
                self._pending.append(state)
                logger.debug(
                    "PipelineDriver: captured chained workflow %s (exec=%s)",
                    state.workflow_id, state.execution_id,
                )
            return state

        return capturing_start

    @staticmethod
    def _result(
        status: str,
        state: WorkflowExecutionState,
        *,
        error: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": status,
            "workflow_id": state.workflow_id,
            "execution_id": state.execution_id,
        }
        if status == "completed":
            msg = (
                state.context.get("_workflow_result")
                or state.context.get("result")
                or ""
            )
            d["result"] = str(msg)
        if error:
            d["error"] = error
        if prompt:
            d["prompt"] = prompt
        return d
