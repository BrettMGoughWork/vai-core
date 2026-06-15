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

from src.runtime.interfaces import (
    PromptRequest,
    PromptResponse,
    S1Error,
    call_runtime_backend,
)


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
    """

    def __init__(
        self,
        *,
        call_runtime: Callable[..., Any] = call_runtime_backend,
        planner: Optional[Callable[..., Any]] = None,
        capability_discoverer: Optional[Callable[[], list]] = None,
        submit_s4_job: Optional[Callable[[Any], Any]] = None,
    ) -> None:
        self._call_runtime = call_runtime
        self._planner = planner
        self._capability_discoverer = capability_discoverer
        self._submit_s4_job = submit_s4_job

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

    def _route_to_llm(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Direct, synchronous LLM call via S1 Runtime with mock fallback.

        Attempts the requested backend (default ``"conversational"``).
        If that returns an ``S1Error``, falls back to the ``"mock"``
        backend so the supervisor always gets a usable response.
        """
        prompt = outcome.payload.get("prompt", {})
        backend = outcome.payload.get("backend", "conversational")

        runtime_request = PromptRequest(
            prompt=prompt,
            memory=outcome.payload.get("memory", {}),
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
        """Generate a plan via S2, then submit plan steps as S4 jobs.

        Requires ``planner``, ``capability_discoverer``, and
        ``submit_s4_job`` to be configured at construction time.
        """
        if self._planner is None or self._capability_discoverer is None:
            raise NotImplementedError(
                "planner and capability_discoverer must be configured "
                "before routing planner outcomes"
            )
        if self._submit_s4_job is None:
            raise NotImplementedError(
                "submit_s4_job must be configured before routing planner outcomes"
            )

        # 1. Discover available skills
        available = self._capability_discoverer()

        # 2. Call S2 planner (stub — returns a mock plan for now)
        goal = outcome.payload.get("goal", "")
        plan = self._planner(goal=goal, context=outcome.payload.get("context"))

        # 3. Submit each plan step as an S4 job for durable execution
        steps = getattr(plan, "steps", [])
        job_ids: list[str] = []
        for step in steps:
            job = self._submit_s4_job({
                "type": "plan_step",
                "plan_id": getattr(plan, "plan_id", ""),
                "step_id": getattr(step, "id", ""),
                "skill_ref": getattr(step, "skill_ref", ""),
                "params": outcome.payload.get("params", {}),
            })
            job_ids.append(getattr(job, "job_id", str(job)))

        return {
            "output": (
                f"Plan created: {len(steps)} steps, "
                f"{len(job_ids)} jobs submitted"
            ),
            "metadata": {
                "plan_id": getattr(plan, "plan_id", ""),
                "job_ids": job_ids,
            },
            "error": None,
        }

    def _route_to_capabilities(self, outcome: RouterOutcome) -> Dict[str, Any]:
        """Execute a tool/skill call via S3, submitted as an S4 job.

        Requires ``submit_s4_job`` to be configured at construction time.
        """
        if self._submit_s4_job is None:
            raise NotImplementedError(
                "submit_s4_job must be configured before routing tool outcomes"
            )

        job = self._submit_s4_job({
            "type": "tool_call",
            "skill_name": outcome.payload.get("skill_name", ""),
            "arguments": outcome.payload.get("arguments", {}),
        })
        job_id = getattr(job, "job_id", str(job))

        return {
            "output": f"Tool call submitted as job {job_id}",
            "metadata": {"job_id": job_id},
            "error": None,
        }
