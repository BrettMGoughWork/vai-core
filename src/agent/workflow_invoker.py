"""
Workflow invoker for executing agent workflow plans.

Owns the workflow step-processing loop and the ``/invoke-workflow``
directive handler.  Extracted from supervisor.py per Sprint 18.4.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from src.agent.contracts import AgentResponse
from src.agent.interfaces.agent_state import LifecycleState
from src.agent.job_interface import dispatch_route
from src.agent.router import DEST_S4B, Route
from src.agent.strategy_router import RouterOutcome
from src.agent.workflow.engine import WorkflowExecutionState, WorkflowStatus


# ---------------------------------------------------------------------------
# Module-level helpers (shared with tool_orchestrator)
# ---------------------------------------------------------------------------


def _freeze_wf_state(wf_state: WorkflowExecutionState) -> Dict[str, Any]:
    """Serialise ``WorkflowExecutionState`` to a JSON-safe dict.

    The result is stored in ``supervisor_metadata["workflow_state"]``
    to survive WAITING \u2192 resume cycles.
    """
    return {
        "execution_id": wf_state.execution_id,
        "workflow_id": wf_state.workflow_id,
        "current_step_id": wf_state.current_step_id,
        "context": dict(wf_state.context),
        "step_results": dict(wf_state.step_results),
        "status": wf_state.status.value,
        "error": wf_state.error,
    }


def _render_context_templates(
    config: Dict[str, Any],
    context: Dict[str, Any],
    step_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace ``{context.X}`` and ``{result.X}`` placeholders in config values.

    Scans every string value in the config dict and substitutes:
      - ``{context.key}`` -> ``context.get("key", "")``
      - ``{result.step_id}`` -> ``step_results.get("step_id", "")``
    """
    rendered: Dict[str, Any] = {}
    for key, raw_value in config.items():
        if not isinstance(raw_value, str):
            rendered[key] = raw_value
            continue

        def _replace(m: re.Match) -> str:
            namespace = m.group(1)
            name = m.group(2)
            if namespace == "context":
                return str(context.get(name, ""))
            if namespace == "result":
                return str(step_results.get(name, ""))
            return m.group(0)

        rendered[key] = re.sub(
            r"\{(context|result)\.([a-zA-Z_0-9]+)\}",
            _replace,
            raw_value,
        )
    return rendered


def _restore_wf_state(d: Dict[str, Any]) -> WorkflowExecutionState:
    """Deserialise a dict back into a ``WorkflowExecutionState``."""
    return WorkflowExecutionState(
        execution_id=d["execution_id"],
        workflow_id=d["workflow_id"],
        current_step_id=d.get("current_step_id"),
        context={k: v for k, v in d.get("context", {}).items()},
        step_results={k: v for k, v in d.get("step_results", {}).items()},
        status=WorkflowStatus(d["status"]),
        error=d.get("error"),
    )


# ---------------------------------------------------------------------------
# WorkflowInvoker
# ---------------------------------------------------------------------------


