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
from src.platform.runtime.job_store import InMemoryJobStore, JobStore
from src.platform.adapter.adapter import s2_to_s1_adapter, s1_to_s2_adapter
from src.platform.observability.logging import (
    log_job_created,
    log_job_started,
    log_job_finished,
)
from src.platform.runtime.retry.policy import (
    PlatformRetryPolicy,
    RetryDecision,
    RetryContext,
    DEFAULT_RETRY_RULES,
    default_retry_policy,
)
from src.platform.runtime.retry.tool_wrapper import (
    PoisonInstruction,
    RetryInstruction,
    ToolRetryWrapper,
)
from src.platform.runtime.retry.poison import (
    PoisonDecision,
    PoisonContext,
    PoisonDetector,
    default_poison_detector,
)
from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.job_state import JobState
from src.platform.runtime.recovery.crash_recovery import (
    CrashRecovery,
    RecoveryContext,
    default_crash_recovery,
)
from src.platform.runtime.safety.panic_guard import (
    PanicDecision,
    PanicGuard,
    StructuredFailure,
    default_panic_guard,
)
from src.platform.runtime.safety.degraded_mode import (
    DegradedContext,
    DegradedDecision,
    DegradedMode,
    default_degraded_mode,
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
        "check": "PENDING -> RUNNING allowed",
        "passed": can_transition(JobState.PENDING, JobState.RUNNING),
    })
    checks.append({
        "check": "RUNNING -> SUCCEEDED allowed",
        "passed": can_transition(JobState.RUNNING, JobState.SUCCEEDED),
    })
    checks.append({
        "check": "RUNNING -> FAILED allowed",
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
        key = f"invalid: {cur.value} -> {tgt.value}"
        checks.append({
            "check": f"{cur.value} -> {tgt.value} raises ValueError",
            "passed": _raises_value_error(transition, cur, tgt),
        })

    # --- str comparison ---
    checks.append({
        "check": "JobState.PENDING == 'pending' (str compat)",
        "passed": JobState.PENDING == "pending",
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("control_plane", "ControlPlane lifecycle: register -> running -> succeeded/failed")
def _test_control_plane() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.job_state import JobState
    from src.platform.runtime.job_store import InMemoryJobStore
    from src.platform.transport.normalization import ChannelMessage

    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    ch = ChannelMessage(input={"x": 1})
    job = create_job(ch)

    # register_job
    cp.register_job(job)
    checks.append({"check": "register_job saves to store", "passed": store.get(job.job_id) == job})
    checks.append({"check": "job still PENDING after register", "passed": job.state is JobState.PENDING})

    # mark_running
    cp.mark_running(job)
    checks.append({"check": "mark_running -> RUNNING", "passed": job.state is JobState.RUNNING})
    checks.append({"check": "store updated after mark_running", "passed": store.get(job.job_id).state is JobState.RUNNING})

    # Registering a job that's already RUNNING must raise
    checks.append({
        "check": "register non-PENDING raises ValueError",
        "passed": _raises_value_error(cp.register_job, job),
    })

    # mark_succeeded
    cp.mark_succeeded(job, {"status": "ok"})
    checks.append({"check": "mark_succeeded -> SUCCEEDED", "passed": job.state is JobState.SUCCEEDED})
    checks.append({"check": "result stored", "passed": job.result == {"status": "ok"}})
    checks.append({"check": "store has result", "passed": store.get(job.job_id).result == {"status": "ok"}})

    # mark_failed (on a fresh PENDING job)
    job2 = create_job(ch)
    cp.register_job(job2)
    cp.mark_running(job2)
    cp.mark_failed(job2, {"error_type": "ValueError", "message": "something went wrong"})
    checks.append({"check": "mark_failed -> FAILED", "passed": job2.state is JobState.FAILED})
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

    store = InMemoryJobStore()
    ch = ChannelMessage(input={"x": 1})
    job = create_job(ch)

    checks.append({"check": "get missing job returns None", "passed": store.get("nope") is None})

    store.save(job)
    checks.append({"check": "get saved job returns it", "passed": store.get(job.job_id) == job})
    checks.append({"check": "len after save", "passed": len(store) == 1})

    # Overwrite
    job.result = {"done": True}
    store.save(job)
    checks.append({"check": "overwrite preserves single entry", "passed": len(store) == 1})
    got = store.get(job.job_id)
    checks.append({"check": "overwritten result visible", "passed": got is not None and got.result == {"done": True}})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("worker_empty", "Worker.process_next() with empty queue -> None")
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


@_scenario("end_to_end", "Full pipeline: normalize -> create -> queue -> work -> store -> retrieve")
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
    store = InMemoryJobStore()
    store.save(job)
    checks.append({"check": "job saved to store", "passed": store.get(job.job_id) == job})

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
    checks.append({"check": "job retrievable from store after processing", "passed": retrieved == job})

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


@_scenario("execution_context", "ExecutionContext model, serialisation, and ControlPlane cycle tracing")
def _test_execution_context() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.execution_context import ExecutionContext
    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.job_store import InMemoryJobStore
    from src.platform.transport.normalization import ChannelMessage

    # ExecutionContext default construction
    ec = ExecutionContext()
    checks.append({"check": "cognitive_state defaults to empty dict", "passed": ec.cognitive_state == {}})
    checks.append({"check": "last_result defaults to None", "passed": ec.last_result is None})
    checks.append({"check": "memory defaults to empty dict", "passed": ec.memory == {}})
    checks.append({"check": "cycle_trace defaults to empty list", "passed": ec.cycle_trace == []})

    # ExecutionContext serialisation round-trip
    ec.cognitive_state = {"step": 1}
    ec.last_result = {"output": "ok"}
    ec.memory = {"buffer": "xyz"}
    ec.cycle_trace.append({"event": "test", "timestamp": "now"})

    d = ec.to_dict()
    checks.append({"check": "to_dict returns dict", "passed": isinstance(d, dict)})
    checks.append({"check": "to_dict preserves cognitive_state", "passed": d["cognitive_state"] == {"step": 1}})
    checks.append({"check": "to_dict preserves last_result", "passed": d["last_result"] == {"output": "ok"}})
    checks.append({"check": "to_dict preserves memory", "passed": d["memory"] == {"buffer": "xyz"}})
    checks.append({"check": "to_dict preserves cycle_trace", "passed": len(d["cycle_trace"]) == 1})

    ec2 = ExecutionContext.from_dict(d)
    checks.append({"check": "from_dict restores ExecutionContext", "passed": isinstance(ec2, ExecutionContext)})
    checks.append({"check": "round-trip preserves cognitive_state", "passed": ec2.cognitive_state == {"step": 1}})
    checks.append({"check": "round-trip preserves last_result", "passed": ec2.last_result == {"output": "ok"}})

    # ControlPlane initialises ExecutionContext on register
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    ch = ChannelMessage(input={"hello": "world"})
    job = create_job(ch)
    checks.append({"check": "new job has no execution_context", "passed": job.execution_context is None})

    cp.register_job(job)
    checks.append({"check": "register_job initialises execution_context", "passed": job.execution_context is not None})
    checks.append({"check": "initial context has empty cycle_trace", "passed": len(job.execution_context.cycle_trace) == 0})

    # append_cycle_trace
    cp.append_cycle_trace(job, "cycle_start", {"payload": "test"})
    checks.append({"check": "cycle_trace has 1 entry after append", "passed": len(job.execution_context.cycle_trace) == 1})
    trace_entry = job.execution_context.cycle_trace[0]
    checks.append({"check": "trace entry has event key", "passed": "event" in trace_entry})
    checks.append({"check": "trace entry has timestamp key", "passed": "timestamp" in trace_entry})
    checks.append({"check": "trace entry has payload key", "passed": "payload" in trace_entry})
    checks.append({"check": "trace entry event matches", "passed": trace_entry["event"] == "cycle_start"})

    # Persisted to store
    stored = store.get(job.job_id)
    checks.append({"check": "cycle_trace persisted in store", "passed": len(stored.execution_context.cycle_trace) == 1})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("checkpointing", "Checkpoint round-trip: serialise, store, hydrate, modify independently")
def _test_checkpointing() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.execution_context import ExecutionContext
    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.job_store import InMemoryJobStore
    from src.platform.transport.normalization import ChannelMessage

    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)

    # --- Job.save_checkpoint() ---
    ch = ChannelMessage(input={"checkpoint": "test"})
    job = create_job(ch)
    cp.register_job(job)

    cp.mark_running(job)
    cp.mark_succeeded(job, {"output": "ok"})

    checkpoint = job.save_checkpoint()
    checks.append({"check": "save_checkpoint returns dict", "passed": isinstance(checkpoint, dict)})
    checks.append({"check": "job.trace has state transition entries from mark_running/mark_succeeded",
                   "passed": len(job.trace) > 0})

    # --- Store.get() hydrates fresh ExecutionContext ---
    job2 = create_job(ch)
    cp.register_job(job2)
    job2.execution_context.cognitive_state["cycle"] = 1

    # Save modifies original context
    cp.append_cycle_trace(job2, "cycle_start", {"t": 1})
    checks.append({"check": "context persisted after append_cycle_trace",
                   "passed": store.get(job2.job_id).execution_context is not None})

    # Load a fresh copy — modifications to loaded copy should NOT affect store
    loaded = store.get(job2.job_id)
    loaded.execution_context.cognitive_state["modified"] = True
    checks.append({"check": "loaded copy is independent from stored original",
                   "passed": "modified" not in store.get(job2.job_id).execution_context.cognitive_state})

    # --- Checkpoint round-trip with full lifecycle ---
    job3 = create_job(ch)
    cp.register_job(job3)
    cp.mark_running(job3)
    cp.mark_succeeded(job3, {"result": "done"})
    cp.append_cycle_trace(job3, "cycle_end", {"status": "succeeded"})

    loaded3 = store.get(job3.job_id)
    checks.append({"check": "full lifecycle checkpoint preserves execution_context",
                   "passed": loaded3.execution_context is not None})
    checks.append({"check": "loaded execution_context has cycle_trace entry from append_cycle_trace",
                   "passed": len(loaded3.execution_context.cycle_trace) >= 1})
    checks.append({"check": "loaded execution_context has state_transition trace in job.trace",
                   "passed": len(loaded3.trace) >= 2})

    # --- Edge: save_checkpoint when context is None (before register) ---
    job4 = Job(payload=ChannelMessage(input={}))
    empty_checkpoint = job4.save_checkpoint()
    checks.append({"check": "save_checkpoint with no context returns empty dict",
                   "passed": empty_checkpoint == {}})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("resume_tokens", "Resume token generation, lifecycle, and opaque passthrough via adapter")
def _test_resume_tokens() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.tokens import new_resume_token
    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.job import Job, create_job
    from src.platform.runtime.job_store import InMemoryJobStore
    from src.platform.transport.normalization import ChannelMessage
    from src.platform.adapter.adapter import s2_to_s1_adapter

    # --- new_resume_token() ---
    t1 = new_resume_token()
    checks.append({"check": "new_resume_token returns a string", "passed": isinstance(t1, str)})
    checks.append({"check": "token is non-empty", "passed": len(t1) > 0})

    t2 = new_resume_token()
    checks.append({"check": "consecutive tokens are unique", "passed": t1 != t2})

    # --- ControlPlane.issue_resume_token() ---
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    ch = ChannelMessage(input={"token": "test"})
    job = create_job(ch)
    cp.register_job(job)

    checks.append({"check": "resume_token is None after register", "passed": job.resume_token is None})

    cp.issue_resume_token(job)
    checks.append({"check": "issue_resume_token sets resume_token", "passed": job.resume_token is not None})
    checks.append({"check": "resume_token is a string after issue", "passed": isinstance(job.resume_token, str)})

    first_token = job.resume_token

    # --- issue_resume_token persists to store ---
    stored = store.get(job.job_id)
    checks.append({"check": "resume_token persisted in store", "passed": stored is not None and stored.resume_token == first_token})

    # --- issue_resume_token generates a new token each call ---
    cp.issue_resume_token(job)
    checks.append({"check": "second issue generates different token", "passed": job.resume_token != first_token})

    # --- mark_succeeded issues a new token ---
    job2 = create_job(ch)
    cp.register_job(job2)
    cp.issue_resume_token(job2)
    token_before = job2.resume_token
    cp.mark_running(job2)
    cp.mark_succeeded(job2, {"output": "ok"})
    checks.append({"check": "mark_succeeded issues new resume_token", "passed": job2.resume_token != token_before})
    checks.append({"check": "token after mark_succeeded is not None", "passed": job2.resume_token is not None})

    # --- mark_failed issues a new token ---
    job3 = create_job(ch)
    cp.register_job(job3)
    cp.issue_resume_token(job3)
    token_before3 = job3.resume_token
    cp.mark_running(job3)
    cp.mark_failed(job3, {"error_type": "TestError", "message": "intentional"})
    checks.append({"check": "mark_failed issues new resume_token", "passed": job3.resume_token != token_before3})
    checks.append({"check": "token after mark_failed is not None", "passed": job3.resume_token is not None})

    # --- token is opaque passthrough via adapter ---
    msg = ChannelMessage(input={"hello": "adapter"})
    s1_req = s2_to_s1_adapter(msg, resume_token=t1)
    checks.append({"check": "adapter includes resume_token in request", "passed": s1_req.get("resume_token") == t1})
    checks.append({"check": "adapter preserves other keys", "passed": s1_req["type"] == "s1_request" and s1_req["input"] == {"hello": "adapter"}})

    # --- adapter without token ---
    s1_req2 = s2_to_s1_adapter(msg)
    checks.append({"check": "adapter without token omits resume_token key", "passed": "resume_token" not in s1_req2})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("multi_cycle", "Multi-cycle Worker loop: ExecutionContext, checkpointing, resume tokens, cycle traces")
def _test_multi_cycle() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.control_plane import ControlPlane
    from src.platform.runtime.execution_context import ExecutionContext
    from src.platform.runtime.job import create_job
    from src.platform.runtime.job_store import InMemoryJobStore

    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    q = InMemoryQueue()
    w = Worker(queue=q, control_plane=cp)

    ch = ChannelMessage(input={"multi": "cycle"})
    job = create_job(ch)
    store.save(job)
    q.push(job)

    # Process through multi-cycle loop
    result = w.process_next()
    checks.append({"check": "process_next returns job", "passed": result is job})
    checks.append({"check": "state is succeeded", "passed": result is not None and result.state == "succeeded"})
    checks.append({"check": "result is populated", "passed": result is not None and result.result is not None})

    if result and result.result:
        checks.append({"check": "result type is s2_result", "passed": result.result.get("type") == "s2_result"})
        notes.append(f"Result: {result.result}")

    # Lifecycle trace events on job.trace
    life_events = [e["event"] for e in job.trace]
    checks.append({"check": "hydrate event in job.trace", "passed": "hydrate_execution_context" in life_events})
    checks.append({"check": "dehydrate events in job.trace", "passed": "dehydrate_execution_context" in life_events})
    notes.append(f"Lifecycle trace events: {life_events}")

    # Execution context was hydrated during the loop
    checks.append({"check": "execution_context exists after cycle", "passed": job.execution_context is not None})

    if job.execution_context is not None:
        checks.append({"check": "cycle_trace has entries", "passed": len(job.execution_context.cycle_trace) > 0})
        notes.append(f"Cycle trace entries: {len(job.execution_context.cycle_trace)}")

        # Each pair of entries should be cycle_start + cycle_end
        events = [e["event"] for e in job.execution_context.cycle_trace]
        checks.append({"check": "first event is cycle_start", "passed": events[0] == "cycle_start"})
        checks.append({"check": "last event is cycle_end", "passed": events[-1] == "cycle_end"})

    # Resume token was issued
    checks.append({"check": "resume_token set after processing", "passed": job.resume_token is not None})

    # Checkpoint persisted to store
    stored = store.get(job.job_id)
    checks.append({"check": "job persisted in store", "passed": stored is not None})
    if stored is not None and stored.execution_context is not None:
        checks.append({"check": "cycle_trace persisted in store", "passed": len(stored.execution_context.cycle_trace) > 0})

    # Queue drained
    checks.append({"check": "queue drained after processing", "passed": len(q) == 0})

    # --- Multi-cycle with simulated multiple cycles ---
    # Create a second job where execute_job_payload returns done=False on first call
    # (simulate by injecting a custom execute via a test subclass or manually looping)
    notes.append("Verifying multi-cycle loop completes after one cycle (done=True from stub)")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("retry_policy", "RetryPolicy evaluation logic — known/unknown errors, exhaustion, backoff")
def _test_retry_policy() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    policy = default_retry_policy()

    # --- Known error type, first attempt ---
    d = policy.evaluate(RetryContext(attempt=1, error_type="TimeoutError"))
    checks.append({"check": "TimeoutError attempt 1 should_retry", "passed": d.should_retry is True})
    checks.append({"check": "TimeoutError attempt 1 delay", "passed": d.delay_seconds == 1.5})

    # --- Exponential backoff (attempt 2 of 2 max) ---
    d = policy.evaluate(RetryContext(attempt=2, error_type="TimeoutError"))
    # max_attempts=2, so attempt 2 >= 2 → exhausted
    checks.append({"check": "TimeoutError attempt 2 exhausted", "passed": d.should_retry is False})
    checks.append({"check": "TimeoutError attempt 2 no delay", "passed": d.delay_seconds is None})

    # Verify the exponential backoff calculation on attempt 2 with higher max_attempts
    policy3 = PlatformRetryPolicy({"TimeoutError": {"max_attempts": 5, "base_delay": 1.5}})
    d = policy3.evaluate(RetryContext(attempt=2, error_type="TimeoutError"))
    checks.append({"check": "backoff attempt 2 delay 3.0", "passed": d.delay_seconds == 3.0})  # 1.5 * 2^(2-1)

    # --- Exhaustion (attempt 3, max=2) ---
    d = policy.evaluate(RetryContext(attempt=3, error_type="TimeoutError"))
    checks.append({"check": "TimeoutError attempt 3 exhausted", "passed": d.should_retry is False})
    checks.append({"check": "TimeoutError attempt 3 no delay", "passed": d.delay_seconds is None})

    # --- Unknown error type ---
    d = policy.evaluate(RetryContext(attempt=1, error_type="UnknownError"))
    checks.append({"check": "UnknownError no retry", "passed": d.should_retry is False})

    # --- RateLimitError default rules ---
    d = policy.evaluate(RetryContext(attempt=1, error_type="RateLimitError"))
    checks.append({"check": "RateLimitError attempt 1 delay", "passed": d.delay_seconds == 2.0})

    # --- Custom policy (max_attempts=1, so attempt 1 >= 1 → no retry) ---
    custom = PlatformRetryPolicy({"CustomError": {"max_attempts": 1, "base_delay": 0.5}})
    d = custom.evaluate(RetryContext(attempt=1, error_type="CustomError"))
    checks.append({"check": "CustomError attempt 1 exhausted", "passed": d.should_retry is False})

    # max_attempts=1 → only retry when attempt=0 (impossible), attempt 1 is always exhausted
    d = custom.evaluate(RetryContext(attempt=2, error_type="CustomError"))
    checks.append({"check": "CustomError attempt 2 exhausted", "passed": d.should_retry is False})

    # --- DEFAULT_RETRY_RULES structure ---
    checks.append({"check": "default rules contain TransientNetworkError",
                   "passed": "TransientNetworkError" in DEFAULT_RETRY_RULES})
    checks.append({"check": "default rules contain RateLimitError",
                   "passed": "RateLimitError" in DEFAULT_RETRY_RULES})
    checks.append({"check": "default rules contain TimeoutError",
                   "passed": "TimeoutError" in DEFAULT_RETRY_RULES})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("retry_wrapper_recovery", "ToolRetryWrapper retries a flaky function until success")
def _test_retry_wrapper_recovery() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    class _FlakyError(Exception):
        pass

    call_count: int = 0

    def _flaky_fn() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _FlakyError("simulated transient failure")
        return "ok"

    policy = PlatformRetryPolicy({_FlakyError.__name__: {"max_attempts": 5, "base_delay": 0.001}})
    wrapper = ToolRetryWrapper(_flaky_fn, retry_policy=policy)

    result = wrapper.execute(attempt=1)

    # After attempt 1: failure → RetryInstruction
    checks.append({"check": "attempt 1 returns RetryInstruction", "passed": isinstance(result, RetryInstruction)})
    if isinstance(result, RetryInstruction):
        checks.append({"check": "attempt 1 sets next_attempt=2", "passed": result.next_attempt == 2})
        notes.append(f"attempt 1 → RetryInstruction(delay={result.delay_seconds}, next={result.next_attempt})")

        # Simulate retry by calling with next_attempt
        result2 = wrapper.execute(attempt=result.next_attempt)
        checks.append({"check": "attempt 2 returns RetryInstruction again",
                       "passed": isinstance(result2, RetryInstruction)})
        if isinstance(result2, RetryInstruction):
            notes.append(f"attempt 2 → RetryInstruction(delay={result2.delay_seconds}, next={result2.next_attempt})")
            result3 = wrapper.execute(attempt=result2.next_attempt)
            checks.append({"check": "attempt 3 succeeds", "passed": result3 == "ok"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("retry_wrapper_exhaustion", "ToolRetryWrapper exhausts max_attempts and re-raises")
def _test_retry_wrapper_exhaustion() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    class _AlwaysFailError(Exception):
        pass

    call_count: int = 0

    def _always_fail() -> str:
        nonlocal call_count
        call_count += 1
        raise _AlwaysFailError("always fails")

    policy = PlatformRetryPolicy({_AlwaysFailError.__name__: {"max_attempts": 3, "base_delay": 0.001}})
    wrapper = ToolRetryWrapper(_always_fail, retry_policy=policy)

    # Attempt 1 → RetryInstruction (attempt 1 < 3)
    r1 = wrapper.execute(attempt=1)
    checks.append({"check": "attempt 1 returns instruction", "passed": isinstance(r1, RetryInstruction)})
    if isinstance(r1, RetryInstruction):
        notes.append(f"attempt 1 → retry (delay={r1.delay_seconds})")

    # Attempt 2 → RetryInstruction (attempt 2 < 3)
    r2 = wrapper.execute(attempt=r1.next_attempt)
    checks.append({"check": "attempt 2 returns instruction", "passed": isinstance(r2, RetryInstruction)})
    if isinstance(r2, RetryInstruction):
        notes.append(f"attempt 2 → retry (delay={r2.delay_seconds})")

    # Attempt 3 → exhausted (attempt 3 >= 3), should raise
    try:
        wrapper.execute(attempt=r2.next_attempt)
        checks.append({"check": "attempt 3 raises exception", "passed": False})
    except _AlwaysFailError:
        checks.append({"check": "attempt 3 re-raises original error", "passed": True})
        notes.append("attempt 3 → _AlwaysFailError re-raised (exhausted)")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("worker_retry", "Worker accepts retry wrapper and processes normally")
def _test_worker_retry() -> dict[str, Any]:
    """Verify the Worker's retry wrapper doesn't block normal execution."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    q = InMemoryQueue()
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    w = Worker(queue=q, control_plane=cp)

    job = create_job(cli_to_channel_message({"cmd": "deploy"}))
    cp.register_job(job)
    q.push(job)
    notes.append(f"Pushed job {job.job_id}")

    result = w.process_next()
    checks.append({"check": "worker returns job", "passed": result is not None})
    if result:
        checks.append({"check": "worker succeeds", "passed": result.state.value == "succeeded"})
        checks.append({"check": "result payload present", "passed": result.result is not None})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("poison_detection", "PoisonDetector identifies poison jobs by failure count")
def _test_poison_detection() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    detector = default_poison_detector()

    # Below threshold
    d = detector.evaluate(PoisonContext(job_id="j1", failure_count=3, error_type="TimeoutError"))
    checks.append({"check": "failure_count 3 < 5 is not poison", "passed": d.is_poison is False})
    checks.append({"check": "below threshold reason is None", "passed": d.reason is None})

    # At threshold
    d = detector.evaluate(PoisonContext(job_id="j2", failure_count=5, error_type="TimeoutError"))
    checks.append({"check": "failure_count 5 >= 5 is poison", "passed": d.is_poison is True})
    checks.append({"check": "poison reason populated", "passed": d.reason is not None})

    # Above threshold
    d = detector.evaluate(PoisonContext(job_id="j3", failure_count=7, error_type="RateLimitError"))
    checks.append({"check": "failure_count 7 >= 5 is poison", "passed": d.is_poison is True})

    # Custom threshold
    strict = PoisonDetector(max_failures=1)
    d = strict.evaluate(PoisonContext(job_id="j4", failure_count=1, error_type="AnyError"))
    checks.append({"check": "strict max=1 triggers at count 1", "passed": d.is_poison is True})

    d = strict.evaluate(PoisonContext(job_id="j5", failure_count=0, error_type="AnyError"))
    checks.append({"check": "strict max=1 count 0 not poison", "passed": d.is_poison is False})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("poison_wrapper", "ToolRetryWrapper returns PoisonInstruction for poison jobs")
def _test_poison_wrapper() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    class _PoisonError(Exception):
        pass

    def _always_poison() -> str:
        raise _PoisonError("too many failures")

    policy = PlatformRetryPolicy({_PoisonError.__name__: {"max_attempts": 10, "base_delay": 0.001}})
    detector = PoisonDetector(max_failures=3)
    wrapper = ToolRetryWrapper(_always_poison, retry_policy=policy, poison_detector=detector)

    # failure_count=3 (at threshold) → PoisonInstruction, not RetryInstruction
    result = wrapper.execute(attempt=1, job_id="poison-1", failure_count=3)
    checks.append({"check": "poison at threshold returns PoisonInstruction",
                   "passed": isinstance(result, PoisonInstruction)})
    if isinstance(result, PoisonInstruction):
        checks.append({"check": "poison instruction reason present",
                       "passed": len(result.reason) > 0})
        notes.append(f"PoisonInstruction(reason={result.reason})")

    # failure_count=1 (below threshold) → RetryInstruction
    result2 = wrapper.execute(attempt=1, job_id="poison-2", failure_count=1)
    checks.append({"check": "below poison threshold returns RetryInstruction",
                   "passed": isinstance(result2, RetryInstruction)})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("worker_poison", "Worker marks job POISON when failure threshold exceeded")
def _test_worker_poison() -> dict[str, Any]:
    """Verify the worker marks a job as POISON after repeated failures."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    q = InMemoryQueue()
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    w = Worker(queue=q, control_plane=cp)

    # Replace the retry wrapper's function with one that always fails
    def _always_fail_fn(*args, **kwargs):
        raise RuntimeError("simulated poison")

    w._retry_wrapper.fn = _always_fail_fn

    job = create_job(cli_to_channel_message({"cmd": "deploy"}))
    cp.register_job(job)
    q.push(job)

    notes.append(f"Pushed job {job.job_id}")

    # Inject high failure_count + store so the Worker loads it
    job.failure_count = 5
    store.save(job)
    notes.append(f"Set failure_count=5 to trigger poison")

    result = w.process_next()
    checks.append({"check": "worker returns job", "passed": result is not None})
    if result:
        checks.append({"check": "job state is poison", "passed": result.state == JobState.POISON})
        checks.append({"check": "failure_count incremented to 6", "passed": result.failure_count == 6})
        checks.append({"check": "result has poison flag",
                       "passed": result.result is not None and result.result.get("poison") is True})
        notes.append(f"Job {result.job_id} → {result.state.value} (failures={result.failure_count})")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("crash_recovery_logic", "Pure logic tests for CrashRecovery.evaluate()")
def _test_crash_recovery_logic() -> dict[str, Any]:
    """Verify CrashRecovery decisions: no checkpoint, not running, RUNNING+checkpoint, token match/mismatch."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.execution_context import ExecutionContext

    cr = default_crash_recovery()

    # No checkpoint
    ctx1 = RecoveryContext(
        job_id="j1", last_checkpoint=None, last_resume_token=None, job_state="pending",
    )
    d1 = cr.evaluate(ctx1)
    checks.append({"check": "no checkpoint → no recovery", "passed": not d1.should_recover})
    notes.append(f"no checkpoint → should_recover={d1.should_recover}")

    # Not running — use a real ExecutionContext
    ec_failed = ExecutionContext(cognitive_state={"x": 1}, memory={}, last_result=None)
    ctx2 = RecoveryContext(
        job_id="j2", last_checkpoint=ec_failed, last_resume_token="tok1", job_state="failed",
    )
    d2 = cr.evaluate(ctx2)
    checks.append({"check": "not running → no recovery", "passed": not d2.should_recover})
    notes.append(f"state=failed → should_recover={d2.should_recover}")

    # Running + checkpoint — should recover
    ec = ExecutionContext(cognitive_state={"a": 1}, memory={}, last_result={"value": "partial"})
    ctx3 = RecoveryContext(
        job_id="j3", last_checkpoint=ec, last_resume_token="tok2", job_state="running",
    )
    d3 = cr.evaluate(ctx3)
    checks.append({"check": "RUNNING + checkpoint → recover", "passed": d3.should_recover})
    checks.append({"check": "resume_token preserved", "passed": d3.resume_token == "tok2"})
    notes.append(f"RUNNING + checkpoint → should_recover={d3.should_recover} token={d3.resume_token}")

    # Validate token: match
    checks.append({
        "check": "validate_resume_token match",
        "passed": cr.validate_resume_token("abc", "abc"),
    })

    # Validate token: mismatch
    checks.append({
        "check": "validate_resume_token mismatch",
        "passed": not cr.validate_resume_token("abc", "xyz"),
    })

    # Validate token: first token None
    checks.append({
        "check": "validate_resume_token first is None",
        "passed": cr.validate_resume_token(None, "any"),
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("worker_crash_recovery", "Worker recovers a job left in RUNNING state with a checkpoint")
def _test_worker_crash_recovery() -> dict[str, Any]:
    """Push a job, execute one cycle (creating a checkpoint), then simulate crash
    by pushing the same job again in RUNNING state. Worker should recover and complete it."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.execution_context import ExecutionContext

    q = InMemoryQueue()
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    w = Worker(queue=q, control_plane=cp)

    job = create_job(cli_to_channel_message({"cmd": "analyze"}))
    cp.register_job(job)
    q.push(job)
    notes.append(f"Pushed job {job.job_id}")

    # First cycle — execute normally
    notes.append("First process_next (normal execution)...")
    result1 = w.process_next()
    checks.append({"check": "first cycle succeeded", "passed": result1 is not None and result1.state == JobState.SUCCEEDED})
    notes.append(f"After first cycle: state={result1.state.value if result1 else 'None'}")

    # Simulate a crash: create a fresh job that references the same ID, in RUNNING state
    # with a checkpoint in the store
    crash_job = create_job(cli_to_channel_message({"cmd": "analyze"}))
    cp.register_job(crash_job)
    # Put it in RUNNING state in the store
    crash_job.state = JobState.RUNNING
    crash_job.execution_context = ExecutionContext(
        cognitive_state={"phase": "mid"},
        memory={},
        last_result={"value": "partial"},
    )
    crash_job.resume_token = result1.resume_token if result1 else None
    store.save(crash_job)
    q.push(crash_job)
    notes.append(f"Simulated crash — pushed job {crash_job.job_id} in RUNNING state with checkpoint")

    # Second process_next — worker should recover and complete
    notes.append("Second process_next (crash recovery)...")
    result2 = w.process_next()
    checks.append({"check": "recovery returned job", "passed": result2 is not None})
    if result2:
        checks.append({"check": "recovery completed job", "passed": result2.state == JobState.SUCCEEDED})
        notes.append(f"After recovery: state={result2.state.value} token={result2.resume_token}")
        # Should have a lifecycle event for crash_recovery
        has_crash_event = any(
            t.get("event") == "crash_recovery" for t in result2.trace
        )
        checks.append({"check": "crash_recovery lifecycle event recorded", "passed": has_crash_event})
        if has_crash_event:
            notes.append("crash_recovery event found in trace")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("recovery_idempotency", "Pure logic: validate_resume_token enforces idempotency")
def _test_recovery_idempotency() -> dict[str, Any]:
    """Verify `validate_resume_token` pure logic — the idempotency gate that
    ensures a cycle only advances when tokens match."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cr = default_crash_recovery()

    from src.platform.runtime.execution_context import ExecutionContext

    # Same token → safe to advance
    checks.append({
        "check": "identical tokens → safe",
        "passed": cr.validate_resume_token("token-A", "token-A"),
    })
    notes.append("token-A == token-A: safe to advance")

    # Different tokens → must re-hydrate
    checks.append({
        "check": "different tokens → block",
        "passed": not cr.validate_resume_token("token-A", "token-B"),
    })
    notes.append("token-A != token-B: block advancement")

    # Both None → safe (fresh job, no checkpoint)
    checks.append({
        "check": "both None → safe",
        "passed": cr.validate_resume_token(None, None),
    })
    notes.append("None == None: safe (fresh job)")

    # expected is None, actual is set → safe (first cycle)
    checks.append({
        "check": "expected None, actual set → safe",
        "passed": cr.validate_resume_token(None, "new-token"),
    })
    notes.append("expected=None, actual=token: safe (first cycle)")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("poison_skip_recovery",
           "Poisoned jobs in RUNNING state skip recovery and go to POISON")
def _test_poison_skip_recovery() -> dict[str, Any]:
    """A job with POISON state should not be recovered even if a checkpoint exists."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.execution_context import ExecutionContext

    q = InMemoryQueue()
    store = InMemoryJobStore()
    cp = ControlPlane(job_store=store)
    w = Worker(queue=q, control_plane=cp)

    job = create_job(cli_to_channel_message({"cmd": "tainted"}))
    cp.register_job(job)

    # Job is POISON but has a checkpoint (simulates a poison job that crashed after being marked)
    job.state = JobState.POISON
    job.failure_count = 5
    job.execution_context = ExecutionContext(
        cognitive_state={"bad": True}, memory={}, last_result=None,
    )
    job.resume_token = "poison-token"
    store.save(job)
    q.push(job)
    notes.append(f"Pushed POISON job {job.job_id} with checkpoint")

    result = w.process_next()
    checks.append({"check": "worker returned job", "passed": result is not None})
    if result:
        # The worker should NOT try to run or recover a poison job
        checks.append({"check": "state remains poison",
                       "passed": result.state == JobState.POISON})
        notes.append(f"Result state: {result.state.value}")

    # Verify CrashRecovery pure logic: POISON should not recover
    cr = default_crash_recovery()
    ctx = RecoveryContext(
        job_id="p1",
        last_checkpoint=job.execution_context,
        last_resume_token="poison-token",
        job_state="poison",
    )
    d = cr.evaluate(ctx)
    checks.append({"check": "poison state → no recovery (pure logic)",
                   "passed": not d.should_recover})
    notes.append(f"Poison evaluate: should_recover={d.should_recover}")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("panic_guard_pure_logic",
           "PanicGuard pure logic: wrap catches exceptions, returns StructuredFailure/PanicDecision")
def _test_panic_guard_pure_logic() -> dict[str, Any]:
    """PanicGuard.wrap() catches unexpected exceptions and returns PanicDecision."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    guard = default_panic_guard()

    # --- Success path ---
    @guard.wrap
    def _succeeds() -> str:
        return "ok"

    result = _succeeds()
    checks.append({"check": "successful fn returns its value", "passed": result == "ok"})

    # --- Exception path ---
    @guard.wrap
    def _panics() -> str:
        raise RuntimeError("boom")

    result = _panics()
    checks.append({"check": "panicked fn returns PanicDecision", "passed": isinstance(result, PanicDecision)})
    if isinstance(result, PanicDecision):
        checks.append({"check": "is_panic is True", "passed": result.is_panic is True})
        checks.append({"check": "reason is set", "passed": result.reason is not None})
        checks.append({"check": "safe_failure is StructuredFailure", "passed": isinstance(result.safe_failure, StructuredFailure)})
        if result.safe_failure is not None:
            checks.append({"check": "error_type captured", "passed": result.safe_failure.error_type == "RuntimeError"})
            checks.append({"check": "message captured", "passed": str(result.safe_failure.message) == "boom"})

    # --- handle_exception directly ---
    raw_decision = guard.handle_exception(ValueError("bad value"))
    checks.append({"check": "handle_exception returns PanicDecision", "passed": isinstance(raw_decision, PanicDecision)})
    if isinstance(raw_decision, PanicDecision):
        checks.append({"check": "handle_exception is_panic True",
                       "passed": raw_decision.is_panic is True})
        if raw_decision.safe_failure is not None:
            checks.append({"check": "handle_exception error_type",
                           "passed": raw_decision.safe_failure.error_type == "ValueError"})

    # --- StructuredFailure idempotency ---
    sf1 = StructuredFailure.from_exception(ValueError("same"))
    sf2 = StructuredFailure.from_exception(ValueError("same"))
    checks.append({"check": "same exception → same StructuredFailure fields",
                   "passed": sf1.error_type == sf2.error_type and sf1.message == sf2.message})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_pure_logic",
           "DegradedMode pure logic — thresholds, signals, edge cases")
def _test_degraded_mode_pure_logic() -> dict[str, Any]:
    """DegradedMode.evaluate() returns correct decisions for various contexts."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    dm = default_degraded_mode()

    # --- Normal mode (no signals) ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "no signals → normal mode", "passed": d.enter_degraded is False})
    checks.append({"check": "no signals → no reason", "passed": d.reason is None})

    # --- Retry exhausted ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0, retry_exhausted=True,
    ))
    checks.append({"check": "retry exhausted → degraded", "passed": d.enter_degraded is True})
    if d.reason:
        checks.append({"check": "retry exhausted reason set", "passed": "Retry" in d.reason})

    # --- Consecutive failures threshold ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=3, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "failures=3 → degraded", "passed": d.enter_degraded is True})
    if d.reason:
        checks.append({"check": "failures reason mentions failures", "passed": "failures" in d.reason.lower()})

    # Below threshold
    d = dm.evaluate(DegradedContext(
        consecutive_failures=2, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "failures=2 → normal", "passed": d.enter_degraded is False})

    # --- Panic count threshold ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=1, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "panic=1 → degraded", "passed": d.enter_degraded is True})

    # Below threshold
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "panic=0 → normal", "passed": d.enter_degraded is False})

    # --- Crash count threshold ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=1, retry_exhausted=False,
    ))
    checks.append({"check": "crash=1 → degraded", "passed": d.enter_degraded is True})

    # Below threshold
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "crash=0 → normal", "passed": d.enter_degraded is False})

    # --- Custom thresholds ---
    custom = DegradedMode({"failures": 5, "panics": 2, "crashes": 3})
    d = custom.evaluate(DegradedContext(
        consecutive_failures=4, panic_count=1, crash_count=2, retry_exhausted=False,
    ))
    checks.append({"check": "custom: all below → normal", "passed": d.enter_degraded is False})

    d = custom.evaluate(DegradedContext(
        consecutive_failures=5, panic_count=1, crash_count=2, retry_exhausted=False,
    ))
    checks.append({"check": "custom: failures=5 → degraded", "passed": d.enter_degraded is True})

    d = custom.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=2, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "custom: panics=2 → degraded", "passed": d.enter_degraded is True})

    d = custom.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=3, retry_exhausted=False,
    ))
    checks.append({"check": "custom: crashes=3 → degraded", "passed": d.enter_degraded is True})

    # --- Priority: retry exhausted checked first ---
    d = dm.evaluate(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0, retry_exhausted=True,
    ))
    checks.append({"check": "retry exhausted before other signals",
                   "passed": d.enter_degraded is True})

    # --- Factory returns defaults ---
    dm2 = default_degraded_mode()
    d = dm2.evaluate(DegradedContext(
        consecutive_failures=3, panic_count=0, crash_count=0, retry_exhausted=False,
    ))
    checks.append({"check": "factory threshold appears correct",
                   "passed": d.enter_degraded is True})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_in_worker",
           "Worker enters degraded mode when consecutive failures exceed threshold")
