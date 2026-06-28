"""End-to-end smoke test: runs all 6 DevSquad workflows in sequence.

Sets DEVSQUAD_PROJECTS_ROOT to a temp directory, starts with a ``sprint.init``
trigger, drives each workflow via the engine step loop, simulates LLM / user
input steps, and verifies the event chain completes.

Usage:
    python -m tests.manual.test_devsquad_e2e
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.agent.composition_root import (
    _execute_tool_inline,
    _primitive_registry,
    _render_template,
    _workflow_engine,
    wf_registry,
)
from src.agent.workflow.engine import (
    WorkflowExecutionState,
    WorkflowStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def run_workflow_loop(state: WorkflowExecutionState,
                      max_steps: int = 30,
                      simulate_llm_result: dict | None = None,
                      simulate_user_input: str | None = None,
                      ) -> WorkflowExecutionState:
    """Manually drive the workflow engine loop (like the Supervisor does).

    Parameters
    ----------
    simulate_llm_result:
        If set, returned as the result of every ``llm_call`` outcome.
        Default: ``{"status": "success", "outputs": {"answer": "simulated"}}``.
    simulate_user_input:
        If set, used as the user input for ``waiting_for_input`` outcomes.
        Default: ``{"decision": "approved", "feedback": ""}``.
    """
    step_count = 0
    llm_default = simulate_llm_result or {"status": "success", "outputs": {"answer": "simulated"}}
    input_default = simulate_user_input or '{"decision": "approved", "feedback": ""}'

    while step_count < max_steps:
        step_count += 1
        new_state, outcome = _workflow_engine.step(state)
        state = new_state

        print(f"  Step {step_count}: type={outcome.type}, step_id={outcome.step_id!r}")

        if outcome.type == "completed":
            print(f"  [OK] Workflow completed!")
            break
        elif outcome.type == "failed":
            print(f"  [FAIL] Workflow FAILED: {outcome.error}")
            break
        elif outcome.type == "tool_execute":
            config = outcome.config
            tool = config.get("tool") or config.get("tool", {}).get("name", "")
            args = config.get("args", {})
            # Render templates against state context + step results
            rendered = _render_template(config, state.context, state.step_results)
            result = _execute_tool_inline(rendered, state.context, state.step_results)
            if result is None:
                print(f"     [WARN] Inline executor returned None -- would fall through to S4B")
                print(f"     Aborting loop (no S4B available)")
                break
            status = result.get("status", "error")
            print(f"     Tool={tool} Result: {status} -- {result.get('message', '')[:100]}")
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, result,
            )
        elif outcome.type == "llm_call":
            print(f"     Simulating LLM call with default result")
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, llm_default,
            )
        elif outcome.type == "waiting_for_input":
            print(f"     Simulating user input: {input_default}")
            state, _ = _workflow_engine.resume_with_input(state, input_default, step_id=outcome.step_id)
        elif outcome.type == "condition":
            # Conditions are handled internally by the engine -- no resume needed
            continue
        elif outcome.type == "council_deliberate":
            print(f"     Simulating council deliberation with default result")
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, llm_default,
            )
        elif outcome.type == "continue":
            continue
        else:
            print(f"     Unknown outcome type: {outcome.type}")
            break
    else:
        print(f"  [WARN] Max steps ({max_steps}) reached without completion")

    return state


def capture_step_results(state: WorkflowExecutionState) -> dict:
    """Return a summary of step results from a finished workflow."""
    return dict(state.step_results)


# ── Tests ─────────────────────────────────────────────────────────────────

def test_e2e_all_workflows():
    """Run all 6 DevSquad workflows in sequence, connected by events."""
    # Use default /projects root (C:\projects on Windows) so the hardcoded
    # /projects/<id>/... paths in workflow YAMLs resolve correctly.
    project_root = Path("/projects")
    project_id = f"test-e2e-{int(time.time())}"
    project_dir = project_root / project_id

    # Track published events
    published: list[tuple[str, dict]] = []

    from src.agent.composition_root import get_event_bus
    bus = get_event_bus()

    def _capture(event):
        published.append((event.event_type, event.payload or {}))
        print(f"     [EVENT] {event.event_type} -- {event.payload}")
    bus.subscribe("prd.completed", _capture)
    bus.subscribe("solution.completed", _capture)
    bus.subscribe("delivery_plan.completed", _capture)
    bus.subscribe("implementation.completed", _capture)
    bus.subscribe("review.completed", _capture)
    bus.subscribe("sprint.completed", _capture)
    bus.subscribe("sprint.restart", _capture)
    bus.subscribe("sprint.rejected", _capture)
    bus.subscribe("task_block.completed", _capture)

    # Check event bus is emitting (clear any stale events)
    published.clear()

    # ── Workflow 1: Bootstrap ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("WORKFLOW 1: Bootstrap (sprint.init)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-sprint-bootstrap",
        context={
            "project_id": project_id,
            "title": "Calculator App",
            "requirement": "Build a simple calculator that supports +, -, *, /",
            "context": "Python CLI application",
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        simulate_llm_result={"status": "success", "outputs": {"answer": "# PRD\nCalculator app"}},
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Bootstrap ended {state.status}: {state.error}"
    )
    assert any(e[0] == "prd.completed" for e in published), (
        "prd.completed event not published"
    )
    print("  [PASS] Bootstrap completed\n")

    # ── Create artifact files for downstream workflows ───────────────
    # (the LLM simulation doesn't write them, so we do it manually)
    prd_path = str(project_dir / "prd.md")
    sol_path = str(project_dir / "solution.md")
    dp_path  = str(project_dir / "delivery_plan.json")
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(prd_path, "w") as f:
        f.write("# PRD\nCalculator app\n\nSupports +, -, *, /")
    with open(sol_path, "w") as f:
        f.write("# Solution\nCalculator CLI architecture\n\nPython, single file")
    with open(dp_path, "w") as f:
        f.write('{"blocks": [{"id": "b1", "desc": "implement add"}]}')
    print("     Created artifact files for downstream workflows")

    # ── Workflow 2: Architecture ───────────────────────────────────────
    prd_payload = published[-1][1]
    print("=" * 60)
    print("WORKFLOW 2: Architecture (prd.completed)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-architecture",
        context={
            "project_id": project_id,
            "artifact_path": prd_path,
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        simulate_llm_result={"status": "success", "outputs": {"answer": "# Solution\nCalculator CLI architecture"}},
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Architecture ended {state.status}: {state.error}"
    )
    assert any(e[0] == "solution.completed" for e in published), (
        "solution.completed event not published"
    )
    print("  [PASS] Architecture completed\n")

    # ── Workflow 3: Delivery Plan ──────────────────────────────────────
    solution_payload = [e for e in published if e[0] == "solution.completed"][-1][1]
    print("=" * 60)
    print("WORKFLOW 3: Delivery Plan (solution.completed)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-delivery-plan",
        context={
            "project_id": project_id,
            "artifact_path": solution_payload.get("artifact_path", ""),
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        simulate_llm_result={"status": "success", "outputs": {"answer": '{"blocks": [{"id": "b1", "desc": "implement add"}]}'}},
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Delivery Plan ended {state.status}: {state.error}"
    )
    assert any(e[0] == "delivery_plan.completed" for e in published), (
        "delivery_plan.completed event not published"
    )
    print("  [PASS] Delivery Plan completed\n")

    # ── Workflow 4: Implementation ─────────────────────────────────────
    dp_payload = [e for e in published if e[0] == "delivery_plan.completed"][-1][1]
    print("=" * 60)
    print("WORKFLOW 4: Implementation (delivery_plan.completed)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-implementation",
        context={
            "project_id": project_id,
            "artifact_path": dp_payload.get("artifact_path", ""),
            "remaining_blocks": [],
            "current_block": {},
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        simulate_llm_result={"status": "success", "outputs": {"answer": "def add(a,b): return a+b"}},
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Implementation ended {state.status}: {state.error}"
    )
    assert any(e[0] == "implementation.completed" for e in published), (
        "implementation.completed event not published"
    )
    print("  [PASS] Implementation completed\n")

    # ── Workflow 5: Review ─────────────────────────────────────────────
    impl_payload = [e for e in published if e[0] == "implementation.completed"][-1][1]
    print("=" * 60)
    print("WORKFLOW 5: Review (implementation.completed)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-review",
        context={
            "project_id": project_id,
            "artifact_path": impl_payload.get("artifact_path", ""),
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        # Simulate LLM for council_deliberate returns
        simulate_llm_result={"status": "success", "outputs": {"answer": "# Review\nCode looks good"}},
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Review ended {state.status}: {state.error}"
    )
    assert any(e[0] == "review.completed" for e in published), (
        "review.completed event not published"
    )
    print("  [PASS] Review completed\n")

    # ── Workflow 6: Acceptance ─────────────────────────────────────────
    review_payload = [e for e in published if e[0] == "review.completed"][-1][1]
    print("=" * 60)
    print("WORKFLOW 6: Acceptance (review.completed)")
    print("=" * 60)

    state = _workflow_engine.start_workflow(
        "workflow-acceptance",
        context={
            "project_id": project_id,
            "artifact_path": review_payload.get("artifact_path", ""),
        },
    )
    print(f"  Started: execution_id={state.execution_id}")
    state = run_workflow_loop(
        state,
        simulate_user_input='{"decision": "approved", "feedback": "Looks great!"}',
    )
    assert state.status == WorkflowStatus.COMPLETED, (
        f"Acceptance ended {state.status}: {state.error}"
    )
    assert any(e[0] == "sprint.completed" for e in published), (
        "sprint.completed event not published"
    )
    print("  [PASS] Acceptance completed\n")

    # ── Final Summary ──────────────────────────────────────────────────
    event_chain = [e[0] for e in published]
    print("=" * 60)
    print("EVENT CHAIN")
    print("=" * 60)
    for i, evt in enumerate(event_chain, 1):
        print(f"  {i}. {evt}")
    print()
    print(f"All 6 workflows completed successfully.")
    print(f"Project dir: {project_dir}")

    # Cleanup
    shutil.rmtree(str(project_dir), ignore_errors=True)

    return True


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("End-to-end DevSquad pipeline", test_e2e_all_workflows),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        print(f"\n=== {name} ===")
        try:
            func()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"  Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