class WorkflowInvoker:
    """Executes workflow step-processing loops and /invoke-workflow directives.

    Owns:
    - ``run_workflow_loop`` \u2014 deterministic step-processing loop
    - ``handle_invoke_workflow`` \u2014 parses and executes /invoke-workflow
      directives in LLM replies
    - ``parse_invoke_params`` \u2014 static helper for key="value" parsing
    """

    _WF_MAX_ITERATIONS = 50
    """Safety limit on sequential step iterations within one call."""

    def __init__(
        self,
        workflow_engine: Any,
        workflow_store: Any,
        *,
        strategy_router: Any = None,
        inline_tool_executor: Optional[Callable[[dict[str, Any]], dict[str, Any] | None]] = None,
        submit_job: Optional[Callable[[Any], str]] = None,
        interaction_manager: Any = None,
        agent_selector: Any = None,
        registry: Any = None,
        workflow_tool_adapter: Any = None,
        primitive_tool_adapter: Any = None,
    ) -> None:
        self._workflow_engine = workflow_engine
        self._workflow_store = workflow_store
        self._strategy_router = strategy_router
        self._inline_tool_executor = inline_tool_executor
        self._submit_job = submit_job
        self._interaction_manager = interaction_manager
        self._agent_selector = agent_selector
        self._registry = registry
        self._workflow_tool_adapter = workflow_tool_adapter
        self._primitive_tool_adapter = primitive_tool_adapter

    # ------------------------------------------------------------------
    # run_workflow_loop
    # ------------------------------------------------------------------

    def run_workflow_loop(
        self,
        state: Any,
        engine: Any,
        wf_state: WorkflowExecutionState,
        route: Any,
        meta: Dict[str, Any],
        new_errors: List[Dict[str, Any]],
        persist: Callable[[Any], Any],
    ) -> Any:
        """Deterministic step-processing loop.

        Processes steps until a blocking outcome (tool_execute,
        waiting_for_input) or a terminal outcome (completed, failed)
        is reached.
        """
        iteration = 0
        wf_store = self._workflow_store

        while iteration < self._WF_MAX_ITERATIONS:
            iteration += 1
            wf_state, outcome = engine.step(wf_state)
            wf_store.save(wf_state)

            # ── Deterministic transitions ──────────────────────────
            if outcome.type == "continue":
                continue

            # ── Terminal ───────────────────────────────────────────
            if outcome.type == "completed":
                meta.pop("workflow_state", None)
                meta.pop("workflow_waiting_for", None)
                final_msg = (
                    wf_state.context.get("_workflow_result")
                    or wf_state.context.get("result")
                    or "Workflow completed successfully."
                )
                return persist(state.with_(
                    lifecycle_state=LifecycleState.COMPLETED,
                    route_result=route,
                    final_response=AgentResponse(
                        reply=str(final_msg),
                        metadata={
                            "correlation_id": state.correlation_id,
                            "trace_id": state.trace_id,
                            "agent_id": state.agent_id,
                            "workflow_id": wf_state.workflow_id,
                            "route_destination": route.destination,
                        },
                    ),
                    supervisor_metadata=meta,
                    _reason="Workflow completed",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "execution_id": wf_state.execution_id,
                    },
                ))

            if outcome.type == "failed":
                meta.pop("workflow_state", None)
                meta.pop("workflow_waiting_for", None)
                return persist(state.with_(
                    lifecycle_state=LifecycleState.FAILED,
                    route_result=route,
                    errors=(list(state.errors) + new_errors + [{
                        "type": "workflow_step_failed",
                        "step_id": outcome.step_id,
                        "message": outcome.error or "Unknown workflow error",
                    }]),
                    supervisor_metadata=meta,
                    _reason=f"Workflow failed: {outcome.error}",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "step_id": outcome.step_id,
                    },
                ))

            # ── LLM call → route via StrategyRouter → resume / fail ──
            if outcome.type == "llm_call":
                rendered_config = _render_context_templates(
                    outcome.config,
                    wf_state.context,
                    wf_state.step_results,
                )

                # Agent selection: resolve agent_profile / agent_id from step config
                selected_agent_id: Optional[str] = None
                selected_agent_meta: Any = None
                if self._agent_selector is not None:
                    selected_agent_id = self._agent_selector.select(outcome.config)
                    try:
                        selected_agent_meta = self._registry.get_agent(selected_agent_id)
                    except Exception:  # AgentNotFoundError may not be importable
                        selected_agent_meta = None

                # Inject selected agent metadata into prompt
                if selected_agent_meta is not None:
                    if isinstance(rendered_config, dict):
                        rendered_config.setdefault("agent_id", selected_agent_id)
                        rendered_config.setdefault("agent_metadata", {
                            "name": selected_agent_meta.identity.name,
                            "description": selected_agent_meta.identity.description,
                            "persona": selected_agent_meta.persona,
                        })

                # Merge pattern_instructions (from apply_pattern step) into agent_metadata
                pattern_instructions = rendered_config.pop("pattern_instructions", None)
                if pattern_instructions and "agent_metadata" in rendered_config:
                    existing_patterns = rendered_config["agent_metadata"].get("patterns", [])
                    rendered_config["agent_metadata"]["patterns"] = pattern_instructions + existing_patterns

                # Build tool_context from workflow + primitive tool adapters
                tool_context: list[dict] = []
                if self._workflow_tool_adapter is not None:
                    tool_context = self._workflow_tool_adapter.list_tools()
                if self._primitive_tool_adapter is not None:
                    primitive_tools = self._primitive_tool_adapter.list_tools()
                    tool_context.extend(primitive_tools)

                router_outcome = RouterOutcome(
                    type="llm_call",
                    payload={
                        "prompt": rendered_config,
                        "backend": "conversational",
                        "memory": {},
                        "plan_context": {},
                        "tool_context": tool_context,
                    },
                    step_id=outcome.step_id,
                )
                result = self._strategy_router.route(router_outcome)
                if result.get("error") is None:
                    wf_state, _ = engine.resume_with_result(
                        wf_state, outcome.step_id, result["output"],
                    )
                else:
                    wf_state, _ = engine.fail_step(
                        wf_state, outcome.step_id, result["error"],
                    )
                wf_store.save(wf_state)
                continue

            # ── Tool execute → dispatch to S4B → WAITING ──────────
            if outcome.type == "tool_execute":
                # Try inline tool execution first
                if self._inline_tool_executor is not None:
                    try:
                        inline_result = self._inline_tool_executor(outcome.config)
                    except Exception:
                        inline_result = None
                    if inline_result is not None:
                        wf_state, _ = engine.resume_with_result(
                            wf_state, outcome.step_id, inline_result,
                        )
                        wf_store.save(wf_state)
                        continue

                tool_route = Route(
                    destination=DEST_S4B,
                    payload=outcome.config,
                    agent_id=state.agent_id,
                )
                dispatch_result = dispatch_route(
                    route=tool_route,
                    submit_job_callable=self._submit_job,
                )
                if dispatch_result.errors:
                    for _jid, err_msg in dispatch_result.errors:
                        new_errors.append({
                            "type": "workflow_dispatch_error",
                            "step_id": outcome.step_id,
                            "message": err_msg,
                        })

                if dispatch_result.dispatched_jobs:
                    meta["workflow_state"] = _freeze_wf_state(wf_state)
                    meta["workflow_waiting_for"] = "tool_result"
                    meta["workflow_last_step_id"] = outcome.step_id
                    meta["workflow_last_result"] = {}
                    return persist(state.with_(
                        lifecycle_state=LifecycleState.WAITING,
                        route_result=route,
                        dispatch_result=dispatch_result,
                        errors=(list(state.errors) + new_errors),
                        supervisor_metadata=meta,
                        _reason=(
                            f"Workflow dispatched "
                            f"{len(dispatch_result.dispatched_jobs)} jobs"
                        ),
                        _details={
                            "workflow_id": wf_state.workflow_id,
                            "step_id": outcome.step_id,
                        },
                    ))

                # No jobs dispatched → treat as step failure
                wf_state, _ = engine.fail_step(
                    wf_state, outcome.step_id,
                    "tool_execute dispatched zero jobs",
                )
                wf_store.save(wf_state)
                continue

            # ── User input → WAITING ───────────────────────────────
            if outcome.type == "waiting_for_input":
                meta["workflow_state"] = _freeze_wf_state(wf_state)
                meta["workflow_waiting_for"] = "user_input"
                meta["workflow_waiting_step_id"] = outcome.step_id

                # Register an interaction request with the manager
                if self._interaction_manager is not None:
                    step_config = outcome.config or {}
                    prompt = step_config.get("prompt", "Please provide input:")
                    schema = step_config.get("input_schema", {})
                    req = self._interaction_manager.request_input(
                        instance_id=wf_state.workflow_id,
                        step_id=outcome.step_id,
                        prompt=prompt,
                        schema=schema,
                        timeout_seconds=step_config.get("timeout_seconds"),
                    )
                    meta["workflow_interaction_request_id"] = req.request_id
                    meta["workflow_interaction_prompt"] = prompt
                    meta["workflow_interaction_schema"] = schema

                return persist(state.with_(
                    lifecycle_state=LifecycleState.WAITING,
                    route_result=route,
                    errors=(list(state.errors) + new_errors),
                    supervisor_metadata=meta,
                    _reason="Workflow waiting for user input",
                    _details={
                        "workflow_id": wf_state.workflow_id,
                        "step_id": outcome.step_id,
                    },
                ))

            # ── Sub-workflow → start and loop ──────────────────────
            if outcome.type == "sub_workflow":
                sub_id = outcome.workflow_id or ""
                try:
                    wf_state = engine.start_workflow(
                        sub_id, context=dict(wf_state.context),
                    )
                except ValueError as exc:
                    wf_state, _ = engine.fail_step(
                        wf_state, outcome.step_id,
                        f"sub-workflow {sub_id!r}: {exc}",
                    )
                wf_store.save(wf_state)
                continue

            # ── Unreachable guard ───────────────────────────────────
            meta.pop("workflow_state", None)
            meta.pop("workflow_waiting_for", None)
            return persist(state.with_(
                lifecycle_state=LifecycleState.FAILED,
                route_result=route,
                errors=(list(state.errors) + new_errors + [{
                    "type": "workflow_unknown_outcome",
                    "message": f"Unknown outcome type {outcome.type!r}",
                }]),
                supervisor_metadata=meta,
                _reason=f"Unknown outcome type {outcome.type!r}",
            ))

        # ── Iteration limit ────────────────────────────────────────
        meta.pop("workflow_state", None)
        meta.pop("workflow_waiting_for", None)
        return persist(state.with_(
            lifecycle_state=LifecycleState.FAILED,
            route_result=route,
            errors=(list(state.errors) + new_errors + [{
                "type": "workflow_iteration_limit",
                "message": (
                    f"Workflow exceeded "
                    f"{self._WF_MAX_ITERATIONS} iterations"
                ),
            }]),
            supervisor_metadata=meta,
            _reason=f"Exceeded {self._WF_MAX_ITERATIONS} step iterations",
        ))

    # ------------------------------------------------------------------
    # handle_invoke_workflow
    # ------------------------------------------------------------------

    def handle_invoke_workflow(
        self, reply: str, wf_context: dict | None = None,
    ) -> str:
        """Parse and execute ``/invoke-workflow`` directives in an LLM reply.

        Scans *reply* for lines matching::

            /invoke-workflow <workflow_id> key1="value1" key2="value2"

        Each matching line starts a fresh workflow via
        ``self._workflow_engine``, runs **all non-blocking steps**
        (``llm_call``, ``sub_workflow``, ``tool_execute``)
        inline, and **waits** if the workflow reaches ``waiting_for_input``
        or terminates.  Results are appended to *reply* so the caller sees
        both the LLM's original text and the workflow outcomes.

        Returns *reply* unmodified if ``self._workflow_engine`` is ``None``
        or no ``/invoke-workflow`` directives are found.
        """
        if self._workflow_engine is None:
            return reply

        pattern = re.compile(
            r'^/invoke-workflow\s+(\S+)'          # workflow_id
            r'(?:\s+(.+))?',                       # everything after \u2192 key="val" pairs
            re.MULTILINE,
        )

        parts: list[str] = [reply]
        for match in pattern.finditer(reply):
            raw_wf_id = match.group(1)
            # Strip the "workflow.execute." prefix used by WorkflowToolAdapter
            wf_id = raw_wf_id
            for prefix in ("workflow.execute.", "workflow."):
                if wf_id.startswith(prefix):
                    wf_id = wf_id[len(prefix):]
                    break
            raw_params = match.group(2) or ""

            # Parse key="value" pairs (handles \" inside JSON values)
            params: dict[str, str] = self.parse_invoke_params(raw_params)

            context = dict(wf_context or {})
            context.update(params)

            try:
                wf_state = self._workflow_engine.start_workflow(
                    wf_id, context=context,
                )
            except ValueError as exc:
                parts.append(
                    f"\n\n[Workflow {wf_id!r} not found: {exc}]"
                )
                continue

            wf_store = self._workflow_store
            wf_store.save(wf_state)

            iteration = 0
            final_result: str | None = None
            hitl_input: str | None = None

            while iteration < self._WF_MAX_ITERATIONS:
                iteration += 1
                wf_state, outcome = self._workflow_engine.step(wf_state)
                wf_store.save(wf_state)

                if outcome.type == "continue":
                    continue

                if outcome.type == "completed":
                    final_result = (
                        wf_state.context.get("_workflow_result")
                        or wf_state.context.get("result")
                        or "Workflow completed successfully."
                    )
                    break

                if outcome.type == "failed":
                    final_result = (
                        f"Workflow failed: {outcome.error or 'Unknown error'}"
                    )
                    break

                if outcome.type == "waiting_for_input":
                    hitl_input = outcome.prompt or "Awaiting your input."
                    break

                if outcome.type == "llm_call":
                    rendered_config = _render_context_templates(
                        outcome.config,
                        wf_state.context,
                        wf_state.step_results,
                    )
                    ro = RouterOutcome(
                        type=outcome.type,
                        payload=dict(rendered_config) if isinstance(rendered_config, dict) else {},
                        step_id=outcome.step_id,
                    )
                    route_result = self._strategy_router.route(ro)
                    if route_result.get("error") is None:
                        wf_state, _ = self._workflow_engine.resume_with_result(
                            wf_state, outcome.step_id, route_result["output"],
                        )
                    else:
                        wf_state, _ = self._workflow_engine.fail_step(
                            wf_state, outcome.step_id, route_result["error"],
                        )
                    wf_store.save(wf_state)
                    continue

                if outcome.type == "tool_execute":
                    if self._inline_tool_executor is not None:
                        try:
                            inline_result = self._inline_tool_executor(outcome.config)
                        except Exception:
                            inline_result = None
                        if inline_result is not None:
                            wf_state, _ = self._workflow_engine.resume_with_result(
                                wf_state, outcome.step_id, inline_result,
                            )
                            wf_store.save(wf_state)
                            continue
                    parts.append(
                        f"\n\n[Workflow {wf_id!r} reached tool_execute \u2014 "
                        f"dispatch not available in tool context]"
                    )
                    final_result = "Tool execution deferred."
                    break

                if outcome.type == "sub_workflow":
                    sub_id = outcome.workflow_id or ""
                    try:
                        wf_state = self._workflow_engine.start_workflow(
                            sub_id, context=dict(wf_state.context),
                        )
                    except ValueError as exc:
                        wf_state, _ = self._workflow_engine.fail_step(
                            wf_state, outcome.step_id, str(exc),
                        )
                    wf_store.save(wf_state)
                    continue

            else:
                final_result = f"Workflow exceeded {self._WF_MAX_ITERATIONS} iterations"

            summary = final_result or "Workflow completed."
            parts.append(f"\n\n---\n**Workflow {wf_id!r} result:** {summary}")
            if hitl_input:
                parts.append(f"\n_Input required: {hitl_input}_")

        return "".join(parts)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_invoke_params(raw: str) -> dict[str, Any]:
        """Parse ``key="value"`` pairs, handling ``\\"`` inside JSON values."""
        result: dict[str, Any] = {}
        for kv in re.finditer(r'(\w+)="((?:[^"\\]|\\.)*)"', raw):
            raw_val = kv.group(2)
            # Unescape \" -> "
            val = re.sub(r'\\(.)', r'\1', raw_val)
            # Auto-deserialise JSON values (dicts and lists)
            if val and val[0] in ("{", "["):
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    pass  # keep as string
            result[kv.group(1)] = val
        return result


# Backward-compatible alias for external callers that import
# from the old location.
_render_context_templates_alias = _render_context_templates
