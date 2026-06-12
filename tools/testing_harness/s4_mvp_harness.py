"""
S4 MVP Test Harness
===================

Standalone CLI tool that exercises the Stratum-4 Phase 4.1 Minimal Execution
Path — Gateway, Normalization, Job, Queue, Worker, Adapter, Job Store, and
Logging — through scenario-driven integration checks.

Scenarios cover each component in isolation plus the full end-to-end pipeline.

Usage::

    python -m tools.testing_harness.s4_mvp_harness          # run all scenarios
    python -m tools.testing_harness.s4_mvp_harness --name end_to_end
    python -m tools.testing_harness.s4_mvp_harness --json
    python -m tools.testing_harness.s4_mvp_harness --list
"""

from __future__ import annotations

import json
import sys
import time
import io
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.platform.transport.normalization import (
    ChannelMessage,
    cli_to_channel_message,
    gateway_to_channel_message,
)
from src.platform.runtime.job import Job, create_job
from src.platform.queue.queue import InMemoryQueue
from src.platform.runtime.worker import Worker
from src.platform.runtime.job_store import JobStore
from src.platform.adapter.adapter import s2_to_s1_adapter, s1_to_s2_adapter
from src.platform.observability.logging import (
    log_job_created,
    log_job_started,
    log_job_finished,
)

# ---- Helpers ---------------------------------------------------------------


def _raises_value_error(fn: Any, *args: Any, **kwargs: Any) -> bool:
    """Return ``True`` if calling ``fn(*args, **kwargs)`` raises ``ValueError``."""
    try:
        fn(*args, **kwargs)
        return False
    except ValueError:
        return True


# ---- Scenario registry ---------------------------------------------------

SCENARIOS: list[dict[str, Any]] = []


def _scenario(name: str, description: str) -> Any:
    """Decorator that registers a scenario function."""
    def decorator(fn: Any) -> Any:
        SCENARIOS.append({
            "name": name,
            "description": description,
            "fn": fn,
            "tags": ["s4", "mvp"],
        })
        return fn
    return decorator


# ---- Scenarios ------------------------------------------------------------


