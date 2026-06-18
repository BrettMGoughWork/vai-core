"""
R.5 — Strategy Router
=====================

Routes workflow outcomes to the correct execution layer:

- ``llm_call``       → S1 Runtime (direct LLM call with mock fallback)
- ``planner_call``   → S2 Planner (plan generation, submitted as S4 jobs)
- ``tool_call``      → S3 via S4 job (capability execution)

The StrategyRouter replaces direct ``call_runtime_backend()`` calls in
the Supervisor, decoupling S5 from the S1 runtime interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from src.runtime.interfaces import (
    PromptRequest,
    PromptResponse,
    S1Error,
)
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.planning.s1_contract.s1_client import call_runtime_backend
from src.strategy.types.subgoal import Subgoal


@dataclass(frozen=True)
class RouterOutcome:
    """Instruction for the StrategyRouter to dispatch to a specific layer.

    Fields
    ------
    type:
        One of ``"llm_call"``, ``"planner_call"``, ``"tool_call"``.
    payload:
        Data required by the target layer.  Keys differ by route:
        - ``llm_call``:  ``prompt``, ``backend``, ``memory``, ``plan_context``, ``tool_context``
        - ``planner_call``: ``goal``, ``context``, ``params``
        - ``tool_call``: ``skill_name``, ``arguments``
    step_id:
        Optional workflow step identifier for result correlation.
    """

    type: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    step_id: str = ""


class StrategyRouter:
    """Routes workflow outcomes to the correct execution layer.

    The router owns dispatch to S1 (LLM), S2 (Planner), and S3 (capabilities).
    The supervisor no longer calls S1 directly.

    Parameters
    ----------
    call_runtime:
        Callable wrapping ``call_runtime_backend``.  Defaults to the real
        function so the router works out-of-the-box.
    planner:
        Optional callable for plan generation (S2).  When None,
        ``_route_to_planner`` raises ``NotImplementedError``.
    capability_discoverer:
        Optional callable for skill discovery (S3).  When None,
        ``_route_to_capabilities`` raises ``NotImplementedError``.
    submit_s4_job:
        Optional callable to submit a job to S4.  Required for planner
        and capability routes.  When None, those routes raise
        ``NotImplementedError``.
    governance:
        Shared ``MemoryGovernance`` instance for cross-store consistency.
        When set, a subgoal is created via ``governance.put_subgoal()``
        before calling the planner.  When ``None``, the planner is called
        without subgoal creation (backwards-compatible mode).
    """

    def __init__(
        self,
        *,
        call_runtime: Callable[..., Any] = call_runtime_backend,
        planner: Optional[Callable[..., Any]] = None,
        capability_discoverer: Optional[Callable[[], list]] = None,
        submit_s4_job: Optional[Callable[[Any], Any]] = None,
        skill_executor: Optional[Any] = None,
        validation_pipeline: Optional[Any] = None,
        step_executor: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        governance: Optional[MemoryGovernance] = None,
    ) -> None:
        self._call_runtime = call_runtime
        self._planner = planner
        self._capability_discoverer = capability_discoverer
        self._submit_s4_job = submit_s4_job
        self._skill_executor = skill_executor
        self._validation_pipeline = validation_pipeline
        self._step_executor = step_executor
        self._governance = governance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Route a workflow outcome to the correct execution layer.

        Args:
            outcome: The outcome to dispatch.

        Returns:
            A result dict with keys ``output``, ``error``, and optional
            ``runtime_fallback`` / ``runtime_error``.

        Raises:
            ValueError: If ``outcome.type`` is not recognised.
        """
        t = outcome.type
        if t == "llm_call":
            return self._route_to_llm(outcome)
        if t == "planner_call":
            return self._route_to_planner(outcome)
        if t == "tool_call":
            return self._route_to_capabilities(outcome)
        raise ValueError(
            f"Unknown route type: {t!r}. "
            f"Expected one of: llm_call, planner_call, tool_call"
        )

    # ------------------------------------------------------------------
    # Route handlers
    # ------------------------------------------------------------------

    def _build_governance_context(self) -> Dict[str, Any]:
        """Gather current governance state for conversational turns.

        Reads from the shared ``MemoryGovernance`` instance (if set) and
        returns a dict that can be injected into ``PromptRequest.memory``
        so the LLM has visibility into governance state (active subgoals,
        drift events, consistency violations).

        Returns an empty dict when governance is not configured, so callers
        can simply merge the result without an ``if`` guard.
        """
        if self._governance is None:
            return {}
        try:
            violations = self._governance.check_consistency()
            return {
                "consistency_issues": [str(v) for v in violations] if violations else [],
            }
        except Exception:
            return {}

    def _route_to_llm(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Direct, synchronous LLM call via S1 Runtime with mock fallback.

        Attempts the requested backend (default ``"conversational"``).
        If that returns an ``S1Error``, falls back to the ``"mock"``
        backend so the supervisor always gets a usable response.

        When a ``MemoryGovernance`` instance is configured, governance
        context (consistency state, active subgoals) is also injected
        into the memory payload so the LLM has visibility into the
        current governance state (4a.5 / 4a.6).
        """
        prompt = outcome.payload.get("prompt", {})
        backend = outcome.payload.get("backend", "conversational")

        # Build memory payload — start with base from outcome, enrich
        # with governance context if governance is configured.
        memory = outcome.payload.get("memory", {})
        governance_context = self._build_governance_context()
        if governance_context:
            memory["governance"] = governance_context

        runtime_request = PromptRequest(
            prompt=prompt,
            memory=memory,
            plan_context=outcome.payload.get("plan_context", {}),
            tool_context=outcome.payload.get("tool_context", []),
        )

        response = self._call_runtime(runtime_request, backend=backend)

        if isinstance(response, PromptResponse):
            return {
                "output": response.output,
                "tool_calls": getattr(response, "tool_calls", []),
                "error": None,
            }

        # First attempt failed — try mock fallback
        error_msg: str = getattr(response, "message", str(response))
        fallback = self._call_runtime(runtime_request, backend="mock")
        if isinstance(fallback, PromptResponse):
            return {
                "output": fallback.output,
                "tool_calls": getattr(fallback, "tool_calls", []),
                "error": None,
                "runtime_fallback": True,
                "runtime_error": error_msg,
            }

        # Both conversational and mock failed
        return {
            "output": {"message": f"[Runtime unavailable: {error_msg}]"},
            "error": error_msg,
            "runtime_error": True,
        }

    def _route_to_planner(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Generate a plan via S2, then execute each plan step inline.

        If a ``step_executor`` is configured, steps are executed
        synchronously and their results collected.  Otherwise falls
        back to submitting each step as an S4 job.

        Requires ``planner``, ``capability_discoverer``, and either
        ``step_executor`` or ``submit_s4_job`` to be configured.
        """
        if self._planner is None or self._capability_discoverer is None:
            raise NotImplementedError(
                "planner and capability_discoverer must be configured "
                "before routing planner outcomes"
            )

        # 1. Discover available skills
        available = self._capability_discoverer()

        # 2. Get goal from outcome
        goal = outcome.payload.get("goal", "")

        # 3. Create subgoal in shared governance (if configured)
        if self._governance is not None:
            subgoal = Subgoal(
                subgoal_id=f"sg-{uuid4().hex[:16]}",
                goal=goal,
                context=outcome.payload.get("context", {}),
                metadata={},
            )
            self._governance.put_subgoal(subgoal)
            subgoal_id = subgoal.subgoal_id
        else:
            subgoal_id = f"sg-{hash(goal) & 0xFFFFFFFF:08x}"

        # 4. Call S2 planner with governance context
        plan = self._planner(
            goal=goal,
            subgoal_id=subgoal_id,
            governance=self._governance,
            capabilities=available,
        )

        # 5. Execute each plan step (inline via step_executor, or submit as S4 job)
        steps = getattr(plan, "steps", [])
        step_results: list[Dict[str, Any]] = []
        job_ids: list[str] = []

        for step in steps:
            step_payload = {
                "type": "plan_step",
                "plan_id": getattr(plan, "plan_id", ""),
                "step_id": getattr(step, "id", ""),
                "skill_ref": getattr(step, "skill_ref", ""),
                "inputs": getattr(step, "inputs", {}),
                "description": getattr(step, "description", ""),
            }

            if self._step_executor is not None:
                result = self._step_executor(step_payload)
                step_results.append(result)
            elif self._submit_s4_job is not None:
                job = self._submit_s4_job(step_payload)
                job_ids.append(getattr(job, "job_id", str(job)))
            else:
                raise NotImplementedError(
                    "step_executor or submit_s4_job must be configured "
                    "before routing planner outcomes"
                )

        # Build a readable summary from step results
        lines: list[str] = []
        for sr in step_results:
            status = sr.get("status", "unknown")
            msg = sr.get("message", "")
            sid = sr.get("step_id", "")
            lines.append(f"  [{status}] {sid}: {msg}")
        plan_summary = f"Plan {getattr(plan, 'plan_id', '')}: {len(steps)} steps\n" + "\n".join(lines)

        return {
            "output": {
                "message": plan_summary,
                "plan_id": getattr(plan, "plan_id", ""),
                "intent": getattr(plan, "intent", ""),
                "reasoning_summary": getattr(plan, "reasoning_summary", ""),
                "steps": step_results,
            },
            "metadata": {
                "plan_id": getattr(plan, "plan_id", ""),
                "step_count": len(steps),
                "job_ids": job_ids or None,
            },
            "error": None,
        }

    def _route_to_capabilities(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Execute a tool/skill call via S3 or submit as an S4 job.

        If ``skill_executor`` is configured, executes directly (S3).
        Otherwise, submits as an S4 job for durable execution.

        When executing directly, the optional ``validation_pipeline``
        runs shape validation + anomaly detection + drift evaluation
        on the result.
        """
        skill_name = outcome.payload.get("skill_name", "")
        arguments = outcome.payload.get("arguments", {})

        # --- Direct execution path (S3) ---
        if self._skill_executor is not None:
            result = self._skill_executor.execute(
                skill_name=skill_name,
                arguments=arguments,
            )
            response: Dict[str, Any] = {
                "output": result.output if result.success else None,
                "error": result.error if not result.success else None,
                "metadata": {"direct": True},
            }

            # Optional validation pipeline (S5)
            if self._validation_pipeline is not None and result.success:
                schemas = outcome.payload.get("output_schema", None)
                diagnostics = self._validation_pipeline.apply(
                    skill_name=skill_name,
                    actual_output=result.output,
                    expected_schema=schemas,
                    subgoal_id=outcome.payload.get("subgoal_id", ""),
                    segment_id=outcome.payload.get("segment_id", ""),
                    step_id=outcome.step_id,
                )
                response["metadata"]["validation"] = diagnostics

            return response

        # --- S4 job submission fallback ---
        if self._submit_s4_job is None:
            raise NotImplementedError(
                "submit_s4_job must be configured before routing tool outcomes"
            )

        job = self._submit_s4_job({
            "type": "tool_call",
            "skill_name": skill_name,
            "arguments": arguments,
        })
        job_id = getattr(job, "job_id", str(job))

        return {
            "output": f"Tool call submitted as job {job_id}",
            "metadata": {"direct": False, "job_id": job_id},
            "error": None,
        }
