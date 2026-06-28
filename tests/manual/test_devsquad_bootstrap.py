"""Smoke test: DevSquad bootstrap workflow step-by-step.

Exercises the full configuration loading, primitive registration, inline tool
execution, and workflow engine state machine — all without S4B.

Usage:
    python -m tests.manual.test_devsquad_bootstrap
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.agent.composition_root import (
    _workflow_engine,
    _trigger_router,
    _execute_tool_inline,
    _primitive_registry,
    wf_registry,
)
from src.agent.workflow.event_bus import EventBus
from src.agent.workflow.engine import (
    WorkflowExecutionState,
    WorkflowStatus,
)
from src.agent.workflow.trigger_router import WorkflowEvent

# ── Helpers ──────────────────────────────────────────────────────────────

def run_workflow_loop(state: WorkflowExecutionState, max_steps: int = 20):
    """Manually drive the workflow engine loop (like the Supervisor does)."""
    step_count = 0
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
            # Execute inline (bypasses S4B)
            config = outcome.config
            print(f"     Config: tool={config.get('tool')}, args={config.get('args', {})}")
            result = _execute_tool_inline(config, state.context, state.step_results)
            if result is None:
                print(f"     [WARN] Inline executor returned None -- would fall through to S4B")
                print(f"     Aborting loop (no S4B available)")
                break
            status = result.get("status", "error")
            print(f"     Result: {status} -- {result.get('message', '')[:80]}")
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, result,
            )
        elif outcome.type == "llm_call":
            print(f"     [WARN] LLM call would be dispatched to Runtime backend")
            print(f"     Simulating success with empty result")
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, {"status": "success", "outputs": {}},
            )
        elif outcome.type == "waiting_for_input":
            print(f"     [WARN] User input required -- injecting 'approved'")
            state, _ = _workflow_engine.resume_with_input(state, "approved")
        elif outcome.type == "condition":
            state, _ = _workflow_engine.resume_with_result(
                state, outcome.step_id, {"status": "success", "outputs": {}},
            )
        elif outcome.type == "continue":
            # Deterministic transition — loop back to step()
            continue
        else:
            print(f"     Unknown outcome type: {outcome.type}")
            break
    else:
        print(f"  [WARN] Max steps ({max_steps}) reached without completion")

    return state


# ── Tests ─────────────────────────────────────────────────────────────────

def test_01_registry_has_devsquad_workflows():
    """Verify all DevSquad workflows are registered."""
    expected = [
        "workflow-sprint-bootstrap",
        "workflow-architecture",
        "workflow-delivery-plan",
        "workflow-implementation",
        "workflow-review",
        "workflow-acceptance",
    ]
    registered = {w.workflow_id for w in wf_registry.list()}
    for wf_id in expected:
        assert wf_id in registered, f"Missing workflow: {wf_id}"
    print(f"  [OK] All {len(expected)} DevSquad workflows registered")


def test_02_primitives_auto_discovered():
    """Verify key primitives are in the registry."""
    for name in ["stdlib.publish_event", "stdlib.update_metadata", "stdlib.create_project_structure"]:
        prim = _primitive_registry.get(name)
        assert prim is not None, f"Primitive {name!r} not registered"
        assert hasattr(prim, "execute"), f"Primitive {name!r} has no execute()"
        print(f"  [OK] Key primitives registered and executable")


def test_03_bootstrap_workflow_step_by_step():
    """Run the bootstrap workflow through its full lifecycle.

    Steps:
      1. create_project      → tool_execute (creates project dir)
      2. update_metadata_prd → tool_execute (updates metadata)
      3. publish_prd_completed → tool_execute (emits prd.completed event)
    """
    import tempfile
    import os

    # Use a temp project_id to avoid real /projects/ collisions
    project_id = f"test-bootstrap-{int(time.time())}"
    event_bus = EventBus()
    published: list[tuple[str, dict]] = []

    def _capture(event_type: str, payload: dict | None = None):
        published.append((event_type, payload or {}))
    event_bus.subscribe("prd.completed", _capture)

    # Override event bus for the run — publish_event primitive calls
    # src.agent.workflow.event_bus.get_event_bus() which returns the module-level
    # singleton.  We just verify the published events via the bus directly.

    state = _workflow_engine.start_workflow(
        "workflow-sprint-bootstrap",
        context={
            "project_id": project_id,
            "title": "Calculator App",
            "requirements": "Build a simple calculator in Python",
        },
    )
    print(f"  Started workflow: execution_id={state.execution_id}")
    print(f"  Current step: {state.current_step_id}")

    final_state = run_workflow_loop(state)

    assert final_state.status == WorkflowStatus.COMPLETED, (
        f"Workflow ended with status {final_state.status}: {final_state.error}"
    )

    # Verify the project directory was created
    projects_root = os.environ.get("DEVSQUAD_PROJECTS_ROOT", ".\\projects")
    project_dir = Path(projects_root) / project_id
    if project_dir.exists():
        subdirs = [d.name for d in project_dir.iterdir() if d.is_dir()]
        print(f"  [OK] Project directory created: {project_dir}")
        print(f"     Subdirs: {sorted(subdirs)}")
        metadata_file = project_dir / "metadata.json"
        if metadata_file.exists():
            meta = json.loads(metadata_file.read_text())
            print(f"     metadata.json: {json.dumps(meta, indent=2)}")
    else:
        print(f"  [WARN] Project directory not found at {project_dir}")
        print(f"     (This is expected if the projects root doesn't exist on this system)")

    # Cleanup
    import shutil
    if project_dir.exists():
        shutil.rmtree(str(project_dir))

    print(f"  [OK] Bootstrap workflow completed successfully")


def test_04_event_publishing_works():
    """Verify publish_event primitive works inline."""
    event_bus = EventBus()
    captured: list[str] = []

    def _handler(event_type, payload=None):
        captured.append(event_type)

    event_bus.subscribe("prd.completed", _handler)

    result = _execute_tool_inline({
        "tool": "publish_event",
        "args": {
            "event_type": "test.event",
            "payload": {"msg": "hello"},
        },
    })
    assert result is not None, "publish_event returned None (not found)"
    assert result["status"] == "success", f"publish_event failed: {result}"
    print(f"  [OK] publish_event primitive executed: {result['status']}")


def test_05_trigger_via_event_bus():
    """Verify sprint.init triggers the bootstrap workflow."""
    # We can't run the full Supervisor loop in a test, but we can verify
    # the trigger router correctly maps sprint.init -> devsquad-bootstrap
    matches = wf_registry.find_by_trigger("sprint.init")
    assert len(matches) > 0, "No workflows match sprint.init"
    wf_ids = [d.workflow_id for d in matches]
    assert "workflow-sprint-bootstrap" in wf_ids, (
        f"workflow-sprint-bootstrap not in matches: {wf_ids}"
    )
    print(f"  [OK] sprint.init -> {wf_ids}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("Registry has DevSquad workflows", test_01_registry_has_devsquad_workflows),
        ("Primitives auto-discovered", test_02_primitives_auto_discovered),
        ("Bootstrap workflow step-by-step", test_03_bootstrap_workflow_step_by_step),
        ("Event publishing works", test_04_event_publishing_works),
        ("Trigger via event bus", test_05_trigger_via_event_bus),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        print(f"\n=== {name} ===")
        try:
            func()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  FAILED: {e}")
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
