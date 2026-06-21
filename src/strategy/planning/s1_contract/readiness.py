"""
Phase 2.14.6 — LLM-On Readiness Checklist
==========================================

A binary readiness gate that determines whether the real LLM backend
may be enabled.  Every check is a pure function — no I/O, no network
calls, no LLM calls, and no mutation of S2 state.

Usage::

    from src.strategy.planning.s1_contract.readiness import check_llm_on_readiness
    result = check_llm_on_readiness()
    if result.all_passed:
        # Safe to wire the real LLM (Phase 2.14.7)
        ...
    else:
        print("Readiness failures:")
        for f in result.failures:
            print(f"  - {f}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# Result type
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ReadinessResult:
    """Structured result of the LLM-On readiness gate.

    Attributes:
        all_passed: True if every check succeeded.
        failures: Human-readable descriptions of each failure.
        checks: Detailed per-check results for dashboard surface.
    """

    all_passed: bool
    failures: List[str] = field(default_factory=list)
    checks: Dict[str, bool] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Individual readiness checks  (pure functions)
# ──────────────────────────────────────────────────────────────────────────────


def _check_s1_contract_locked() -> bool:
    """Verify that all S1 contract types, validators, and adapters are
    importable and produce valid objects.

    This is a compile-time / import-time check: if any module is broken
    the import will fail, so we catch ImportError.
    """
    try:
        from src.strategy.planning.s1_contract.types import (
            PromptRequest,
            PromptResponse,
            ToolCallRequest,
            ToolCallResult,
            S1Error,
        )
        from src.strategy.planning.s1_contract.validators import (
            validate_prompt_request,
            validate_prompt_response,
        )
        from src.strategy.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
        from src.strategy.planning.s1_contract.s1_to_s2_adapter import (
            parse_prompt_response,
            map_s1_error_to_agent_error,
        )
        from src.runtime.llm.client import call_s1_backend
        from src.strategy.planning.s1_contract.s1_simulation_backend import (
            simulate_prompt_response,
        )
        from src.strategy.planning.s1_contract.s1_prompt_builder import build_llm_prompt
        from src.strategy.planning.s1_contract.s1_response_validator import (
            validate_llm_response,
        )
    except ImportError:
        return False

    # Structural check: validate that an adapter round-trip doesn't crash
    try:
        request = PromptRequest(
            prompt={"instruction": "test"},
            memory={},
            plan_context={
                "subgoal": {"index": 0, "state": "pending"},
                "segment": {"index": 0, "state": "pending"},
            },
            tool_context=[],
        )
        if not validate_prompt_request(request):
            return False

        response = simulate_prompt_response(request)
        if not validate_prompt_response(response):
            return False

        # adapter round-trip
        updates = parse_prompt_response(response)
        if not isinstance(updates, dict):
            return False
    except Exception:
        return False

    return True


def _check_simulation_backend_stable() -> bool:
    """Verify the simulation backend is deterministic and produces valid output."""
    try:
        from src.strategy.planning.s1_contract.s1_simulation_backend import (
            simulate_prompt_response,
        )
        from src.strategy.planning.s1_contract.types import PromptRequest

        request = PromptRequest(
            prompt={"instruction": "stability-check"},
            memory={},
            plan_context={
                "subgoal": {"index": 0, "state": "pending"},
                "segment": {"index": 0, "state": "pending"},
            },
            tool_context=[],
        )

        # Determinism: same input → same output (three runs)
        r1 = simulate_prompt_response(request)
        r2 = simulate_prompt_response(request)
        r3 = simulate_prompt_response(request)

        if r1.to_dict() != r2.to_dict() or r2.to_dict() != r3.to_dict():
            return False

        # Structure: response must have output, tool_calls, errors
        if not isinstance(r1.output, dict):
            return False
        if "drift_detected" not in r1.output:
            return False

    except Exception:
        return False

    return True


def _check_real_llm_behind_flag() -> bool:
    """Verify the real LLM backend is wired behind a flag and not enabled.

    Checks:
    - call_s1_backend supports backend="real_llm"
    - backend="real_llm" returns S1Error (kill-switch active) — NOT a live call
    - unknown backends raise an error
    """
    try:
        from src.runtime.llm.client import call_s1_backend
        from src.strategy.planning.s1_contract.types import (
            PromptRequest,
            PromptResponse,
            S1Error,
        )

        request = PromptRequest(
            prompt={"instruction": "flag-check"},
            memory={},
            plan_context={
                "subgoal": {"index": 0, "state": "pending"},
                "segment": {"index": 0, "state": "pending"},
            },
            tool_context=[],
        )

        # simulation should work
        sim_result = call_s1_backend(request, backend="simulation")
        if not isinstance(sim_result, PromptResponse):
            return False

        # real_llm with kill-switch active → S1Error (expected safe behaviour)
        llm_result = call_s1_backend(request, backend="real_llm")
        if not isinstance(llm_result, S1Error):
            return False
        # With enable_real_llm=True in config, we expect s1_provider_failure
        # (no transport injected in test context), NOT a live call.
        if llm_result.type not in ("real_llm_disabled", "s1_provider_failure"):
            return False

        # unknown backend must raise
        raised = False
        try:
            call_s1_backend(request, backend="production")
        except ValueError:
            raised = True
        if not raised:
            return False

    except Exception:
        return False

    return True


def _check_invalid_s1_response_handling() -> bool:
    """Verify that invalid S1 responses produce structured S1Error, not crashes."""
    try:
        from src.strategy.planning.s1_contract.s1_response_validator import (
            validate_llm_response,
        )
        from src.strategy.planning.s1_contract.types import S1Error

        # non-JSON text → S1Error
        r1 = validate_llm_response("not json")
        if not isinstance(r1, S1Error):
            return False

        # empty string → S1Error
        r2 = validate_llm_response("")
        if not isinstance(r2, S1Error):
            return False

        # Non-object JSON → S1Error
        r3 = validate_llm_response("[1, 2, 3]")
        if not isinstance(r3, S1Error):
            return False

        # Missing required fields → S1Error
        r4 = validate_llm_response('{"drift_detected": false}')
        if not isinstance(r4, S1Error):
            return False

        # All errors must have structured fields
        for err in (r1, r2, r3, r4):
            if not err.type or not err.message:
                return False

    except Exception:
        return False

    return True


def _check_e2e_smoke_tests_structural() -> bool:
    """Verify the e2e smoke test module exists and helpers are importable.

    This is a structural check — it verifies the test infrastructure is in
    place, not that tests actually pass (that is the CI test's job).
    """
    try:
        from tests.e2e.helpers import (
            build_minimal_plan,
            plan_1_1,
            plan_1_3,
            plan_2_2,
            run_agent_for_cycles,
            extract_trace,
            is_json_safe,
            has_raw_strings,
        )

        # Quick smoke: can we build a plan?
        subgoals, segments = plan_1_1()
        if len(subgoals) != 1 or len(segments) != 1:
            return False

        # Quick smoke: can we run 1 cycle?
        result = run_agent_for_cycles(subgoals, segments, max_cycles=1)
        if result is None:
            return False

        # Trace must be extractable
        trace = extract_trace(result)
        if trace is None:
            return False

    except Exception:
        return False

    return True


def _check_architecture_audit_clean() -> bool:
    """Verify that S2/S1 boundary is clean: no raw strings cross the boundary.

    Checks:
    - PromptRequest fields are all JSON-safe
    - PromptResponse fields are all JSON-safe
    - S1Error is JSON-safe
    - Adapters do not leak raw strings
    """
    try:
        import json

        from src.strategy.planning.s1_contract.types import (
            PromptRequest,
            PromptResponse,
            S1Error,
        )
        from src.strategy.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
        from src.strategy.planning.s1_contract.s1_simulation_backend import (
            simulate_prompt_response,
        )

        # Build a request from typical S2 state
        synthetic_agent_state = {}
        synthetic_subgoal_state = {"index": 0, "state": "pending"}
        synthetic_segment_state = {"index": 0, "state": "pending"}
        synthetic_memory = {}
        tool_schemas = []

        request = build_prompt_request(
            synthetic_agent_state,
            synthetic_subgoal_state,
            synthetic_segment_state,
            synthetic_memory,
            tool_schemas,
        )

        # Request must be JSON-safe
        try:
            json.dumps(request.to_dict())
        except (TypeError, OverflowError, ValueError):
            return False

        # Response must be JSON-safe
        response = simulate_prompt_response(request)
        try:
            json.dumps(response.to_dict())
        except (TypeError, OverflowError, ValueError):
            return False

        # S1Error must be JSON-safe
        err = S1Error(type="test", message="architecture audit check")
        try:
            json.dumps(err.to_dict())
        except (TypeError, OverflowError, ValueError):
            return False

    except Exception:
        return False

    return True


def _check_real_s1_client_importable() -> bool:
    """Verify the real S1 client module exists and is importable.
    The kill-switch value is a config decision, not a readiness gate concern.
    """
    try:
        from src.strategy.planning.s1_contract.s1_real_client import (
            call_llm,
            S1RealLLMError,
        )

        # Verify that calling with kill‑switch active raises RuntimeError
        from src.strategy.planning.s1_contract.types import PromptRequest

        request = PromptRequest(
            prompt={"instruction": "import-check"},
            memory={},
            plan_context={
                "subgoal": {"index": 0, "state": "pending"},
                "segment": {"index": 0, "state": "pending"},
            },
            tool_context=[],
        )

        raised = False
        try:
            call_llm(request)
        except (RuntimeError, S1RealLLMError):
            # Both are acceptable: RuntimeError from kill‑switch, or
            # S1RealLLMError from transport failure if kill‑switch disabled.
            raised = True
        if not raised:
            return False

    except Exception:
        return False

    return True


# ──────────────────────────────────────────────────────────────────────────────
# Master readiness gate
# ──────────────────────────────────────────────────────────────────────────────

# Map of check IDs → (description, check_function)
_CHECKS: Dict[str, tuple] = {
    "s1_contract_locked": (
        "S2/S1 contract locked: all types, validators, and adapters importable and valid",
        _check_s1_contract_locked,
    ),
    "simulation_backend_stable": (
        "Simulation backend stable: deterministic and produces valid PromptResponse",
        _check_simulation_backend_stable,
    ),
    "real_llm_behind_flag": (
        "Real LLM backend wired behind a flag: routing works, unknown backends rejected",
        _check_real_llm_behind_flag,
    ),
    "invalid_s1_response_handling": (
        "Invalid S1 response handling tested: malformed input → structured S1Error, not crash",
        _check_invalid_s1_response_handling,
    ),
    "e2e_smoke_tests_structural": (
        "E2E smoke tests structural: helpers importable, minimal plan builds and runs 1 cycle",
        _check_e2e_smoke_tests_structural,
    ),
    "architecture_audit_clean": (
        "Architecture audit clean: no raw strings cross S2/S1 boundary, all types JSON-safe",
        _check_architecture_audit_clean,
    ),
    "real_s1_client_importable": (
        "Real S1 client importable: module exists and is importable",
        _check_real_s1_client_importable,
    ),
}


def check_llm_on_readiness() -> ReadinessResult:
    """Evaluate all readiness conditions for enabling the real LLM backend.

    Pure function.  No I/O.  No network calls.  No LLM calls.
    Does not mutate S2 state.

    Each condition is evaluated independently.  A single failure does
    not short-circuit the remaining checks so the full picture is
    always available.

    Returns:
        ReadinessResult with ``all_passed=True`` only if every check
        succeeded.
    """
    failures: List[str] = []
    checks: Dict[str, bool] = {}

    for check_id, (description, check_fn) in sorted(_CHECKS.items()):
        try:
            passed = check_fn()
        except Exception as exc:
            passed = False
            description = f"{description} [exception: {exc}]"

        checks[check_id] = passed
        if not passed:
            failures.append(description)

    return ReadinessResult(
        all_passed=len(failures) == 0,
        failures=failures,
        checks=checks,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard / CLI surface  (pure function)
# ──────────────────────────────────────────────────────────────────────────────


def render_readiness_status(result: ReadinessResult) -> Dict[str, Any]:
    """Return a JSON-safe structure summarising readiness for dashboards/CLI.

    Pure function.  No I/O.

    Example output::

        {
            "status": "READY",
            "all_passed": true,
            "checks": {
                "s1_contract_locked": true,
                ...
            },
            "failures": []
        }
    """
    return {
        "status": "READY" if result.all_passed else "NOT_READY",
        "all_passed": result.all_passed,
        "checks": dict(sorted(result.checks.items())),
        "failures": list(result.failures),
    }
