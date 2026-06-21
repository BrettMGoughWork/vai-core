"""
runner.py — Core statistical conformance runner.

Orchestrates N repetitions of a scenario, collecting per-run metrics,
then aggregates and evaluates them against thresholds.

Pure except for calling the S1→S2 pipeline.
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import Any, Dict, List

from dotenv import load_dotenv

load_dotenv(override=True)

# Ensure project root is on path (for import symmetry)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from src.strategy.planning.s1_contract import s1_real_client
from src.strategy.planning.s1_contract.types import PromptRequest, PromptResponse, S1Error
from src.runtime.llm.client import call_s1_backend
from src.strategy.planning.s1_contract.s2_to_s1_adapter import build_prompt_request
from src.strategy.planning.s1_contract.s1_to_s2_adapter import parse_prompt_response
from src.strategy.planning.s1_contract.validators import (
    validate_prompt_request,
    validate_prompt_response,
)

from tests.e2e.helpers import plan_1_1, plan_1_3, plan_2_2, is_json_safe, has_raw_strings
from tests.e2e.helpers import validate_trace_structure

from tests.statistical.runner.scenario import ConformanceScenario
from tests.statistical.runner.aggregator import ConformanceResult, aggregate
from tests.statistical.runner.thresholds import Thresholds, evaluate


# ── Plan builder registry ───────────────────────────────────────────────────

_PLAN_BUILDERS = {
    "plan_1_1": plan_1_1,
    "plan_1_3": plan_1_3,
    "plan_2_2": plan_2_2,
}


# ── Fake S2 state (mirrors test_s1_s2_smoke.py pattern) ─────────────────────


class _FakeEnum:
    def __init__(self, value):
        self.value = value


class _FakeAgentState:
    def __init__(self, cycle=0, is_complete=False):
        self.cycle = cycle
        self.is_complete = is_complete


class _FakeSubgoalState:
    def __init__(self, index=0, state="active"):
        self.index = index
        self.state = _FakeEnum(state)


class _FakeSegmentState:
    def __init__(self, index=0, state="running"):
        self.index = index
        self.state = _FakeEnum(state)


def _make_fake_memory() -> dict:
    return {
        "subgoal_history": [],
        "segment_history": [],
        "drift_history": [],
        "repair_history": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Single-run executor
# ──────────────────────────────────────────────────────────────────────────────


def _execute_single_run(
    scenario: ConformanceScenario,
    run_index: int,
    plan_builder_name: str,
) -> Dict[str, Any]:
    """Execute a single S1→S2 cycle and return a per-run metrics dict.

    Parameters
    ----------
    scenario : ConformanceScenario
        The scenario being executed.
    run_index : int
        0-based index of this repetition.
    plan_builder_name : str
        Name of the plan builder to use.

    Returns
    -------
    dict
        Per-run result with keys: json_valid, schema_valid, is_error,
        has_raw_strings, is_json_safe, missing_trace_keys, s2_updates, error_details.
    """
    run_result: Dict[str, Any] = {
        "run_index": run_index,
        "json_valid": False,
        "schema_valid": False,
        "is_error": False,
        "has_raw_strings": False,
        "is_json_safe": True,
        "missing_trace_keys": False,
        "s2_updates": {},
        "error_details": None,
    }

    try:
        # 1. Build plan
        builder = _PLAN_BUILDERS.get(plan_builder_name, plan_1_1)
        subgoals, segments = builder()

        # 2. Build prompt request (first subgoal, first segment)
        agent_state = _FakeAgentState(cycle=0, is_complete=False)
        subgoal_state = _FakeSubgoalState(index=0, state="active")
        segment_state = _FakeSegmentState(index=0, state="running")
        memory = _make_fake_memory()

        request = build_prompt_request(
            agent_state=agent_state,
            subgoal_state=subgoal_state,
            segment_state=segment_state,
            memory=memory,
        )

        # 3. Validate request
        if not validate_prompt_request(request):
            run_result["is_error"] = True
            run_result["error_details"] = {"type": "invalid_request", "message": "PromptRequest schema invalid"}
            return run_result

        # 4. Call S1 backend
        if scenario.backend == "real_llm":
            s1_real_client.ENABLE_REAL_LLM = True

        response = call_s1_backend(request, backend=scenario.backend)

        # 5. Check for S1Error
        if isinstance(response, S1Error):
            run_result["is_error"] = True
            run_result["error_details"] = response.to_dict()

            # Check if the error raw text is valid JSON anyway
            raw_text = response.details.get("raw_text", "")
            if raw_text:
                try:
                    json.loads(raw_text)
                    run_result["json_valid"] = True
                except (json.JSONDecodeError, TypeError):
                    pass
            return run_result

        # 6. Got PromptResponse — check JSON validity (always True if we got here)
        run_result["json_valid"] = True
        run_result["schema_valid"] = validate_prompt_response(response)

        # 7. Parse into S2 updates
        s2_updates = parse_prompt_response(response)
        run_result["s2_updates"] = s2_updates

        # 8. Invariant checks
        output_raw = s2_updates.get("output_raw", {})
        run_result["has_raw_strings"] = has_raw_strings(output_raw)
        run_result["is_json_safe"] = is_json_safe(output_raw)

        # Check for trace-like structure issues
        if not isinstance(s2_updates, dict):
            run_result["missing_trace_keys"] = True

    except Exception as exc:
        run_result["is_error"] = True
        run_result["error_details"] = {
            "type": "unhandled_exception",
            "message": str(exc),
            "exception_type": type(exc).__name__,
        }

    return run_result


# ──────────────────────────────────────────────────────────────────────────────
# Scenario runner
# ──────────────────────────────────────────────────────────────────────────────


def run_scenario(
    scenario: ConformanceScenario,
    thresholds: Thresholds | None = None,
    verbose: bool = False,
) -> ConformanceResult:
    """Execute a scenario N times and return aggregated results.

    Parameters
    ----------
    scenario : ConformanceScenario
        The scenario to execute.
    thresholds : Thresholds or None
        Optional thresholds to evaluate against. If provided, results are
        printed with pass/fail indicators.
    verbose : bool
        If True, print per-run details.

    Returns
    -------
    ConformanceResult
        Aggregated result across all repetitions.
    """
    run_results: List[Dict[str, Any]] = []

    if scenario.backend == "real_llm":
        print(f"\n{'='*60}")
        print(f"  Statistical Conformance: {scenario.name}")
        print(f"  Backend: {scenario.backend}  |  Repetitions: {scenario.repetitions}")
        print(f"  Plan: {scenario.plan_builder}  |  Cycles/run: {scenario.cycles}")
        print(f"{'='*60}\n")
        print("WARNING: Running against real LLM. This will consume tokens and cost money.")
        print("Press Ctrl+C within 3 seconds to abort...")
        try:
            time.sleep(3)
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)

    t_start = time.time()

    for i in range(scenario.repetitions):
        run_result = _execute_single_run(scenario, run_index=i, plan_builder_name=scenario.plan_builder)
        run_results.append(run_result)

        if verbose:
            status = "✓" if not run_result["is_error"] else "✗"
            print(f"  [{i+1:3d}/{scenario.repetitions}] {status} json={run_result['json_valid']} schema={run_result['schema_valid']} error={run_result['is_error']}")

    elapsed = time.time() - t_start

    # Aggregate
    result = aggregate(
        run_results,
        scenario_name=scenario.name,
        backend=scenario.backend,
    )

    # Print summary
    print(f"\n{'─'*60}")
    print(f"  RESULTS: {scenario.name}")
    print(f"{'─'*60}")
    for key, val in result.summary.items():
        print(f"  {key:<30} {val}")
    print(f"  {'elapsed_sec':<30} {elapsed:.1f}")

    # Evaluate thresholds if provided
    if thresholds is not None:
        passed, failures = evaluate(result, thresholds)
        print(f"\n{'─'*60}")
        print(f"  THRESHOLD EVALUATION: {'✓ PASSED' if passed else '✗ FAILED'}")
        print(f"{'─'*60}")
        print(f"  min_json_validity         >= {thresholds.min_json_validity:.0%}  → {result.json_validity_rate:.2%} {'✓' if result.json_validity_rate >= thresholds.min_json_validity else '✗'}")
        print(f"  min_schema_validity      >= {thresholds.min_schema_validity:.0%}   → {result.schema_validity_rate:.2%} {'✓' if result.schema_validity_rate >= thresholds.min_schema_validity else '✗'}")
        print(f"  max_catastrophic_failures <= {thresholds.max_catastrophic_failures}    → {result.catastrophic_failures} {'✓' if result.catastrophic_failures <= thresholds.max_catastrophic_failures else '✗'}")
        print(f"  max_invariant_violations  <= {thresholds.max_invariant_violations}   → {result.total_invariant_violations} {'✓' if result.total_invariant_violations <= thresholds.max_invariant_violations else '✗'}")
        print(f"  min_trace_stability      >= {thresholds.min_trace_stability:.0%}  → {result.mean_trace_stability:.2%} {'✓' if result.mean_trace_stability >= thresholds.min_trace_stability else '✗'}")
        if failures:
            print(f"\n  FAILURES:")
            for f in failures:
                print(f"    - {f}")
        print()

    return result