@_scenario("normalization", "ChannelMessage creation and converter functions")
def _test_normalization() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # ChannelMessage with explicit fields
    msg = ChannelMessage(input={"key": "val"}, metadata={"trace": "abc"}, channel="http")
    checks.append({
        "check": "explicit fields",
        "passed": msg.input == {"key": "val"}
                  and msg.metadata == {"trace": "abc"}
                  and msg.channel == "http",
    })

    # ChannelMessage defaults
    msg2 = ChannelMessage(input={"x": 1})
    checks.append({
        "check": "default channel / metadata",
        "passed": msg2.metadata == {} and msg2.channel == "cli",
    })

    # ChannelMessage validation — non-dict input
    try:
        ChannelMessage(input="not_a_dict")  # type: ignore
        checks.append({"check": "rejects non-dict input", "passed": False})
    except ValidationError:
        checks.append({"check": "rejects non-dict input", "passed": True})

    # cli_to_channel_message
    cli_msg = cli_to_channel_message({"cmd": "deploy"})
    checks.append({
        "check": "cli converter",
        "passed": cli_msg.input == {"cmd": "deploy"}
                  and cli_msg.metadata == {}
                  and cli_msg.channel == "cli",
    })

    # gateway_to_channel_message
    gw_msg = gateway_to_channel_message({"action": "run"})
    checks.append({
        "check": "gateway converter",
        "passed": gw_msg.input == {"action": "run"}
                  and gw_msg.metadata == {"source": "gateway"}
                  and gw_msg.channel == "cli",
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("job_creation", "Job model and create_job() factory")
def _test_job_creation() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    ch = ChannelMessage(input={"hello": "world"})
    job = create_job(ch)

    checks.append({"check": "job_id is UUID4 string", "passed": len(job.job_id) == 36})
    checks.append({"check": "created_at is UTC", "passed": job.created_at.tzinfo is not None})
    checks.append({"check": "state defaults to pending", "passed": job.state == "pending"})
    checks.append({"check": "payload is the ChannelMessage", "passed": job.payload is ch})
    checks.append({"check": "result is None", "passed": job.result is None})

    # Job with explicit fields (Pydantic)
    job2 = Job(payload=ch)
    checks.append({
        "check": "Job default factory generates id+timestamp",
        "passed": len(job2.job_id) == 36 and job2.created_at.tzinfo is not None,
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("state_machine", "JobState enum valid and invalid transitions")
def _test_state_machine() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.job_state import (
        JobState,
        can_transition,
        transition,
    )

    # --- Valid transitions ---
    checks.append({
        "check": "PENDING → RUNNING allowed",
        "passed": can_transition(JobState.PENDING, JobState.RUNNING),
    })
    checks.append({
        "check": "RUNNING → SUCCEEDED allowed",
        "passed": can_transition(JobState.RUNNING, JobState.SUCCEEDED),
    })
    checks.append({
        "check": "RUNNING → FAILED allowed",
        "passed": can_transition(JobState.RUNNING, JobState.FAILED),
    })
    checks.append({
        "check": "transition() returns target",
        "passed": transition(JobState.PENDING, JobState.RUNNING) is JobState.RUNNING,
    })

    # --- Invalid transitions ---
    invalid_pairs = [
        (JobState.PENDING, JobState.SUCCEEDED),
        (JobState.PENDING, JobState.FAILED),
        (JobState.SUCCEEDED, JobState.RUNNING),
        (JobState.SUCCEEDED, JobState.FAILED),
        (JobState.FAILED, JobState.PENDING),
        (JobState.FAILED, JobState.RUNNING),
        (JobState.FAILED, JobState.SUCCEEDED),
    ]
    for cur, tgt in invalid_pairs:
        key = f"invalid: {cur.value} → {tgt.value}"
        checks.append({
            "check": f"{cur.value} → {tgt.value} raises ValueError",
            "passed": _raises_value_error(transition, cur, tgt),
        })

    # --- str comparison ---
    checks.append({
        "check": "JobState.PENDING == 'pending' (str compat)",
        "passed": JobState.PENDING == "pending",
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("control_plane", "ControlPlane lifecycle: register → running → succeeded/failed")
def _test_control_plane() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.job_state import JobState
    from src.platform.runtime.job_store import JobStore
    from src.platform.transport.normalization import ChannelMessage

    store = JobStore()
    cp = ControlPlane(job_store=store)
    ch = ChannelMessage(input={"x": 1})
    job = create_job(ch)

    # register_job
    cp.register_job(job)
    checks.append({"check": "register_job saves to store", "passed": store.get(job.job_id) is job})
    checks.append({"check": "job still PENDING after register", "passed": job.state is JobState.PENDING})

    # mark_running
    cp.mark_running(job)
    checks.append({"check": "mark_running → RUNNING", "passed": job.state is JobState.RUNNING})
    checks.append({"check": "store updated after mark_running", "passed": store.get(job.job_id).state is JobState.RUNNING})

    # Registering a job that's already RUNNING must raise
    checks.append({
        "check": "register non-PENDING raises ValueError",
        "passed": _raises_value_error(cp.register_job, job),
    })

    # mark_succeeded
    cp.mark_succeeded(job, {"status": "ok"})
    checks.append({"check": "mark_succeeded → SUCCEEDED", "passed": job.state is JobState.SUCCEEDED})
    checks.append({"check": "result stored", "passed": job.result == {"status": "ok"}})
    checks.append({"check": "store has result", "passed": store.get(job.job_id).result == {"status": "ok"}})

    # mark_failed (on a fresh PENDING job)
    job2 = create_job(ch)
    cp.register_job(job2)
    cp.mark_running(job2)
    cp.mark_failed(job2, {"error_type": "ValueError", "message": "something went wrong"})
    checks.append({"check": "mark_failed → FAILED", "passed": job2.state is JobState.FAILED})
    checks.append({"check": "error stored in result", "passed": job2.result == {"error_type": "ValueError", "message": "something went wrong"}})

    # Illegal direct transitions rejected
    checks.append({
        "check": "mark_succeeded on FAILED raises ValueError",
        "passed": _raises_value_error(cp.mark_succeeded, job2, {}),
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("worker_failure", "Worker.process_next() sets FAILED on exception")
def _test_worker_failure() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from unittest.mock import patch
    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job_state import JobState
    from src.platform.queue.queue import InMemoryQueue
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.worker import Worker
    from src.platform.transport.normalization import ChannelMessage

    q = InMemoryQueue()
    cp = ControlPlane()
    ch = ChannelMessage(input={})
    job = create_job(ch)
    q.push(job)

    with patch("src.platform.runtime.worker._mock_execute", side_effect=RuntimeError("boom")):
        w = Worker(queue=q, control_plane=cp)
        result = w.process_next()

    checks.append({"check": "worker returns job after failure", "passed": result is job})
    checks.append({"check": "state is FAILED", "passed": result is not None and result.state == JobState.FAILED})
    checks.append({"check": "result has error_type", "passed": result is not None and result.result.get("error_type") == "RuntimeError"})
    checks.append({"check": "result has message", "passed": result is not None and result.result.get("message") == "boom"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("queue_fifo", "InMemoryQueue push/pop/len FIFO semantics")
def _test_queue_fifo() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    q = InMemoryQueue()
    ch = ChannelMessage(input={"n": 0})
    j1 = Job(payload=ch)
    j2 = Job(payload=ch)
    j3 = Job(payload=ch)

    # Empty queue
    checks.append({"check": "empty queue len is 0", "passed": len(q) == 0})
    checks.append({"check": "pop from empty returns None", "passed": q.pop() is None})

    # Push
    q.push(j1)
    q.push(j2)
    q.push(j3)
    checks.append({"check": "len after 3 pushes", "passed": len(q) == 3})

    # FIFO order
    first = q.pop()
    second = q.pop()
    checks.append({"check": "FIFO j1 first", "passed": first is j1})
    checks.append({"check": "FIFO j2 second", "passed": second is j2})
    checks.append({"check": "one remaining", "passed": len(q) == 1})

    last = q.pop()
    checks.append({"check": "FIFO j3 third", "passed": last is j3})
    checks.append({"check": "queue empty after draining", "passed": len(q) == 0})

    # push() returns job_id
    jid = q.push(Job(payload=ch))
    checks.append({"check": "push returns job_id", "passed": jid == q.pop().job_id})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("job_store", "JobStore save/get lifecycle")
def _test_job_store() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    store = JobStore()
    ch = ChannelMessage(input={"x": 1})
    job = create_job(ch)

    checks.append({"check": "get missing job returns None", "passed": store.get("nope") is None})

    store.save(job)
    checks.append({"check": "get saved job returns it", "passed": store.get(job.job_id) is job})
    checks.append({"check": "len after save", "passed": len(store) == 1})

    # Overwrite
    job.result = {"done": True}
    store.save(job)
    checks.append({"check": "overwrite preserves single entry", "passed": len(store) == 1})
    got = store.get(job.job_id)
    checks.append({"check": "overwritten result visible", "passed": got is not None and got.result == {"done": True}})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("worker_empty", "Worker.process_next() with empty queue → None")
def _test_worker_empty() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.control_plane import ControlPlane

    q = InMemoryQueue()
    cp = ControlPlane()
    w = Worker(queue=q, control_plane=cp)

    result = w.process_next()
    checks.append({"check": "process_next on empty queue returns None", "passed": result is None})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("worker_execute", "Worker.process_next() executes payload stub")
def _test_worker_execute() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.control_plane import ControlPlane

    q = InMemoryQueue()
    cp = ControlPlane()
    w = Worker(queue=q, control_plane=cp)
    ch = ChannelMessage(input={"ping": "pong"})
    job = create_job(ch)
    q.push(job)

    result = w.process_next()
    checks.append({"check": "process_next returns job", "passed": result is job})
    checks.append({"check": "result is set", "passed": result is not None and result.result is not None})
    if result and result.result:
        checks.append({"check": "result type is s2_result", "passed": result.result.get("type") == "s2_result"})
        checks.append({"check": "result echoes input", "passed": result.result.get("output", {}).get("echo") == {"ping": "pong"}})
    checks.append({"check": "state is succeeded", "passed": result is not None and result.state == "succeeded"})
    checks.append({"check": "queue drained", "passed": len(q) == 0})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("adapter", "S1/S2/S3 adapter boundary functions")
def _test_adapter() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    ch = ChannelMessage(input={"query": "test"}, metadata={"source": "cli"}, channel="cli")
    s1_req = s2_to_s1_adapter(ch)
    checks.append({"check": "s2_to_s1_adapter returns dict", "passed": isinstance(s1_req, dict)})
    checks.append({"check": "s2_to_s1_adapter type", "passed": s1_req.get("type") == "s1_request"})
    checks.append({"check": "s2_to_s1_adapter preserves input", "passed": s1_req.get("input") == {"query": "test"}})
    checks.append({"check": "s2_to_s1_adapter preserves metadata", "passed": s1_req.get("metadata") == {"source": "cli"}})

    s2_result = s1_to_s2_adapter({"raw": "output"})
    checks.append({"check": "s1_to_s2_adapter returns dict", "passed": isinstance(s2_result, dict)})
    checks.append({"check": "s1_to_s2_adapter type", "passed": s2_result.get("type") == "s2_result"})
    checks.append({"check": "s1_to_s2_adapter wraps output", "passed": s2_result.get("output") == {"raw": "output"}})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("logging", "Lifecycle log functions emit correct format")
def _test_logging() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = buf = io.StringIO()

    try:
        ch = ChannelMessage(input={"x": 1})
        job = create_job(ch)

        log_job_created(job)
        log_job_started(job)
        log_job_finished(job)

        output = buf.getvalue()
        lines = [l for l in output.split("\n") if l.strip()]

        checks.append({"check": "3 log lines emitted", "passed": len(lines) == 3})
        checks.append({
            "check": "first line is job_created",
            "passed": len(lines) > 0 and "job_created" in lines[0] and job.job_id in lines[0],
        })
        checks.append({
            "check": "second line is job_started",
            "passed": len(lines) > 1 and "job_started" in lines[1] and job.job_id in lines[1],
        })
        checks.append({
            "check": "third line is job_finished",
            "passed": len(lines) > 2 and "job_finished" in lines[2] and job.job_id in lines[2],
        })
        checks.append({
            "check": "format includes [S4] prefix and ISO timestamp",
            "passed": len(lines) > 0 and "[S4]" in lines[0],
        })
    finally:
        sys.stdout = old_stdout

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("end_to_end", "Full pipeline: normalize → create → queue → work → store → retrieve")
def _test_end_to_end() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # 1. Normalize raw input
    raw = {"command": "deploy", "env": "staging"}
    ch = gateway_to_channel_message(raw)
    checks.append({"check": "normalization produces ChannelMessage", "passed": isinstance(ch, ChannelMessage)})
    checks.append({"check": "metadata marks gateway source", "passed": ch.metadata.get("source") == "gateway"})

    # 2. Create job
    job = create_job(ch)
    checks.append({"check": "create_job returns Job", "passed": isinstance(job, Job)})
    checks.append({"check": "job state is pending", "passed": job.state == "pending"})

    # 3. Save to store
    store = JobStore()
    store.save(job)
    checks.append({"check": "job saved to store", "passed": store.get(job.job_id) is job})

    # 4. Push to queue
    q = InMemoryQueue()
    jid = q.push(job)
    checks.append({"check": "push returns job_id", "passed": jid == job.job_id})
    checks.append({"check": "queue has 1 item", "passed": len(q) == 1})

    # 5. Worker processes it
    from src.platform.runtime.control_plane import ControlPlane

    cp = ControlPlane()
    w = Worker(queue=q, control_plane=cp)
    processed = w.process_next()
    checks.append({"check": "worker returns job", "passed": processed is job})
    checks.append({"check": "result is populated", "passed": processed is not None and processed.result is not None})

    if processed and processed.result:
        checks.append({"check": "result type is s2_result", "passed": processed.result.get("type") == "s2_result"})
        checks.append({"check": "result echoes original input", "passed": processed.result.get("output", {}).get("echo") == raw})
        notes.append(f"Echo payload: {processed.result.get('output', {}).get('echo')}")

    # 6. Queue is drained
    checks.append({"check": "queue empty after processing", "passed": len(q) == 0})

    # 7. Store still has the job
    retrieved = store.get(job.job_id)
    checks.append({"check": "job retrievable from store after processing", "passed": retrieved is job})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("gateway_post", "Gateway POST /run via TestClient")
def _test_gateway_post() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from fastapi.testclient import TestClient
    from src.platform.transport.app import app

    client = TestClient(app)

    # Valid payload
    resp = client.post("/run", json={"action": "test", "value": 42})
    checks.append({"check": "POST /run returns 200", "passed": resp.status_code == 200})
    data = resp.json()
    checks.append({"check": "response has job_id", "passed": "job_id" in data})
    checks.append({"check": "job_id is UUID format", "passed": len(data["job_id"]) == 36})
    notes.append(f"job_id: {data['job_id']}")

    # Non-dict payload — FastAPI rejects list via type hint before the handler
    resp2 = client.post("/run", json=[1, 2, 3])
    checks.append({"check": "non-dict payload returns 422/400", "passed": resp2.status_code in (422, 400)})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("gateway_get", "Gateway GET /jobs/{id} via TestClient")
def _test_gateway_get() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from fastapi.testclient import TestClient
    from src.platform.transport.app import app, job_queue
    from src.platform.transport.normalization import gateway_to_channel_message
    from src.platform.runtime import create_job
    from src.platform.runtime.job_store import job_store
    from src.platform.observability.logging import log_job_created

    # Drain any leftover jobs from previous shared-queue tests
    while job_queue.pop():
        pass

    client = TestClient(app)

    # Submit a job
    raw = {"say": "hello"}
    resp = client.post("/run", json=raw)
    jid = resp.json()["job_id"]

    # Retrieve it
    resp2 = client.get(f"/jobs/{jid}")
    checks.append({"check": "GET /jobs/{id} returns 200", "passed": resp2.status_code == 200})
    data = resp2.json()
    checks.append({"check": "response has job_id", "passed": data.get("job_id") == jid})
    checks.append({"check": "state is pending", "passed": data.get("state") == "pending"})
    checks.append({"check": "result is None initially", "passed": data.get("result") is None})

    # Process the job
    from src.platform.runtime.control_plane import control_plane
    from src.platform.runtime.worker import Worker
    w = Worker(queue=job_queue, control_plane=control_plane)
    w.process_next()

    # Retrieve updated state
    resp3 = client.get(f"/jobs/{jid}")
    data3 = resp3.json()
    checks.append({"check": "result populated after processing", "passed": data3.get("result") is not None})

    # Missing job
    resp4 = client.get("/jobs/missing-uuid")
    checks.append({"check": "missing job returns 404", "passed": resp4.status_code == 404})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


# ---- Runner ---------------------------------------------------------------


def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Execute one scenario and return the assessment."""
    start = time.perf_counter()
    result = scenario["fn"]()
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "scenario": scenario["name"],
        "description": scenario["description"],
        "tags": scenario.get("tags", []),
        "elapsed_ms": elapsed_ms,
        "assessment": result,
    }


def run_all(
    name_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Run all matching scenarios."""
    results: list[dict[str, Any]] = []
    for sc in SCENARIOS:
        if name_filter and sc["name"] != name_filter:
            continue
        results.append(run_scenario(sc))
    return results


def _assemble_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for r in results if r["assessment"]["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
    }


# ---- CLI ------------------------------------------------------------------


def _print_table(results: list[dict[str, Any]]) -> None:
    summary = _assemble_summary(results)

    print(f"\n{'=' * 72}")
    print(f"  S4 MVP Test Harness — {summary['passed']}/{summary['total']} scenarios passed")
    print(f"{'=' * 72}")
    print(f"  {'Scenario':<24} {'Status':<10} {'Time':<8} {'Checks':<8}")
    print(f"  {'-' * 24} {'-' * 10} {'-' * 8} {'-' * 8}")

    for r in results:
        a = r["assessment"]
        status = "PASS" if a["passed"] else "FAIL"
        n_checks = len(a.get("checks", []))
        n_failed = sum(1 for c in a.get("checks", []) if not c["passed"])
        checks_str = f"{n_checks - n_failed}/{n_checks}" if n_failed else f"{n_checks}/{n_checks}"
        elapsed = f"{r['elapsed_ms']}ms"
        name = r["scenario"]
        if len(name) > 22:
            name = name[:21] + "."
        print(f"  {name:<24} {status:<10} {elapsed:<8} {checks_str:<8}")

    print(f"{'-' * 72}")

    # Failures detail
    failures = [r for r in results if not r["assessment"]["passed"]]
    if failures:
        print(f"\n  Failures ({len(failures)}):")
        for f in failures:
            name = f["scenario"]
            failed_checks = [
                c for c in f["assessment"].get("checks", []) if not c["passed"]
            ]
            for fc in failed_checks:
                print(f"    x [{name}] {fc['check']}")
            for note in f["assessment"].get("notes", []):
                print(f"    ! [{name}] {note}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="S4 MVP Test Harness — scenario-driven Stratum-4 testing",
    )
    parser.add_argument(
        "--name", "-n",
        help="Run a single scenario by name",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output raw JSON instead of table",
    )
    parser.add_argument(
        "--list", "-l", action="store_true", dest="list_only",
        help="List available scenarios and exit",
    )

    args = parser.parse_args()

    if args.list_only:
        print(f"\n{'Scenario':<24} {'Description'}")
        print(f"{'-' * 24} {'-' * 48}")
        for sc in SCENARIOS:
            desc = sc["description"]
            if len(desc) > 46:
                desc = desc[:45] + "."
            print(f"  {sc['name']:<24} {desc}")
        print(f"\n{len(SCENARIOS)} scenarios total")
        return

    results = run_all(name_filter=args.name)

    if args.json:
        output = {
            "summary": _assemble_summary(results),
            "results": results,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    else:
        if not results:
            print("No scenarios matched the filter.")
            return
        _print_table(results)

        # Exit with error if any failures
        summary = _assemble_summary(results)
        if summary["failed"] > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