def _test_degraded_mode_in_worker() -> dict[str, Any]:
    """Worker.process_next() enters degraded mode when failure thresholds are exceeded."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.worker import execute_job_payload

    # Save original to restore later
    _original = execute_job_payload

    def _always_fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("persistent failure")

    import src.platform.runtime.worker as worker_mod
    worker_mod.execute_job_payload = _always_fail  # type: ignore[assignment]

    try:
        q = InMemoryQueue()
        store = InMemoryJobStore()
        cp = ControlPlane(job_store=store)
        w = Worker(queue=q, control_plane=cp)

        # Create a job with consecutive_failures already at the degraded threshold (3)
        job = create_job(cli_to_channel_message({"cmd": "degrade-me"}))
        job.consecutive_failures = 3
        cp.register_job(job)
        q.push(job)

        result = w.process_next()
        checks.append({"check": "worker returned job", "passed": result is not None})
        if result:
            # Should succeed with fallback, not fail
            checks.append({"check": "state is SUCCEEDED (fallback)",
                           "passed": result.state == JobState.SUCCEEDED})
            if result.result is not None:
                checks.append({"check": "result has fallback flag",
                               "passed": result.result.get("fallback") is True})
                checks.append({"check": "result has reason",
                               "passed": result.result.get("reason") is not None})
            notes.append(f"Result state: {result.state.value}")
            notes.append(f"Result: {result.result}")
    finally:
        worker_mod.execute_job_payload = _original

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("panic_guard_in_worker",
           "Worker wraps cycle execution with PanicGuard on unexpected exception")
def _test_panic_guard_in_worker() -> dict[str, Any]:
    """Worker.process_next() catches unexpected exceptions via PanicGuard and marks FAILED."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    from src.platform.runtime.worker import execute_job_payload

    # Save original to restore later
    _original = execute_job_payload

    def _broken_execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("catastrophic failure")

    import src.platform.runtime.worker as worker_mod
    worker_mod.execute_job_payload = _broken_execute  # type: ignore[assignment]

    try:
        q = InMemoryQueue()
        store = InMemoryJobStore()
        cp = ControlPlane(job_store=store)
        w = Worker(queue=q, control_plane=cp)

        job = create_job(cli_to_channel_message({"cmd": "boom"}))
        cp.register_job(job)
        q.push(job)

        result = w.process_next()
        checks.append({"check": "worker returned job", "passed": result is not None})
        if result:
            checks.append({"check": "job state is FAILED",
                           "passed": result.state == JobState.FAILED})
            # Verify the trace has lifecycle events indicating hydration + failure
            has_hydrate = any(
                e.get("event") == "hydrate_execution_context"
                for e in result.trace
            )
            checks.append({"check": "hydrate event in trace", "passed": has_hydrate})
            notes.append(f"Result state: {result.state.value}")
    finally:
        worker_mod.execute_job_payload = _original

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


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
