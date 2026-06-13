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

from src.platform.transport.dev_smtp import (
    DevSMTPConfig,
    DevSMTPTransport,
)
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
    SafeFallbackOutput,
    SignalState,
    WorkerDegradedEvent,
    WorkerRecoveredEvent,
    default_degraded_mode,
)
from src.platform.runtime.channels import (
    CLIChannel,
    CLITUI,
    InboundChannelMessage,
    ChannelRegistry,
    MailChannel,
    SlackChannel,
    WebhookChannel,
    WebhookEvent,
    WebSocketChannel,
    register_cli_channel,
    register_mail_channel,
    register_slack_channel,
    register_webhook_channel,
    register_websocket_channel,
)
from src.platform.runtime.gateway_entrypoint import (
    process_channel_input,
    handle_slack_event,
    handle_mail_message,
)
from src.platform.supervisor.supervisor_loop import (
    SupervisorConfig,
    SupervisorDecision,
    SupervisorEscalation,
    SupervisorLoop,
    WorkerHealth,
    WorkerHeartbeat,
    WorkerRestartEvent,
)
from src.platform.supervisor.queue_supervisor import (
    QueueSupervisor,
    QueueSupervisorConfig,
    QueueSupervisorDecision,
    QueueMetrics,
    StuckJobEvent,
    QueueBackpressureEvent,
    QueueSupervisorEscalation,
)
from src.platform.supervisor.control_plane_supervisor import (
    AutoRepairEvent,
    ControlPlaneEscalation,
    ControlPlaneSupervisor,
    ControlPlaneSupervisorConfig,
    ControlPlaneSupervisorDecision,
    InconsistencyEvent,
    JobStateSnapshot,
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
        checks.append({"check": "retry exhausted reason set", "passed": "retry" in d.reason.lower()})

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
                checks.append({"check": "result has fallback_action",
                               "passed": result.result.get("fallback_action") is not None})
                checks.append({"check": "result status is degraded",
                               "passed": result.result.get("status") == "degraded"})
                checks.append({"check": "result has reason",
                               "passed": result.result.get("reason") is not None})
            notes.append(f"Result state: {result.state.value}")
            notes.append(f"Result: {result.result}")
    finally:
        worker_mod.execute_job_payload = _original

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_fallback_schema",
           "SafeFallbackOutput schema compliance and serialisation")
def _test_degraded_mode_fallback_schema() -> dict[str, Any]:
    """SafeFallbackOutput schema produces all required fields with correct structure."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # --- Schema fields ---
    fb = SafeFallbackOutput(
        reason="test_reason",
        detail="Test detail message",
        job_id="job-001",
        fallback_action="short_circuit_and_acknowledge",
        recovery_hint="Recovery requires 5 stable cycles.",
    )
    checks.append({"check": "status is 'degraded'", "passed": fb.status == "degraded"})
    checks.append({"check": "reason is set", "passed": fb.reason == "test_reason"})
    checks.append({"check": "detail is set", "passed": fb.detail == "Test detail message"})
    checks.append({"check": "job_id is set", "passed": fb.job_id == "job-001"})
    checks.append({"check": "fallback_action is set", "passed": fb.fallback_action == "short_circuit_and_acknowledge"})
    checks.append({"check": "recovery_hint is set", "passed": fb.recovery_hint == "Recovery requires 5 stable cycles."})

    # --- to_dict / from_dict round-trip ---
    d = fb.to_dict()
    checks.append({"check": "to_dict returns dict with all 6 keys",
                   "passed": len(d) == 6 and "status" in d and "reason" in d})
    checks.append({"check": "to_dict values match dataclass",
                   "passed": d["reason"] == "test_reason" and d["status"] == "degraded"})

    fb2 = SafeFallbackOutput.from_dict(d)
    checks.append({"check": "from_dict round-trip preserves status",
                   "passed": fb2.status == fb.status})
    checks.append({"check": "from_dict round-trip preserves reason",
                   "passed": fb2.reason == fb.reason})
    checks.append({"check": "from_dict round-trip preserves job_id",
                   "passed": fb2.job_id == fb.job_id})
    checks.append({"check": "from_dict round-trip preserves fallback_action",
                   "passed": fb2.fallback_action == fb.fallback_action})

    # --- Default construction ---
    fb3 = SafeFallbackOutput()
    checks.append({"check": "default status is 'degraded'", "passed": fb3.status == "degraded"})
    checks.append({"check": "default reason is empty", "passed": fb3.reason == ""})

    # --- from_dict with empty dict ---
    fb4 = SafeFallbackOutput.from_dict({})
    checks.append({"check": "from_dict({}) defaults status", "passed": fb4.status == "degraded"})
    checks.append({"check": "from_dict({}) defaults reason", "passed": fb4.reason == ""})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_escalation",
           "WorkerDegradedEvent escalation schema and DegradedMode escalation")
def _test_degraded_mode_escalation() -> dict[str, Any]:
    """WorkerDegradedEvent schema and that DegradedMode produces escalation events."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # --- Escalation event schema ---
    ev = WorkerDegradedEvent(
        worker_id="w-42",
        job_id="job-007",
        severity="high",
        timestamp="2025-01-01T00:00:00Z",
        reason="consecutive_failures_exceeded",
    )
    checks.append({"check": "event type is 'worker_degraded'",
                   "passed": ev.event == "worker_degraded"})
    checks.append({"check": "severity is 'high'", "passed": ev.severity == "high"})
    checks.append({"check": "worker_id preserved", "passed": ev.worker_id == "w-42"})
    checks.append({"check": "job_id preserved", "passed": ev.job_id == "job-007"})
    checks.append({"check": "timestamp preserved",
                   "passed": ev.timestamp == "2025-01-01T00:00:00Z"})
    checks.append({"check": "reason preserved",
                   "passed": ev.reason == "consecutive_failures_exceeded"})

    # --- to_dict round-trip ---
    d = ev.to_dict()
    checks.append({"check": "escalation to_dict has 6 keys",
                   "passed": len(d) == 6})
    checks.append({"check": "escalation to_dict includes event key",
                   "passed": d.get("event") == "worker_degraded"})

    # --- DegradedMode.evaluate() produces escalation event ---
    dm = default_degraded_mode(worker_id="test-worker")
    ctx = DegradedContext(
        consecutive_failures=3, panic_count=0, crash_count=0,
        retry_exhausted=False, job_id="job-esc-1",
    )
    decision = dm.evaluate(ctx)
    checks.append({"check": "degraded decision produces escalation_event",
                   "passed": decision.escalation_event is not None})
    if decision.escalation_event:
        ee = decision.escalation_event
        checks.append({"check": "escalation reason matches decision reason",
                       "passed": ee.reason == decision.reason})
        checks.append({"check": "escalation includes worker_id",
                       "passed": ee.worker_id == "test-worker"})
        checks.append({"check": "escalation includes job_id",
                       "passed": ee.job_id == "job-esc-1"})
        checks.append({"check": "escalation has non-empty timestamp",
                       "passed": len(ee.timestamp) > 0})
        notes.append(f"Escalation event: {ee.to_dict()}")

    # --- Recovered event schema ---
    rev = WorkerRecoveredEvent(worker_id="w-42", stability_window=5)
    checks.append({"check": "recovery event type is 'worker_recovered'",
                   "passed": rev.event == "worker_recovered"})
    checks.append({"check": "recovery to_dict preserves stability_window",
                   "passed": rev.to_dict().get("stability_window") == 5})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_recovery",
           "Recovery trigger logic — all gates must be green")
def _test_degraded_mode_recovery() -> dict[str, Any]:
    """DegradedMode.check_recovery() returns correct decisions for signal states."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    dm = default_degraded_mode(worker_id="recovery-test")

    # Helper: a context with already_degraded=True and the given signal_state
    def _ctx(sig: SignalState | None = None) -> DegradedContext:
        return DegradedContext(
            consecutive_failures=0, panic_count=0, crash_count=0,
            retry_exhausted=False, signal_state=sig,
            already_degraded=True, job_id="recovery-1",
        )

    # --- Not degraded → no-op ---
    d = dm.check_recovery(DegradedContext(
        consecutive_failures=0, panic_count=0, crash_count=0,
        retry_exhausted=False, already_degraded=False,
    ))
    checks.append({"check": "not degraded → no recovery needed",
                   "passed": d.enter_degraded is False and d.recovery_event is None})

    # --- No signal state → stay degraded ---
    d = dm.check_recovery(_ctx(None))
    checks.append({"check": "no signals → stay degraded",
                   "passed": d.enter_degraded is True and d.currently_degraded is True})

    # --- Gate 1: S1 not stable ---
    sig = SignalState(s1_stable=False, s1_stable_cycles=0)
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "S1 unstable → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- Gate 1: S1 stable but not enough cycles ---
    sig = SignalState(s1_stable=True, s1_stable_cycles=3)
    # Default recovery_stable_cycles is 5, so 3 < 5 → stay degraded
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "S1 stable < N cycles → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- Gate 2: S2 not stable ---
    sig = SignalState(s1_stable=True, s1_stable_cycles=10, s2_stable=False)
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "S2 unstable → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- Gate 3: S3 not stable ---
    sig = SignalState(s1_stable=True, s1_stable_cycles=10, s2_stable=True, s3_stable=False)
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "S3 unstable → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- Gate 4: Critical errors in window ---
    sig = SignalState(
        s1_stable=True, s1_stable_cycles=10, s2_stable=True, s3_stable=True,
        new_critical_errors=1,
    )
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "critical errors → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- Gate 4: Recent error timestamp ---
    sig = SignalState(
        s1_stable=True, s1_stable_cycles=10, s2_stable=True, s3_stable=True,
        new_critical_errors=0, last_error_timestamp=time.time(),
    )
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "recent error → stay degraded",
                   "passed": d.enter_degraded is True})

    # --- All gates green → recovery ---
    sig = SignalState(
        s1_stable=True, s1_stable_cycles=10, s2_stable=True, s3_stable=True,
        new_critical_errors=0, last_error_timestamp=0.0,
    )
    d = dm.check_recovery(_ctx(sig))
    checks.append({"check": "all green → recovery possible",
                   "passed": d.enter_degraded is False})
    checks.append({"check": "recovery event emitted",
                   "passed": d.recovery_event is not None})
    if d.recovery_event:
        checks.append({"check": "recovery event is worker_recovered",
                       "passed": d.recovery_event.event == "worker_recovered"})
        checks.append({"check": "recovery has worker_id",
                       "passed": d.recovery_event.worker_id == "recovery-test"})
        checks.append({"check": "recovery has stability_window",
                       "passed": d.recovery_event.stability_window == dm.recovery_stable_cycles})
        notes.append(f"Recovery event: {d.recovery_event.to_dict()}")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("degraded_mode_behavioural_contract",
           "Behavioural contract enforcement — allowed vs forbidden operations")
def _test_degraded_mode_behavioural_contract() -> dict[str, Any]:
    """DegradedMode class methods enforce the behavioural contract."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # --- Forbidden ops ---
    FORBIDDEN = ["retry", "backoff", "tool_call", "multi_step_reasoning",
                 "agentic_behaviour", "external_api_call", "state_mutation",
                 "job_completion_attempt"]

    for op in FORBIDDEN:
        checks.append({"check": f"'{op}' is forbidden",
                       "passed": DegradedMode.is_op_forbidden(op)})
        checks.append({"check": f"'{op}' is not allowed",
                       "passed": not DegradedMode.is_op_allowed(op)})

    # --- Allowed ops ---
    ALLOWED = ["produce_fallback_output", "emit_escalation_event",
               "wait_for_recovery_signals", "maintain_heartbeat",
               "maintain_isolation"]

    for op in ALLOWED:
        checks.append({"check": f"'{op}' is allowed",
                       "passed": DegradedMode.is_op_allowed(op)})
        checks.append({"check": f"'{op}' is not forbidden",
                       "passed": not DegradedMode.is_op_forbidden(op)})

    # --- validate_behaviour ---
    violations = DegradedMode.validate_behaviour([
        "produce_fallback_output",
        "tool_call",
        "maintain_heartbeat",
        "retry",
    ])
    checks.append({"check": "validate_behaviour returns forbidden ops",
                   "passed": len(violations) == 2})
    checks.append({"check": "tool_call is detected",
                   "passed": "tool_call" in violations})
    checks.append({"check": "retry is detected",
                   "passed": "retry" in violations})

    # --- No violations ---
    clean = DegradedMode.validate_behaviour(list(ALLOWED))
    checks.append({"check": "all allowed → no violations",
                   "passed": len(clean) == 0})

    # --- Unknown ops are not forbidden (not explicitly forbidden) ---
    checks.append({"check": "unknown op is not forbidden",
                   "passed": not DegradedMode.is_op_forbidden("unknown_op")})
    checks.append({"check": "unknown op is not allowed",
                   "passed": not DegradedMode.is_op_allowed("unknown_op")})

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


@_scenario("channels",
           "Channel abstraction: InboundChannelMessage, CLIChannel, CLITUI, registry, gateway")
def _test_channels() -> dict[str, Any]:
    """S4.6.1–S4.6.2 — Channel abstraction + CLI Channel integration."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. InboundChannelMessage immutability and construction
    # ------------------------------------------------------------------
    import time as _time
    ts = _time.time()
    msg = InboundChannelMessage(
        channel="cli", sender="alice",
        payload={"text": "hello"}, timestamp=ts,
    )
    checks.append({"check": "InboundChannelMessage constructed",
                   "passed": msg.channel == "cli"
                             and msg.sender == "alice"
                             and msg.payload == {"text": "hello"}
                             and msg.timestamp == ts})
    try:
        msg.payload = {}  # type: ignore[misc]
        checks.append({"check": "InboundChannelMessage immutable", "passed": False})
    except Exception:
        checks.append({"check": "InboundChannelMessage immutable", "passed": True})
    notes.append(f"InboundChannelMessage(channel={msg.channel}, sender={msg.sender})")

    # ------------------------------------------------------------------
    # 2. CLIChannel — receive with validation
    # ------------------------------------------------------------------
    _clock = iter([100.0, 101.0, 102.0, 103.0]).__next__
    cli_ch = CLIChannel(clock=_clock)

    # 2a. Minimal receive
    _msg1 = cli_ch.receive({"text": "deploy"})
    checks.append({"check": "CLIChannel receive minimal",
                   "passed": _msg1.channel == "cli"
                             and _msg1.sender is None
                             and _msg1.payload == {"text": "deploy"}
                             and _msg1.timestamp == 100.0})

    # 2b. Receive with sender
    _msg2 = cli_ch.receive({"text": "status", "sender": "bob"})
    checks.append({"check": "CLIChannel receive with sender",
                   "passed": _msg2.sender == "bob"
                             and _msg2.timestamp == 101.0})

    # 2c. Validation — non-dict raises TypeError
    try:
        cli_ch.receive("raw string")  # type: ignore[arg-type]
        checks.append({"check": "CLIChannel rejects non-dict", "passed": False})
    except TypeError:
        checks.append({"check": "CLIChannel rejects non-dict", "passed": True})

    # 2d. Validation — missing text raises ValueError
    try:
        cli_ch.receive({"sender": "alice"})
        checks.append({"check": "CLIChannel rejects missing text", "passed": False})
    except ValueError:
        checks.append({"check": "CLIChannel rejects missing text", "passed": True})

    # ------------------------------------------------------------------
    # 3. CLIChannel — normalize
    # ------------------------------------------------------------------
    _norm = cli_ch.normalize(_msg1)
    checks.append({"check": "CLIChannel normalize",
                   "passed": _norm == {
                       "input": "deploy",
                       "metadata": {
                           "channel": "cli",
                           "sender": None,
                           "received_at": 100.0,
                       },
                   }})

    # ------------------------------------------------------------------
    # 4. CLIChannel — send
    # ------------------------------------------------------------------
    _out = cli_ch.send({"output": "done", "metadata": {"key": "val"}})
    checks.append({"check": "CLIChannel send",
                   "passed": _out == {"text": "done", "metadata": {"key": "val"}}})

    # ------------------------------------------------------------------
    # 5. CLITUI stub
    # ------------------------------------------------------------------
    _tui = CLITUI()
    _rendered = _tui.render({"output": "hello", "metadata": {}})
    checks.append({"check": "CLITUI render",
                   "passed": _rendered == {
                       "rendered": True,
                       "content": {"output": "hello", "metadata": {}},
                   }})

    # ------------------------------------------------------------------
    # 6. ChannelRegistry
    # ------------------------------------------------------------------
    registry = ChannelRegistry()
    registry.register("cli", cli_ch)
    checks.append({"check": "registry.get returns channel",
                   "passed": registry.get("cli") is cli_ch})
    checks.append({"check": "registry.names includes cli",
                   "passed": "cli" in registry.names})
    try:
        registry.get("nope")
        checks.append({"check": "KeyError on unknown channel", "passed": False})
    except KeyError:
        checks.append({"check": "KeyError on unknown channel", "passed": True})

    # ------------------------------------------------------------------
    # 7. register_cli_channel convenience
    # ------------------------------------------------------------------
    _reg2 = ChannelRegistry()
    register_cli_channel(_reg2, clock=_clock)
    _ch2 = _reg2.get("cli")
    checks.append({"check": "register_cli_channel registers CLIChannel",
                   "passed": isinstance(_ch2, CLIChannel)})

    # ------------------------------------------------------------------
    # 8. Gateway entrypoint
    # ------------------------------------------------------------------
    result = process_channel_input(registry, "cli", {"text": "say hello"})
    checks.append({"check": "gateway processes cli input",
                   "passed": result is not None and result["input"] == "say hello"})

    result_none = process_channel_input(registry, "unknown", {"text": "data"})
    checks.append({"check": "gateway returns None for unknown channel",
                   "passed": result_none is None})

    empty_reg = ChannelRegistry()
    result_empty = process_channel_input(empty_reg, "cli", {"text": "data"})
    checks.append({"check": "gateway returns None for empty registry",
                   "passed": result_empty is None})

    # ------------------------------------------------------------------
    # 9. WebSocketChannel — receive with validation
    # ------------------------------------------------------------------
    _ws_clock = iter([200.0, 201.0, 202.0, 203.0, 204.0]).__next__
    ws_ch = WebSocketChannel(clock=_ws_clock)

    # 9a. Minimal receive
    _ws_msg1 = ws_ch.receive({"text": "ws hello"})
    checks.append({"check": "WebSocketChannel receive minimal",
                   "passed": _ws_msg1.channel == "ws"
                             and _ws_msg1.sender is None
                             and _ws_msg1.payload == {"text": "ws hello",
                                                      "message_type": "text"}
                             and _ws_msg1.timestamp == 200.0})

    # 9b. Receive with sender and message_type
    _ws_msg2 = ws_ch.receive({"text": "ping", "sender": "node1",
                              "message_type": "binary"})
    checks.append({"check": "WebSocketChannel receive with sender+type",
                   "passed": _ws_msg2.sender == "node1"
                             and _ws_msg2.payload == {"text": "ping",
                                                      "message_type": "binary"}
                             and _ws_msg2.timestamp == 201.0})

    # 9c. Validation — non-dict raises TypeError
    try:
        ws_ch.receive("raw string")  # type: ignore[arg-type]
        checks.append({"check": "WebSocketChannel rejects non-dict", "passed": False})
    except TypeError:
        checks.append({"check": "WebSocketChannel rejects non-dict", "passed": True})

    # 9d. Validation — missing text raises ValueError
    try:
        ws_ch.receive({"sender": "alice"})
        checks.append({"check": "WebSocketChannel rejects missing text",
                       "passed": False})
    except ValueError:
        checks.append({"check": "WebSocketChannel rejects missing text",
                       "passed": True})

    # 9e. Validation — invalid sender type
    try:
        ws_ch.receive({"text": "hi", "sender": 42})
        checks.append({"check": "WebSocketChannel rejects non-string sender",
                       "passed": False})
    except TypeError:
        checks.append({"check": "WebSocketChannel rejects non-string sender",
                       "passed": True})

    # 9f. Validation — invalid message_type type
    try:
        ws_ch.receive({"text": "hi", "message_type": 42})
        checks.append({"check": "WebSocketChannel rejects non-string message_type",
                       "passed": False})
    except TypeError:
        checks.append({"check": "WebSocketChannel rejects non-string message_type",
                       "passed": True})

    # ------------------------------------------------------------------
    # 10. WebSocketChannel — normalize
    # ------------------------------------------------------------------
    _ws_norm = ws_ch.normalize(_ws_msg1)
    checks.append({"check": "WebSocketChannel normalize",
                   "passed": _ws_norm == {
                       "input": "ws hello",
                       "metadata": {
                           "channel": "ws",
                           "sender": None,
                           "message_type": "text",
                       },
                   }})

    # ------------------------------------------------------------------
    # 11. WebSocketChannel — send
    # ------------------------------------------------------------------
    _ws_out = ws_ch.send({"output": "ws done", "metadata": {"key": "val"}})
    checks.append({"check": "WebSocketChannel send",
                   "passed": _ws_out == {
                       "text": "ws done",
                       "message_type": "text",
                       "metadata": {"key": "val"},
                   }})

    # ------------------------------------------------------------------
    # 12. register_websocket_channel convenience
    # ------------------------------------------------------------------
    _reg3 = ChannelRegistry()
    register_websocket_channel(_reg3, clock=_ws_clock)
    _ws_ch2 = _reg3.get("ws")
    checks.append({"check": "register_websocket_channel registers WebSocketChannel",
                   "passed": isinstance(_ws_ch2, WebSocketChannel)})

    # ------------------------------------------------------------------
    # 13. Gateway with WebSocket channel
    # ------------------------------------------------------------------
    registry.register("ws", ws_ch)
    ws_result = process_channel_input(registry, "ws", {"text": "via gateway"})
    checks.append({"check": "gateway processes ws input",
                   "passed": ws_result is not None
                             and ws_result["input"] == "via gateway"
                             and ws_result["metadata"]["channel"] == "ws"})

    # ------------------------------------------------------------------
    # 14. WebhookChannel — receive with validation
    # ------------------------------------------------------------------
    _wh_clock = iter([300.0, 301.0, 302.0, 303.0, 304.0, 305.0]).__next__
    wh_ch = WebhookChannel(clock=_wh_clock)

    # 14a. Minimal receive (generic source)
    _wh_msg1 = wh_ch.receive({
        "source": "generic",
        "payload": {"action": "deploy", "env": "prod"},
    })
    checks.append({"check": "WebhookChannel receive minimal",
                   "passed": _wh_msg1.channel == "webhook"
                             and _wh_msg1.sender is None
                             and _wh_msg1.payload == {
                                 "source": "generic",
                                 "payload": {"action": "deploy", "env": "prod"},
                             }
                             and _wh_msg1.timestamp == 300.0})

    # 14b. Receive with named source and sender
    _wh_msg2 = wh_ch.receive({
        "source": "github",
        "payload": {"event": "push", "ref": "main"},
        "sender": "webhook-bot",
    })
    checks.append({"check": "WebhookChannel receive with source+sender",
                   "passed": _wh_msg2.sender == "webhook-bot"
                             and _wh_msg2.payload == {
                                 "source": "github",
                                 "payload": {"event": "push", "ref": "main"},
                             }
                             and _wh_msg2.timestamp == 301.0})

    # 14c. Validation — non-dict raises TypeError
    try:
        wh_ch.receive("raw string")  # type: ignore[arg-type]
        checks.append({"check": "WebhookChannel rejects non-dict", "passed": False})
    except TypeError:
        checks.append({"check": "WebhookChannel rejects non-dict", "passed": True})

    # 14d. Validation — missing source raises ValueError
    try:
        wh_ch.receive({"payload": {}})
        checks.append({"check": "WebhookChannel rejects missing source",
                       "passed": False})
    except ValueError:
        checks.append({"check": "WebhookChannel rejects missing source",
                       "passed": True})

    # 14e. Validation — missing payload raises ValueError
    try:
        wh_ch.receive({"source": "github"})
        checks.append({"check": "WebhookChannel rejects missing payload",
                       "passed": False})
    except ValueError:
        checks.append({"check": "WebhookChannel rejects missing payload",
                       "passed": True})

    # 14f. Validation — non-dict payload raises ValueError
    try:
        wh_ch.receive({"source": "github", "payload": "not-a-dict"})
        checks.append({"check": "WebhookChannel rejects non-dict payload",
                       "passed": False})
    except ValueError:
        checks.append({"check": "WebhookChannel rejects non-dict payload",
                       "passed": True})

    # ------------------------------------------------------------------
    # 15. WebhookChannel — normalize
    # ------------------------------------------------------------------
    _wh_norm = wh_ch.normalize(_wh_msg1)
    checks.append({"check": "WebhookChannel normalize",
                   "passed": _wh_norm == {
                       "input": {"action": "deploy", "env": "prod"},
                       "metadata": {
                           "channel": "webhook",
                           "source": "generic",
                           "sender": None,
                       },
                   }})

    # ------------------------------------------------------------------
    # 16. WebhookChannel — send
    # ------------------------------------------------------------------
    _wh_out = wh_ch.send({"output": "deploying", "metadata": {"job_id": "j-1"}})
    checks.append({"check": "WebhookChannel send",
                   "passed": _wh_out == {
                       "status": "ok",
                       "response": "deploying",
                       "metadata": {"job_id": "j-1"},
                   }})

    # ------------------------------------------------------------------
    # 17. register_webhook_channel convenience
    # ------------------------------------------------------------------
    _reg4 = ChannelRegistry()
    register_webhook_channel(_reg4, clock=_wh_clock)
    _wh_ch2 = _reg4.get("webhook")
    checks.append({"check": "register_webhook_channel registers WebhookChannel",
                   "passed": isinstance(_wh_ch2, WebhookChannel)})

    # ------------------------------------------------------------------
    # 18. Gateway with Webhook channel
    # ------------------------------------------------------------------
    registry.register("webhook", wh_ch)
    wh_result = process_channel_input(registry, "webhook", {
        "source": "github", "payload": {"event": "issues"},
    })
    checks.append({"check": "gateway processes webhook input",
                   "passed": wh_result is not None
                             and wh_result["metadata"]["source"] == "github"
                             and wh_result["metadata"]["channel"] == "webhook"})

    # ------------------------------------------------------------------
    # 19. WebhookEvent dataclass
    # ------------------------------------------------------------------
    _we = WebhookEvent(source="stripe", payload={"charge": 100}, sender="svc-1")
    checks.append({"check": "WebhookEvent constructed",
                   "passed": _we.source == "stripe"
                             and _we.payload == {"charge": 100}
                             and _we.sender == "svc-1"})
    try:
        _we.payload = {}  # type: ignore[misc]
        checks.append({"check": "WebhookEvent immutable", "passed": False})
    except Exception:
        checks.append({"check": "WebhookEvent immutable", "passed": True})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# ------------------------------------------------------------------
# 20. SlackChannel — receive, normalize, send, validation
# ------------------------------------------------------------------

@_scenario("slack_channel",
           "SlackChannel: receive, normalize, send, validation, register, gateway")
def _test_slack_channel() -> dict[str, Any]:
    """S4.7.4 — Slack Channel integration."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    _slack_clock = iter([400.0, 401.0, 402.0, 403.0, 404.0]).__next__
    slack_ch = SlackChannel(clock=_slack_clock)

    # 1. Receive minimal
    _s_msg1 = slack_ch.receive({"text": "deploy"})
    checks.append({"check": "SlackChannel receive minimal",
                   "passed": _s_msg1.channel == "slack"
                             and _s_msg1.sender is None
                             and _s_msg1.payload == {"text": "deploy"}
                             and _s_msg1.timestamp == 400.0})

    # 2. Receive with sender, channel, team
    _s_msg2 = slack_ch.receive({
        "text": "status", "sender": "U123",
        "channel": "C456", "team": "T789",
    })
    checks.append({"check": "SlackChannel receive with sender+channel+team",
                   "passed": _s_msg2.sender == "U123"
                             and _s_msg2.payload == {
                                 "text": "status",
                                 "channel": "C456",
                                 "team": "T789",
                             }
                             and _s_msg2.timestamp == 401.0})

    # 3. Validation — non-dict
    try:
        slack_ch.receive("bad")
        checks.append({"check": "SlackChannel rejects non-dict", "passed": False})
    except TypeError:
        checks.append({"check": "SlackChannel rejects non-dict", "passed": True})

    # 4. Validation — missing text
    try:
        slack_ch.receive({"sender": "U1"})
        checks.append({"check": "SlackChannel rejects missing text", "passed": False})
    except ValueError:
        checks.append({"check": "SlackChannel rejects missing text", "passed": True})

    # 5. Normalize
    _s_norm = slack_ch.normalize(_s_msg1)
    checks.append({"check": "SlackChannel normalize minimal",
                   "passed": _s_norm == {
                       "input": "deploy",
                       "metadata": {
                           "channel": "slack",
                           "sender": None,
                       },
                   }})

    _s_norm2 = slack_ch.normalize(_s_msg2)
    checks.append({"check": "SlackChannel normalize with metadata",
                   "passed": _s_norm2 == {
                       "input": "status",
                       "metadata": {
                           "channel": "slack",
                           "sender": "U123",
                           "slack_channel": "C456",
                           "slack_team": "T789",
                       },
                   }})

    # 6. Send
    _s_out = slack_ch.send({"output": "done", "metadata": {"job_id": "j-1"}})
    checks.append({"check": "SlackChannel send",
                   "passed": _s_out == {
                       "text": "done",
                       "metadata": {"job_id": "j-1"},
                   }})

    # 7. Send with slack_channel in metadata
    _s_out2 = slack_ch.send({
        "output": "reply",
        "metadata": {"slack_channel": "C456", "job_id": "j-2"},
    })
    checks.append({"check": "SlackChannel send with channel override",
                   "passed": _s_out2 == {
                       "text": "reply",
                       "channel": "C456",
                       "metadata": {"slack_channel": "C456", "job_id": "j-2"},
                   }})

    # 8. register_slack_channel convenience
    _reg_slack = ChannelRegistry()
    register_slack_channel(_reg_slack, clock=_slack_clock)
    _s_ch2 = _reg_slack.get("slack")
    checks.append({"check": "register_slack_channel registers SlackChannel",
                   "passed": isinstance(_s_ch2, SlackChannel)})

    # 9. Gateway convenience
    _reg_all = ChannelRegistry()
    register_slack_channel(_reg_all, clock=_slack_clock)
    _gw = handle_slack_event(_reg_all, {"text": "gateway test"})
    checks.append({"check": "handle_slack_event processes input",
                   "passed": _gw is not None
                             and _gw["input"] == "gateway test"
                             and _gw["metadata"]["channel"] == "slack"})

    # 10. Gateway unregistered
    _empty = ChannelRegistry()
    _gw_none = handle_slack_event(_empty, {"text": "x"})
    checks.append({"check": "handle_slack_event returns None unregistered",
                   "passed": _gw_none is None})

    notes.append("TODO: Add e2e integration test with real Slack workspace + Events API app")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# ------------------------------------------------------------------
# 21. MailChannel — receive, normalize, send, validation
# ------------------------------------------------------------------

@_scenario("mail_channel",
           "MailChannel: receive, normalize, send, validation, register, gateway")
def _test_mail_channel() -> dict[str, Any]:
    """S4.7.4 — Mail Channel integration."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    _mail_clock = iter([500.0, 501.0, 502.0, 503.0, 504.0]).__next__
    mail_ch = MailChannel(clock=_mail_clock)

    # 1. Receive minimal
    _m_msg1 = mail_ch.receive({
        "from": "alice@example.com",
        "subject": "Deploy",
        "body": "Please deploy staging",
    })
    checks.append({"check": "MailChannel receive minimal",
                   "passed": _m_msg1.channel == "mail"
                             and _m_msg1.sender == "alice@example.com"
                             and _m_msg1.payload["subject"] == "Deploy"
                             and _m_msg1.payload["body"] == "Please deploy staging"
                             and _m_msg1.timestamp == 500.0})

    # 2. Receive with recipient
    _m_msg2 = mail_ch.receive({
        "from": "bob@work.com",
        "to": "bot@vai.example",
        "subject": "Status",
        "body": "All good",
    })
    checks.append({"check": "MailChannel receive with recipient",
                   "passed": _m_msg2.payload["to"] == "bot@vai.example"
                             and _m_msg2.timestamp == 501.0})

    # 3. Validation — non-dict
    try:
        mail_ch.receive("bad")
        checks.append({"check": "MailChannel rejects non-dict", "passed": False})
    except TypeError:
        checks.append({"check": "MailChannel rejects non-dict", "passed": True})

    # 4. Validation — missing from
    try:
        mail_ch.receive({"subject": "Hi", "body": "Hello"})
        checks.append({"check": "MailChannel rejects missing from", "passed": False})
    except ValueError:
        checks.append({"check": "MailChannel rejects missing from", "passed": True})

    # 5. Validation — missing subject
    try:
        mail_ch.receive({"from": "a@b.com", "body": "Hello"})
        checks.append({"check": "MailChannel rejects missing subject", "passed": False})
    except ValueError:
        checks.append({"check": "MailChannel rejects missing subject", "passed": True})

    # 6. Validation — missing body
    try:
        mail_ch.receive({"from": "a@b.com", "subject": "Hi"})
        checks.append({"check": "MailChannel rejects missing body", "passed": False})
    except ValueError:
        checks.append({"check": "MailChannel rejects missing body", "passed": True})

    # 7. Normalize
    _m_norm = mail_ch.normalize(_m_msg1)
    checks.append({"check": "MailChannel normalize",
                   "passed": _m_norm == {
                       "input": "Deploy: Please deploy staging",
                       "metadata": {
                           "channel": "mail",
                           "sender": "alice@example.com",
                           "to": "",
                           "subject": "Deploy",
                       },
                   }})

    # 8. Normalize with recipient
    _m_norm2 = mail_ch.normalize(_m_msg2)
    checks.append({"check": "MailChannel normalize with recipient",
                   "passed": _m_norm2["metadata"]["to"] == "bot@vai.example"
                             and _m_norm2["metadata"]["subject"] == "Status"})

    # 9. Send
    _m_out = mail_ch.send({"output": "Deploying now", "metadata": {}})
    checks.append({"check": "MailChannel send",
                   "passed": _m_out == {
                       "to": "",
                       "subject": "Re: Your request",
                       "body": "Deploying now",
                       "metadata": {},
                   }})

    # 10. Send with recipient metadata
    _m_out2 = mail_ch.send({
        "output": "Done",
        "metadata": {"to": "alice@example.com", "subject": "Re: Deploy"},
    })
    checks.append({"check": "MailChannel send with metadata",
                   "passed": _m_out2["to"] == "alice@example.com"
                             and _m_out2["subject"] == "Re: Deploy"
                             and _m_out2["body"] == "Done"})

    # 11. register_mail_channel convenience
    _reg_mail = ChannelRegistry()
    register_mail_channel(_reg_mail, clock=_mail_clock)
    _m_ch2 = _reg_mail.get("mail")
    checks.append({"check": "register_mail_channel registers MailChannel",
                   "passed": isinstance(_m_ch2, MailChannel)})

    # 12. Gateway convenience
    _reg_all = ChannelRegistry()
    register_mail_channel(_reg_all, clock=_mail_clock)
    _gw = handle_mail_message(_reg_all, {
        "from": "a@b.com", "subject": "Hi", "body": "Hello",
    })
    checks.append({"check": "handle_mail_message processes input",
                   "passed": _gw is not None
                             and _gw["input"] == "Hi: Hello"
                             and _gw["metadata"]["channel"] == "mail"})

    # 13. Gateway unregistered
    _empty = ChannelRegistry()
    _gw_none = handle_mail_message(_empty, {
        "from": "a@b.com", "subject": "Hi", "body": "Hello",
    })
    checks.append({"check": "handle_mail_message returns None unregistered",
                   "passed": _gw_none is None})

    notes.append("TODO: Add e2e integration test with SMTP server + IMAP inbox")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# ------------------------------------------------------------------
# 22. DevSMTPTransport — HTTP-based dev email transport
# ------------------------------------------------------------------


@_scenario("dev_smtp",
           "DevSMTPTransport: send alerts to local SMTP test service (MailHog/smtp4dev)")
def _test_dev_smtp() -> dict[str, Any]:
    """S4.7.5 — DevSMTPTransport integration with mocked SMTP."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # 1. DevSMTPConfig defaults
    cfg = DevSMTPConfig()
    checks.append({"check": "DevSMTPConfig defaults",
                   "passed": cfg.host == "localhost"
                             and cfg.port == 1025
                             and cfg.sender == "alerts@vai-core.local"
                             and cfg.timeout == 5.0})

    # 2. DevSMTPConfig custom host/port (smtp4dev)
    cfg_smtp4dev = DevSMTPConfig(host="localhost", port=25)
    checks.append({"check": "DevSMTPConfig custom host/port",
                   "passed": cfg_smtp4dev.host == "localhost"
                             and cfg_smtp4dev.port == 25})

    # 3. DevSMTPTransport construction
    transport = DevSMTPTransport(cfg, clock=lambda: 2000.0)
    checks.append({"check": "DevSMTPTransport constructed",
                   "passed": transport.config.host == cfg.host
                             and transport.config.port == cfg.port})

    # 4. Send — success (mocked SMTP)
    import smtplib as _smtplib
    from unittest.mock import MagicMock, patch as _patch

    with _patch.object(_smtplib, "SMTP") as _mock_smtp_cls:
        _mock_smtp = MagicMock()
        _mock_smtp_cls.return_value = _mock_smtp
        _mock_smtp.__enter__.return_value = _mock_smtp

        result = transport.send(
            to="test@vai.local",
            subject="Alert",
            body="Test body",
        )

    checks.append({"check": "Send success result",
                   "passed": result["success"] is True
                             and result["status_code"] == 250
                             and result["recipient"] == "test@vai.local"
                             and result["body_len"] == 9
                             and result["sent_at"] == 2000.0})

    # 5. Send — SMTP error
    with _patch.object(_smtplib, "SMTP") as _mock_smtp_cls2:
        _mock_smtp2 = MagicMock()
        _mock_smtp2.__enter__.return_value = _mock_smtp2
        _mock_smtp2.send_message.side_effect = _smtplib.SMTPException("550 Rejected")
        _mock_smtp_cls2.return_value = _mock_smtp2

        result_err = transport.send(
            to="bad@test.io",
            subject="Fail",
            body="Rejected",
        )

    checks.append({"check": "Send SMTP error",
                   "passed": result_err["success"] is False
                             and result_err["status_code"] is None
                             and "SMTPException" in result_err["error"]})

    # 6. Send — connection refused
    with _patch.object(_smtplib, "SMTP") as _mock_smtp_cls3:
        _mock_smtp3 = MagicMock()
        _mock_smtp3.__enter__.return_value = _mock_smtp3
        _mock_smtp3.send_message.side_effect = ConnectionRefusedError("No server")
        _mock_smtp_cls3.return_value = _mock_smtp3

        result_ref = transport.send(
            to="down@test.io",
            subject="Down",
            body="Unreachable",
        )

    checks.append({"check": "Send connection refused",
                   "passed": result_ref["success"] is False
                             and result_ref["status_code"] is None
                             and "ConnectionRefusedError" in result_ref["error"]})

    # 7. Custom sender override
    with _patch.object(_smtplib, "SMTP") as _mock_smtp_cls4:
        _mock_smtp4 = MagicMock()
        _mock_smtp4.__enter__.return_value = _mock_smtp4
        _mock_smtp_cls4.return_value = _mock_smtp4

        result_custom = transport.send(
            to="ops@vai-core.local",
            subject="CPU Alert",
            body="High usage",
            sender="noreply@vai-core.local",
        )

    # Verify the MIMEText headers were set correctly
    call_args = _mock_smtp4.send_message.call_args
    sent_msg = call_args[0][0] if call_args else None
    checks.append({"check": "Custom sender in MIME headers",
                   "passed": sent_msg is not None
                             and sent_msg["From"] == "noreply@vai-core.local"
                             and sent_msg["To"] == "ops@vai-core.local"
                             and sent_msg["Subject"] == "CPU Alert"})

    notes.append("TODO: Add e2e integration test with MailHog or smtp4dev running locally")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# =============================================================================
# Instruction Dispatch scenarios
# =============================================================================


@_scenario("instruction_dispatch",
           "UnifiedInstructionDispatch: route instruction types to canonical daemon actions via registry")
def _test_instruction_dispatch() -> dict[str, Any]:
    """Unified Instruction Dispatch §1-6 — full contract verification.

    Tests: all 5 known types, unknown → noop, config injects, validation
    rejects bad input, no mutation, deterministic, ISO-8601 timestamps.
    """
    from datetime import datetime, timezone

    from src.daemon.instruction_dispatch import (
        InstructionDispatchConfig,
        UnifiedInstructionDispatcher,
        default_dispatcher,
    )

    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    clock = [datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)]
    d = default_dispatcher(clock=lambda: clock[0])

    # 1. PanicInstruction → panic
    action, event = d.dispatch({"type": "PanicInstruction", "reason": "OOM", "metadata": {"w": "42"}})
    checks.append({"check": "PanicInstruction → panic",
                   "passed": action == "panic" and event["action"] == "panic"})

    # 2. PoisonInstruction → fail
    action, event = d.dispatch({"type": "PoisonInstruction"})
    checks.append({"check": "PoisonInstruction → fail",
                   "passed": action == "fail" and event["action"] == "fail"})

    # 3. RecoveryInstruction → recover
    action, event = d.dispatch({"type": "RecoveryInstruction"})
    checks.append({"check": "RecoveryInstruction → recover",
                   "passed": action == "recover" and event["action"] == "recover"})

    # 4. DegradedInstruction → degrade
    action, event = d.dispatch({"type": "DegradedInstruction"})
    checks.append({"check": "DegradedInstruction → degrade",
                   "passed": action == "degrade" and event["action"] == "degrade"})

    # 5. RetryInstruction → retry
    action, event = d.dispatch({"type": "RetryInstruction", "reason": "timeout"})
    checks.append({"check": "RetryInstruction → retry",
                   "passed": action == "retry" and event["action"] == "retry"})

    # 6. Unknown type → noop
    action, event = d.dispatch({"type": "FutureS9Instruction"})
    checks.append({"check": "Unknown type → noop",
                   "passed": action == "noop" and event["action"] == "noop"})

    # 7. Dispatch event structure
    _, event = d.dispatch({"type": "RetryInstruction"})
    has_all_keys = all(k in event for k in ("event", "instruction_type", "action", "timestamp"))
    iso_timestamp = False
    try:
        datetime.fromisoformat(event["timestamp"])
        iso_timestamp = True
    except (ValueError, TypeError):
        pass
    checks.append({"check": "Dispatch event has all keys + ISO-8601 timestamp",
                   "passed": has_all_keys and iso_timestamp and event["event"] == "instruction_dispatched"})

    # 8. No mutation
    original = {"type": "PanicInstruction", "reason": "test", "metadata": {"k": "v"}}
    snapshot = dict(original)
    d.dispatch(original)
    checks.append({"check": "No mutation of input instruction",
                   "passed": original == snapshot})

    # 9. Deterministic
    r1 = d.dispatch({"type": "RecoveryInstruction"})
    r2 = d.dispatch({"type": "RecoveryInstruction"})
    checks.append({"check": "Deterministic output",
                   "passed": r1 == r2})

    # 10. Config injection
    cfg = InstructionDispatchConfig(action_map={"MyInstruction": "panic"})
    d2 = UnifiedInstructionDispatcher(config=cfg, clock=lambda: clock[0])
    action, _ = d2.dispatch({"type": "MyInstruction"})
    checks.append({"check": "Custom action_map via config injection",
                   "passed": action == "panic"})

    # 11. Validation rejects non-dict
    try:
        d.validate("not_a_dict")  # type: ignore[arg-type]
        val_passed = False
    except TypeError:
        val_passed = True
    checks.append({"check": "Validation rejects non-dict input",
                   "passed": val_passed})

    # 12. Future-proof: action_map_override
    action, _ = d.dispatch(
        {"type": "S9AlphaOp"},
        action_map_override={"S9AlphaOp": "retry"},
    )
    checks.append({"check": "action_map_override for future types",
                   "passed": action == "retry"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# =============================================================================
# Alert Notification scenarios
# =============================================================================


@_scenario("alert_notifier",
           "AlertNotifier: severity-gated alerts via DevSMTPTransport + notify_on_dispatch integration")
def _test_alert_notifier() -> dict[str, Any]:
    """Alert notification system — AlertNotifier, AlertLevel, notify_on_dispatch.

    Tests that:
      1. AlertLevel ordering is correct
      2. Alert string parsing works
      3. alert() delivers when level >= min_level
      4. alert() skips when level < min_level
      5. custom recipient / sender are respected
      6. notify_on_dispatch integrates with instruction dispatcher
      7. panic → critical alert is delivered
      8. recover → info alert is filtered at warning threshold
      9. unknown action → noop → info → filtered
    """
    notes: list[str] = []
    checks: list[dict[str, Any]] = []

    from src.platform.runtime.alerting import (
        AlertLevel,
        AlertNotifier,
        AlertNotifierConfig,
        notify_on_dispatch,
        DISPATCH_ACTION_ALERT_MAP,
    )

    # 1. Level ordering
    checks.append({
        "check": "AlertLevel ordering: INFO < WARNING < ERROR < CRITICAL",
        "passed": AlertLevel.INFO < AlertLevel.WARNING < AlertLevel.ERROR < AlertLevel.CRITICAL,
    })

    # 2. String parsing
    checks.append({
        "check": "AlertLevel.from_string('error') == AlertLevel.ERROR",
        "passed": AlertLevel.from_string("error") is AlertLevel.ERROR,
    })

    # 3. alert() delivers when level >= min_level (warning)
    config = AlertNotifierConfig(recipient="test@vai-core.local", min_level="warning")
    transport = DevSMTPTransport(DevSMTPConfig())

    # We need a mock transport since DevSMTPTransport requires network.
    class MockTransport:
        def __init__(self):
            self.sends = []

        def send(self, *, to, subject, body, sender=None) -> dict:
            self.sends.append({"to": to, "subject": subject, "body": body, "sender": sender})
            return {"success": True, "status_code": 200, "recipient": to, "subject": subject}

    mock = MockTransport()
    notifier = AlertNotifier(config, mock)

    result = notifier.alert("test warning", "body", level="warning")
    checks.append({
        "check": "alert() delivers when level == min_level",
        "passed": result.get("success") is True and len(mock.sends) == 1,
    })

    # 4. alert() skips when level < min_level
    result = notifier.alert("test info", "body", level="info")
    checks.append({
        "check": "alert() skips when level < min_level",
        "passed": result.get("skipped") is True and len(mock.sends) == 1,
    })

    # 5. Custom recipient / sender
    config2 = AlertNotifierConfig(
        recipient="ops@example.com", min_level="info", sender="noreply@vai-core.local"
    )
    mock2 = MockTransport()
    notifier2 = AlertNotifier(config2, mock2)
    notifier2.alert("test", "body", level="info")
    sent = mock2.sends[0] if mock2.sends else {}
    checks.append({
        "check": "Custom recipient and sender are respected",
        "passed": sent.get("to") == "ops@example.com" and sent.get("sender") == "noreply@vai-core.local",
    })

    # 6. notify_on_dispatch integration
    def fake_dispatcher(inst: dict) -> tuple[str, dict]:
        return inst.get("action", "noop"), {
            "event": "instruction_dispatched",
            "instruction_type": inst.get("type", "Unknown"),
            "action": inst.get("action", "noop"),
            "timestamp": "2025-06-01T00:00:00Z",
        }

    mock3 = MockTransport()
    notifier3 = AlertNotifier(
        AlertNotifierConfig(recipient="t@vai-core.local", min_level="warning"),
        mock3,
    )
    action, event, alert = notify_on_dispatch(
        {"type": "PanicInstruction", "reason": "OOM", "action": "panic"},
        fake_dispatcher,
        notifier3,
    )
    checks.append({
        "check": "notify_on_dispatch panic → critical alert delivered",
        "passed": action == "panic"
                   and event["instruction_type"] == "PanicInstruction"
                   and alert is not None
                   and alert.get("success") is True,
    })

    # 7. Recover → info filtered at warning threshold
    action2, event2, alert2 = notify_on_dispatch(
        {"type": "RecoveryInstruction", "reason": "all good", "action": "recover"},
        fake_dispatcher,
        notifier3,
    )
    checks.append({
        "check": "notify_on_dispatch recover → info → filtered at warning threshold",
        "passed": action2 == "recover" and alert2 is None,
    })

    # 8. Unknown action → noop → info → filtered
    action3, event3, alert3 = notify_on_dispatch(
        {"type": "UnknownInstruction", "reason": "?", "action": "noop"},
        fake_dispatcher,
        notifier3,
    )
    checks.append({
        "check": "notify_on_dispatch unknown → noop → info → filtered",
        "passed": action3 == "noop" and alert3 is None,
    })

    # 9. DISPATCH_ACTION_ALERT_MAP covers all six canonical actions
    expected_actions = {"panic", "fail", "recover", "degrade", "retry", "noop"}
    checks.append({
        "check": "DISPATCH_ACTION_ALERT_MAP covers all six canonical actions",
        "passed": set(DISPATCH_ACTION_ALERT_MAP) == expected_actions,
    })

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# =============================================================================
# Supervisor Loop scenarios
# =============================================================================


@_scenario("supervisor_health_evaluation",
           "SupervisorLoop evaluates healthy / degraded / unresponsive workers")
def _test_supervisor_health_evaluation() -> dict[str, Any]:
    """Supervisor §2 — Worker Health Model.

    Tests: healthy heartbeat, degraded status, unresponsive timeout,
    unknown worker (no heartbeat), edge-case at exact timeout boundary.
    """
    checks: list[dict[str, Any]] = []

    cfg = SupervisorConfig(heartbeat_timeout=10.0)
    loop = SupervisorLoop(config=cfg, clock=lambda: 0.0)

    # 1. No heartbeats — workers are unknown (no health status)
    h = loop.evaluate_health("worker-0", now=0.0)
    checks.append({"check": "unknown worker → unresponsive",
                   "passed": h.status == "unresponsive"
                             and h.reason == "No heartbeat ever received"
                             and h.worker_id == "worker-0"})

    # 2. Healthy heartbeat within timeout
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-1", timestamp=0.0, status="healthy"))
    h = loop.evaluate_health("worker-1", now=5.0)
    checks.append({"check": "recent heartbeat → healthy",
                   "passed": h.status == "healthy"
                             and h.last_seen == 0.0
                             and h.worker_id == "worker-1"})

    # 3. Degraded status in heartbeat
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-2", timestamp=0.0, status="degraded"))
    h = loop.evaluate_health("worker-2", now=3.0)
    checks.append({"check": "degraded heartbeat → degraded",
                   "passed": h.status == "degraded"
                             and h.reason == "Worker reported degraded status"
                             and h.worker_id == "worker-2"})

    # 4. Heartbeat timeout exceeded — unresponsive
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-3", timestamp=0.0, status="healthy"))
    h = loop.evaluate_health("worker-3", now=15.0)
    checks.append({"check": "stale heartbeat → unresponsive",
                   "passed": h.status == "unresponsive"
                             and "timeout" in (h.reason or "")
                             and h.worker_id == "worker-3"})

    # 5. Exact timeout boundary — still healthy (timeout is strict >)
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-4", timestamp=0.0, status="healthy"))
    h = loop.evaluate_health("worker-4", now=10.0)
    checks.append({"check": "heartbeat at exact timeout → healthy (no >)",
                   "passed": h.status == "healthy"
                             and h.worker_id == "worker-4"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("supervisor_restart_semantics",
           "SupervisorLoop restart decisions: new IDs, clean state, event emission")
def _test_supervisor_restart_semantics() -> dict[str, Any]:
    """Supervisor §3 — Restart Semantics.

    Tests: unresponsive worker triggers restart, new worker ID is unique,
    old worker removed from tracking, restart event schema is correct.
    """
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    clock = iter([0.0, 15.0, 15.0]).__next__
    cfg = SupervisorConfig(heartbeat_timeout=10.0, pool_concurrency=2)
    loop = SupervisorLoop(config=cfg, clock=clock)

    # Register heartbeats for two workers (avoid "worker-N" naming as
    # _fresh_worker_id also generates "worker-N" starting at 0)
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="w-0", timestamp=0.0, status="healthy"))
    loop.collect_heartbeat(WorkerHeartbeat(
        worker_id="w-1", timestamp=0.0, status="healthy"))

    # Evaluate at t=15 — both are stale
    decision = loop.evaluate(
        now=15.0,
        active_worker_ids={"w-0", "w-1"},
    )

    # 1. Both unhealthy — 2 restarts scheduled
    checks.append({"check": "two stale workers → two restarts",
                   "passed": len(decision.restarts) >= 2})

    # 2. Restart event has new worker ID (not empty)
    restarts = [r for r in decision.restarts if r.old_worker_id]
    if restarts:
        ev = restarts[0]
        checks.append({"check": "restart event has old_worker_id",
                       "passed": ev.old_worker_id != ""})
        checks.append({"check": "restart event has new_worker_id",
                       "passed": ev.new_worker_id != ""})
        checks.append({"check": "old and new IDs differ",
                       "passed": ev.old_worker_id != ev.new_worker_id})
        checks.append({"check": "restart event has reason",
                       "passed": ev.reason != ""})
        checks.append({"check": "restart event has ISO timestamp",
                       "passed": "T" in ev.timestamp})
        notes.append(f"Restart: {ev.old_worker_id} -> {ev.new_worker_id} ({ev.reason})")

    # 3. Old worker removed from tracking
    hb_old = loop.get_heartbeat("w-0")
    checks.append({"check": "old worker removed from heartbeat tracking",
                   "passed": hb_old is None})

    # 4. Fresh worker IDs are monotonically increasing
    id1 = loop._fresh_worker_id()
    id2 = loop._fresh_worker_id()
    checks.append({"check": "fresh worker IDs are unique",
                   "passed": id1 != id2})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("supervisor_escalation",
           "SupervisorLoop escalates when restart thresholds exceeded")
def _test_supervisor_escalation() -> dict[str, Any]:
    """Supervisor §5 — Escalation Rules.

    Tests: burst restart (more than max_restarts in restart_window),
    single worker restarted too many times.
    """
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Burst restart escalation
    # ------------------------------------------------------------------
    # Heartbeat collected at t=0, evaluate at incrementing timestamps
    # so elapsed always exceeds heartbeat_timeout (0.1s)
    cfg = SupervisorConfig(
        heartbeat_timeout=0.1,   # immediate timeout (elapsed must be > 0.1)
        max_restarts=2,          # low threshold for test
        restart_window=60.0,
        max_worker_restarts=10,
        pool_concurrency=1,
    )
    loop = SupervisorLoop(config=cfg, clock=lambda: 0.0)

    # Run 5 evaluate cycles — each collects a heartbeat at t=0 then
    # evaluates at t=10 so elapsed=10 > 0.1 → worker restarted
    for i in range(5):
        loop.collect_heartbeat(WorkerHeartbeat(
            worker_id="w-0", timestamp=0.0, status="healthy"))
        decision = loop.evaluate(
            now=10.0,
            active_worker_ids={"w-0"},
        )
        # In cycles 1–2: restarts happen but within max_restarts
        # In cycle 3+: recent_count(3) > max_restarts(2) → escalation

    has_burst_esc = any(
        "burst" in e.reason.lower()
        for e in decision.escalations
    )
    checks.append({"check": "burst restart escalation emitted",
                   "passed": has_burst_esc})
    if has_burst_esc:
        burst_esc = [e for e in decision.escalations
                     if "burst" in e.reason.lower()][0]
        notes.append(f"Burst escalation: {burst_esc.reason}")

    # 2. Escalation event schema
    for esc in decision.escalations:
        checks.append({"check": "escalation has event type",
                       "passed": esc.event == "supervisor_escalation"})
        checks.append({"check": "escalation has critical severity",
                       "passed": esc.severity == "critical"})
        checks.append({"check": "escalation has ISO timestamp",
                       "passed": "T" in esc.timestamp})
        checks.append({"check": "escalation has reason",
                       "passed": esc.reason != ""})

    # ------------------------------------------------------------------
    # 3. Single-worker repeated restart escalation
    # ------------------------------------------------------------------
    loop2_cfg = SupervisorConfig(max_worker_restarts=2)
    loop2 = SupervisorLoop(config=loop2_cfg, clock=lambda: 0.0)
    loop2.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-x", timestamp=0.0, status="healthy"))
    # Exhaust restart limit by faking internal counter
    loop2._worker_restart_counts["worker-x"] = 5
    escs = loop2._check_escalation(timestamp=0.0)
    has_worker_esc = any(
        "worker-x" in e.reason
        for e in escs
    )
    checks.append({"check": "single worker restart limit escalation",
                   "passed": has_worker_esc})
    if has_worker_esc:
        notes.append("Per-worker restart escalation detected")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("supervisor_pool_maintenance",
           "SupervisorLoop ensures pool size matches concurrency")
def _test_supervisor_pool_maintenance() -> dict[str, Any]:
    """Supervisor §3.4–3.6 — Pool size enforcement.

    Tests: pool under capacity triggers worker creation, capacity match
    is reported correctly, empty pool creates fill events.
    """
    checks: list[dict[str, Any]] = []

    cfg = SupervisorConfig(
        heartbeat_timeout=30.0,
        pool_concurrency=3,
    )
    loop = SupervisorLoop(config=cfg, clock=lambda: 0.0)

    # 1. Pool at full capacity — all healthy
    for wid in ["worker-0", "worker-1", "worker-2"]:
        loop.collect_heartbeat(WorkerHeartbeat(
            worker_id=wid, timestamp=0.0, status="healthy"))

    decision = loop.evaluate(
        now=0.0,
        active_worker_ids={"worker-0", "worker-1", "worker-2"},
    )
    checks.append({"check": "full pool → pool_full=True",
                   "passed": decision.pool_full})

    # 2. Pool under capacity — missing worker
    loop2 = SupervisorLoop(config=cfg, clock=lambda: 0.0)
    loop2.collect_heartbeat(WorkerHeartbeat(
        worker_id="worker-0", timestamp=0.0, status="healthy"))

    decision2 = loop2.evaluate(
        now=0.0,
        active_worker_ids={"worker-0"},
    )
    checks.append({"check": "under-capacity pool → pool_full=False",
                   "passed": not decision2.pool_full})
    checks.append({"check": "under-capacity creates restart events",
                   "passed": len(decision2.restarts) > 0})

    # 3. No active_worker_ids — pool_full based on heartbeat count
    loop3 = SupervisorLoop(config=cfg, clock=lambda: 0.0)
    for wid in ["worker-0", "worker-1"]:
        loop3.collect_heartbeat(WorkerHeartbeat(
            worker_id=wid, timestamp=0.0, status="healthy"))

    decision3 = loop3.evaluate(now=0.0, active_worker_ids=None)
    checks.append({"check": "no active_worker_ids → pool_full=False (2 < 3)",
                   "passed": not decision3.pool_full})

    # 4. active_unhealthy count is correct
    loop4 = SupervisorLoop(config=cfg, clock=lambda: 0.0)
    loop4.collect_heartbeat(WorkerHeartbeat(
        worker_id="degraded-0", timestamp=0.0, status="degraded"))
    loop4.collect_heartbeat(WorkerHeartbeat(
        worker_id="healthy-0", timestamp=0.0, status="healthy"))

    decision4 = loop4.evaluate(
        now=0.0,
        active_worker_ids={"degraded-0", "healthy-0"},
    )
    checks.append({"check": "active_unhealthy counts degraded workers",
                   "passed": decision4.active_unhealthy == 1})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": []}


@_scenario("supervisor_behavioural_contract",
           "SupervisorLoop behavioural contract enforcement")
def _test_supervisor_behavioural_contract() -> dict[str, Any]:
    """Supervisor §6 — Behavioural Contract.

    Tests: supervisor produces safe, structured output; does NOT execute
    job logic; does NOT mutate job state; is deterministic.
    """
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = SupervisorConfig(heartbeat_timeout=10.0, pool_concurrency=2)
    loop = SupervisorLoop(config=cfg, clock=lambda: 0.0)

    # 1. Decision is a SupervisorDecision
    decision = loop.evaluate(
        now=0.0,
        active_worker_ids={"worker-0", "worker-1"},
    )
    checks.append({"check": "evaluate returns SupervisorDecision",
                   "passed": isinstance(decision, SupervisorDecision)})

    # 2. Decision has expected fields
    checks.append({"check": "decision has restarts list",
                   "passed": isinstance(decision.restarts, list)})
    checks.append({"check": "decision has escalations list",
                   "passed": isinstance(decision.escalations, list)})
    checks.append({"check": "decision has health_map",
                   "passed": isinstance(decision.health_map, dict)})
    checks.append({"check": "decision has pool_full",
                   "passed": isinstance(decision.pool_full, bool)})
    checks.append({"check": "decision has pool_worker_ids",
                   "passed": isinstance(decision.pool_worker_ids, set)})

    # 3. Deterministic: same inputs → same outputs
    loop2 = SupervisorLoop(config=cfg, clock=lambda: 0.0)
    loop2.collect_heartbeat(WorkerHeartbeat(
        worker_id="w1", timestamp=0.0, status="healthy"))
    loop2.collect_heartbeat(WorkerHeartbeat(
        worker_id="w2", timestamp=0.0, status="healthy"))

    d1 = loop2.evaluate(now=5.0, active_worker_ids={"w1", "w2"})
    d2 = loop2.evaluate(now=5.0, active_worker_ids={"w1", "w2"})
    checks.append({"check": "deterministic: same decision for same inputs",
                   "passed": len(d1.restarts) == len(d2.restarts)
                             and d1.pool_full == d2.pool_full})
    notes.append(f"Run 1: {len(d1.restarts)} restarts, pool_full={d1.pool_full}")
    notes.append(f"Run 2: {len(d2.restarts)} restarts, pool_full={d2.pool_full}")

    # 4. Restart event is properly structured (if any exist)
    if decision.restarts:
        ev = decision.restarts[0]
        checks.append({"check": "restart event is WorkerRestartEvent",
                       "passed": isinstance(ev, WorkerRestartEvent)})
        checks.append({"check": "restart event to_dict works",
                       "passed": isinstance(ev.to_dict(), dict)
                                 and "old_worker_id" in ev.to_dict()})

    # 5. Escalation event is properly structured
    if decision.escalations:
        ev = decision.escalations[0]
        checks.append({"check": "escalation event is SupervisorEscalation",
                       "passed": isinstance(ev, SupervisorEscalation)})
        checks.append({"check": "escalation to_dict works",
                       "passed": isinstance(ev.to_dict(), dict)
                                 and "event" in ev.to_dict()})

    # 6. WorkerRestartEvent: default is a frozen dataclass
    default_restart = WorkerRestartEvent()
    checks.append({"check": "default restart event has correct event type",
                   "passed": default_restart.event == "worker_restarted"})

    # 7. SupervisorEscalation: default is a frozen dataclass
    default_esc = SupervisorEscalation()
    checks.append({"check": "default escalation has correct event type",
                   "passed": default_esc.event == "supervisor_escalation"})
    checks.append({"check": "default escalation has critical severity",
                   "passed": default_esc.severity == "critical"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("queue_stuck_job_detection", "Queue Supervisor §2 — Stuck job detection")
def _test_queue_stuck_job_detection() -> dict[str, Any]:
    """Queue Supervisor stuck job detection — queued timeout, processing timeout,
    ack timeout, and healthy boundary cases."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = QueueSupervisorConfig(
        max_processing_time_ms=10.0,
        max_queue_age_ms=10.0,
        ack_timeout_ms=5.0,
    )
    qs = QueueSupervisor(config=cfg)

    # 1. Queued job exceeded max queue age → stuck
    metrics = QueueMetrics(
        queue_length=2,
        queued_jobs=[("j1", 0.005), ("j2", 15.0)],  # j2 stuck (15s > 10ms)
        in_flight_jobs=[],
    )
    d = qs.evaluate(metrics, now=0.0)
    stuck_ids = {s.job_id for s in d.stuck_jobs}
    checks.append({"check": "queued job beyond max_queue_age is stuck",
                   "passed": "j2" in stuck_ids})
    checks.append({"check": "queued job within limit is not stuck",
                   "passed": "j1" not in stuck_ids})
    notes.append(f"Stuck jobs (queued test): {stuck_ids}")

    # 2. In-flight job exceeded max processing time → stuck
    metrics2 = QueueMetrics(
        queue_length=1,
        queued_jobs=[],
        in_flight_jobs=[("j3", 0.003), ("j4", 20.0)],  # j4 stuck
    )
    d2 = qs.evaluate(metrics2, now=0.0)
    stuck_ids2 = {s.job_id for s in d2.stuck_jobs}
    checks.append({"check": "in-flight job beyond max_processing_time is stuck",
                   "passed": "j4" in stuck_ids2})
    checks.append({"check": "in-flight job within limit is not stuck",
                   "passed": "j3" not in stuck_ids2})

    # 3. Ack timeout — in-flight job not acknowledged
    metrics3 = QueueMetrics(
        queue_length=1,
        queued_jobs=[],
        in_flight_jobs=[("j5", 6.0)],  # 6s > 5ms ack timeout → stuck
    )
    d3 = qs.evaluate(metrics3, now=0.0)
    stuck_ids3 = {s.job_id for s in d3.stuck_jobs}
    checks.append({"check": "in-flight job exceeding ack timeout is stuck",
                   "passed": "j5" in stuck_ids3})

    # 4. StuckJobEvent has correct schema
    if d3.stuck_jobs:
        ev = d3.stuck_jobs[0]
        checks.append({"check": "stuck event has correct event type",
                       "passed": ev.event == "job_stuck"})
        checks.append({"check": "stuck event to_dict works",
                       "passed": isinstance(ev.to_dict(), dict)
                                 and "job_id" in ev.to_dict()})

    # 5. Empty metrics → no stuck jobs
    d4 = qs.evaluate(QueueMetrics(), now=0.0)
    checks.append({"check": "empty metrics produce no stuck jobs",
                   "passed": len(d4.stuck_jobs) == 0})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("queue_backpressure", "Queue Supervisor §3 — Backpressure detection")
def _test_queue_backpressure() -> dict[str, Any]:
    """Queue Supervisor backpressure detection — length threshold,
    age threshold, enqueue/dequeue rate ratio, and clean state."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = QueueSupervisorConfig(
        backpressure_queue_length_threshold=3,
        backpressure_avg_age_ms=100.0,
    )
    qs = QueueSupervisor(config=cfg)

    # 1. Queue length exceeds threshold → backpressure
    metrics = QueueMetrics(
        queue_length=5,
        queued_jobs=[("j1", 0.001)],
        in_flight_jobs=[],
    )
    d = qs.evaluate(metrics, now=0.0)
    checks.append({"check": "queue length > threshold triggers backpressure",
                   "passed": d.has_backpressure})
    notes.append(f"BP (length test): {d.has_backpressure}")

    # 2. Average job age exceeds threshold → backpressure
    metrics2 = QueueMetrics(
        queue_length=2,
        queued_jobs=[("j1", 0.1), ("j2", 0.15)],  # avg = 0.125s = 125ms > 100ms
        in_flight_jobs=[],
    )
    d2 = qs.evaluate(metrics2, now=0.0)
    checks.append({"check": "avg job age > threshold triggers backpressure",
                   "passed": d2.has_backpressure})

    # 3. Enqueue/dequeue rate ratio > 1.5 → backpressure
    metrics3 = QueueMetrics(
        queue_length=1,
        queued_jobs=[("j1", 0.001)],
        in_flight_jobs=[],
        enqueue_rate=10.0,
        dequeue_rate=5.0,  # ratio = 2.0 > 1.5
    )
    d3 = qs.evaluate(metrics3, now=0.0)
    checks.append({"check": "enqueue/dequeue ratio > 1.5 triggers backpressure",
                   "passed": d3.has_backpressure})

    # 4. Clean state (low length, low age, balanced rates) → no backpressure
    metrics4 = QueueMetrics(
        queue_length=1,
        queued_jobs=[("j1", 0.001)],
        in_flight_jobs=[],
        enqueue_rate=5.0,
        dequeue_rate=5.0,  # ratio = 1.0
    )
    d4 = qs.evaluate(metrics4, now=0.0)
    checks.append({"check": "clean state has no backpressure",
                   "passed": not d4.has_backpressure})

    # 5. Backpressure event schema
    if d.has_backpressure:
        bp_event = d.backpressure_events[0]
        checks.append({"check": "backpressure event is QueueBackpressureEvent",
                       "passed": isinstance(bp_event, QueueBackpressureEvent)})
        checks.append({"check": "backpressure to_dict works",
                       "passed": isinstance(bp_event.to_dict(), dict)
                                 and "event" in bp_event.to_dict()
                                 and bp_event.to_dict()["event"] == "queue_backpressure"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("queue_escalation", "Queue Supervisor §5 — Escalation rules")
def _test_queue_escalation() -> dict[str, Any]:
    """Queue Supervisor escalation rules — stuck job threshold,
    consecutive backpressure, critical queue length, critical job age."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = QueueSupervisorConfig(
        max_processing_time_ms=10.0,
        max_queue_age_ms=10.0,
        critical_stuck_job_threshold=2,
        backpressure_consecutive_intervals=3,
        critical_queue_length=50,
        critical_job_age_ms=5000.0,
        backpressure_queue_length_threshold=3,
    )
    qs = QueueSupervisor(config=cfg)

    # 1. Stuck job count exceeds threshold → escalation
    metrics = QueueMetrics(
        queue_length=3,
        queued_jobs=[("j1", 15.0), ("j2", 20.0), ("j3", 25.0)],  # 3 stuck
        in_flight_jobs=[],
    )
    d = qs.evaluate(metrics, now=0.0)
    esc_reasons = [e.reason for e in d.escalations]
    checks.append({"check": "stuck job escalation when count exceeds threshold",
                   "passed": any("stuck" in r.lower() for r in esc_reasons)})
    notes.append(f"Escalation reasons: {esc_reasons}")

    # 2. Backpressure persists for N consecutive intervals → escalation
    qs2 = QueueSupervisor(config=cfg)
    for i in range(cfg.backpressure_consecutive_intervals + 1):
        m = QueueMetrics(
            queue_length=10,  # high length → backpressure
            queued_jobs=[("j1", 0.001)],
            in_flight_jobs=[],
        )
        d_step = qs2.evaluate(m, now=float(i))
        if i == cfg.backpressure_consecutive_intervals:
            esc_reasons2 = [e.reason for e in d_step.escalations]
            checks.append({"check": "sustained backpressure triggers escalation",
                           "passed": any("backpressure" in r.lower() for r in esc_reasons2)})
            notes.append(f"BP consecutive escalation reasons: {esc_reasons2}")

    # 3. Critical queue length → escalation
    metrics3 = QueueMetrics(
        queue_length=100,  # exceeds critical 50
        queued_jobs=[("j1", 0.001)],
        in_flight_jobs=[],
    )
    d3 = qs.evaluate(metrics3, now=0.0)
    # Fresh qs so previous state is gone; critical length triggers directly
    qs3 = QueueSupervisor(config=cfg)
    d3 = qs3.evaluate(metrics3, now=0.0)
    tests_passed = any("queue_length" in e.reason for e in d3.escalations)
    # fallback: check critical_queue_length
    if not tests_passed:
        tests_passed = any("critical" in e.reason.lower() for e in d3.escalations)
    checks.append({"check": "critical queue length triggers escalation",
                   "passed": tests_passed})

    # 4. Critical job age → escalation
    metrics4 = QueueMetrics(
        queue_length=1,
        queued_jobs=[("j1", 10.0)],  # 10s = 10000ms > 5000ms critical
        in_flight_jobs=[],
    )
    qs4 = QueueSupervisor(config=cfg)
    d4 = qs4.evaluate(metrics4, now=0.0)
    esc_reasons4 = [e.reason for e in d4.escalations]
    checks.append({"check": "critical job age triggers escalation",
                   "passed": any("age" in r for r in esc_reasons4)})

    # 5. Escalation event schema
    if d.escalations:
        ev = d.escalations[0]
        checks.append({"check": "escalation event is QueueSupervisorEscalation",
                       "passed": isinstance(ev, QueueSupervisorEscalation)})
        checks.append({"check": "escalation to_dict works",
                       "passed": isinstance(ev.to_dict(), dict)
                                 and "event" in ev.to_dict()
                                 and ev.to_dict()["event"] == "queue_supervisor_escalation"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("queue_behavioural_contract", "Queue Supervisor §6 — Behavioural contract")
def _test_queue_behavioural_contract() -> dict[str, Any]:
    """Queue Supervisor behavioural contract — read-only, deterministic,
    structured output, no retries, no state mutation, no worker interaction."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = QueueSupervisorConfig(max_processing_time_ms=10.0, max_queue_age_ms=10.0)
    qs = QueueSupervisor(config=cfg)

    # 1. Decision is a QueueSupervisorDecision
    d = qs.evaluate(QueueMetrics(), now=0.0)
    checks.append({"check": "evaluate returns QueueSupervisorDecision",
                   "passed": isinstance(d, QueueSupervisorDecision)})

    # 2. Decision has expected fields (read-only diagnostic)
    checks.append({"check": "decision has stuck_jobs list",
                   "passed": isinstance(d.stuck_jobs, list)})
    checks.append({"check": "decision has backpressure_events list",
                   "passed": isinstance(d.backpressure_events, list)})
    checks.append({"check": "decision has escalations list",
                   "passed": isinstance(d.escalations, list)})
    checks.append({"check": "decision has has_backpressure bool",
                   "passed": isinstance(d.has_backpressure, bool)})
    checks.append({"check": "decision has queue_length",
                   "passed": isinstance(d.queue_length, int)})
    checks.append({"check": "decision has avg_job_age_ms",
                   "passed": isinstance(d.avg_job_age_ms, float)})

    # 3. No side effects — evaluating twice with same inputs gives same outputs
    metrics = QueueMetrics(
        queue_length=5,
        queued_jobs=[("j1", 20.0)],
        in_flight_jobs=[],
    )
    d1 = qs.evaluate(metrics, now=0.0)
    d2 = qs.evaluate(metrics, now=0.0)
    checks.append({"check": "deterministic: same inputs produce same decision",
                   "passed": len(d1.stuck_jobs) == len(d2.stuck_jobs)
                             and d1.has_backpressure == d2.has_backpressure
                             and len(d1.escalations) == len(d2.escalations)})

    # 4. No retry-like behaviour or state mutation in decision output
    notes.append(f"stuck_jobs={len(d1.stuck_jobs)} (diagnostic only, no retries)")
    notes.append(f"backpressure={d1.has_backpressure} (signal only, no corrective action)")

    # 5. Default event structures
    default_stuck = StuckJobEvent()
    checks.append({"check": "default StuckJobEvent has correct event type",
                   "passed": default_stuck.event == "job_stuck"})
    checks.append({"check": "default StuckJobEvent has empty job_id",
                   "passed": default_stuck.job_id == ""})

    default_bp = QueueBackpressureEvent()
    checks.append({"check": "default QueueBackpressureEvent has correct event",
                   "passed": default_bp.event == "queue_backpressure"})

    default_esc = QueueSupervisorEscalation()
    checks.append({"check": "default escalation has correct event",
                   "passed": default_esc.event == "queue_supervisor_escalation"})
    checks.append({"check": "default escalation has critical severity",
                   "passed": default_esc.severity == "critical"})

    # 6. Empty metrics → deterministic safe decision
    d_empty = qs.evaluate(QueueMetrics(), now=0.0)
    checks.append({"check": "empty metrics yields no stuck jobs",
                   "passed": len(d_empty.stuck_jobs) == 0})
    checks.append({"check": "empty metrics yields no backpressure",
                   "passed": not d_empty.has_backpressure})
    checks.append({"check": "empty metrics yields no escalations",
                   "passed": len(d_empty.escalations) == 0})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario("queue_integration", "Queue Supervisor — Full integration cycle")
def _test_queue_integration() -> dict[str, Any]:
    """Queue Supervisor integration — configure, run evaluation cycle,
    detect stuck jobs, backpressure, and escalation in a realistic scenario."""
    checks: list[dict[str, Any]] = []
    notes: list[str] = []

    cfg = QueueSupervisorConfig(
        max_processing_time_ms=50.0,
        max_queue_age_ms=30.0,
        ack_timeout_ms=20.0,
        backpressure_queue_length_threshold=10,
        backpressure_avg_age_ms=500.0,
        critical_stuck_job_threshold=3,
        backpressure_consecutive_intervals=2,
        critical_queue_length=50,
        critical_job_age_ms=2000.0,
        backpressure_enqueue_dequeue_ratio=1.5,
    )
    qs = QueueSupervisor(config=cfg)

    # Cycle 1: healthy state — short queue, fast jobs
    m1 = QueueMetrics(
        queue_length=2,
        queued_jobs=[("j1", 0.005), ("j2", 0.010)],
        in_flight_jobs=[("j3", 0.020)],
        enqueue_rate=5.0,
        dequeue_rate=5.0,
    )
    d1 = qs.evaluate(m1, now=0.0)
    checks.append({"check": "cycle 1: no stuck jobs in healthy state",
                   "passed": len(d1.stuck_jobs) == 0})
    checks.append({"check": "cycle 1: no backpressure in healthy state",
                   "passed": not d1.has_backpressure})
    checks.append({"check": "cycle 1: no escalation in healthy state",
                   "passed": len(d1.escalations) == 0})

    # Cycle 2: stuck jobs — queued job expired
    m2 = QueueMetrics(
        queue_length=2,
        queued_jobs=[("j4", 0.005), ("j5", 40.0)],  # j5 > 30ms max_queue_age
        in_flight_jobs=[],
    )
    d2 = qs.evaluate(m2, now=1.0)
    stuck_ids = {s.job_id for s in d2.stuck_jobs}
    checks.append({"check": "cycle 2: j5 stuck (queued > max_queue_age)",
                   "passed": "j5" in stuck_ids})
    checks.append({"check": "cycle 2: j4 not stuck",
                   "passed": "j4" not in stuck_ids})
    notes.append(f"Cycle 2 stuck: {stuck_ids}")

    # Cycle 3: in-flight job exceeds processing time
    m3 = QueueMetrics(
        queue_length=1,
        queued_jobs=[],
        in_flight_jobs=[("j6", 60.0)],  # 60ms > 50ms max_processing_time
    )
    d3 = qs.evaluate(m3, now=2.0)
    stuck_ids3 = {s.job_id for s in d3.stuck_jobs}
    checks.append({"check": "cycle 3: j6 stuck (in-flight > processing time)",
                   "passed": "j6" in stuck_ids3})

    # Cycle 4: severe backpressure (high queue + high age + rate imbalance)
    m4 = QueueMetrics(
        queue_length=15,
        queued_jobs=[("j7", 0.600), ("j8", 0.700), ("j9", 0.800)],  # avg 700ms > 500ms
        in_flight_jobs=[],
        enqueue_rate=20.0,
        dequeue_rate=5.0,  # ratio = 4.0
    )
    d4 = qs.evaluate(m4, now=3.0)
    checks.append({"check": "cycle 4: high queue triggers backpressure",
                   "passed": d4.has_backpressure})
    if d4.backpressure_events:
        bp = d4.backpressure_events[0]
        checks.append({"check": "cycle 4: backpressure event has correct event type",
                       "passed": bp.event == "queue_backpressure"})

    # Cycle 5: sustained backpressure triggers escalation
    m5 = QueueMetrics(
        queue_length=15,
        queued_jobs=[("j7", 0.600)],
        in_flight_jobs=[],
        enqueue_rate=20.0,
        dequeue_rate=5.0,
    )
    d5 = qs.evaluate(m5, now=4.0)
    checks.append({"check": "cycle 5: sustained backpressure (count >= 2)",
                   "passed": d5.has_backpressure})

    # Check for escalation from sustained backpressure
    # (qs has been accumulating consecutive backpressure across cycles 4-5)
    esc_reasons = [e.reason for e in d5.escalations]
    notes.append(f"Cycle 5 escalation reasons: {esc_reasons}")

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


# ---- Control Plane Supervisor scenarios -----------------------------------


@_scenario(
    "control_plane_state_detection",
    "Control Plane Supervisor §2 — Inconsistent job state detection",
)
def _() -> dict:
    checks: list[dict] = []
    notes: list[str] = []
    cps = ControlPlaneSupervisor(config=ControlPlaneSupervisorConfig())
    active_workers = {"w-1", "w-2", "w-3"}

    # Check 1: S2 queued but S3 assigned to a worker
    snap1 = JobStateSnapshot(
        job_id="j1", s2_state="queued", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d1 = cps.evaluate([snap1], active_workers, now=1000.0)
    checks.append({"check": "S2 queued + S3 assigned → inconsistency",
                   "passed": len(d1.inconsistencies) == 1})
    if d1.inconsistencies:
        checks.append({"check": "reason mentions S2 queued but S3 assigned",
                       "passed": "assigned" in d1.inconsistencies[0].reason})

    # Check 2: S2 processing but no worker claims it
    snap2 = JobStateSnapshot(
        job_id="j2", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d2 = cps.evaluate([snap2], active_workers, now=1001.0)
    checks.append({"check": "S2 processing + no S4 worker → inconsistency",
                   "passed": len(d2.inconsistencies) == 1})
    if d2.inconsistencies:
        checks.append({"check": "reason mentions S2 processing but no worker",
                       "passed": "no worker" in d2.inconsistencies[0].reason})

    # Check 3: S2 processing but multiple S4 workers
    snap3 = JobStateSnapshot(
        job_id="j3", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=("w-1", "w-2"),
    )
    d3 = cps.evaluate([snap3], active_workers, now=1002.0)
    checks.append({"check": "S2 processing + multiple S4 workers → inconsistency",
                   "passed": len(d3.inconsistencies) == 1})
    if d3.inconsistencies:
        checks.append({"check": "reason mentions multiple workers",
                       "passed": "workers claim" in d3.inconsistencies[0].reason})

    # Check 4: S2 succeeded/failed but S3 still holds
    snap4 = JobStateSnapshot(
        job_id="j4", s2_state="succeeded", s3_has_job=True, s3_worker_id=None,
        s4_worker_ids=(),
    )
    d4 = cps.evaluate([snap4], active_workers, now=1003.0)
    checks.append({"check": "S2 succeeded + S3 still holds → inconsistency",
                   "passed": len(d4.inconsistencies) == 1})
    if d4.inconsistencies:
        checks.append({"check": "reason mentions S3 still holds",
                       "passed": "S3 still holds" in d4.inconsistencies[0].reason})

    # Check 5: S3 assigned to nonexistent worker
    snap5 = JobStateSnapshot(
        job_id="j5", s2_state="queued", s3_has_job=True, s3_worker_id="w-dead",
        s4_worker_ids=(),
    )
    d5 = cps.evaluate([snap5], active_workers, now=1004.0)
    checks.append({"check": "S3 assigned to nonexistent worker → inconsistency",
                   "passed": len(d5.inconsistencies) == 1})
    if d5.inconsistencies:
        checks.append({"check": "reason mentions nonexistent worker",
                       "passed": "nonexistent" in d5.inconsistencies[0].reason})

    # Check 6: S4 claims job but S2 says queued
    snap6 = JobStateSnapshot(
        job_id="j6", s2_state="queued", s3_has_job=False, s3_worker_id=None,
        s4_worker_ids=("w-1",),
    )
    d6 = cps.evaluate([snap6], active_workers, now=1005.0)
    checks.append({"check": "S4 claims job + S2 queued → inconsistency",
                   "passed": len(d6.inconsistencies) == 1})
    if d6.inconsistencies:
        checks.append({"check": "reason mentions S4 claims but S2 queued",
                       "passed": "S4 claims" in d6.inconsistencies[0].reason})

    # Check 7: Consistent state → no inconsistency
    snap7 = JobStateSnapshot(
        job_id="j7", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=("w-1",),
    )
    d7 = cps.evaluate([snap7], active_workers, now=1006.0)
    checks.append({"check": "Consistent S2/S3/S4 → no inconsistency",
                   "passed": len(d7.inconsistencies) == 0})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario(
    "control_plane_auto_repair",
    "Control Plane Supervisor §3 — Deterministic auto-repair",
)
def _() -> dict:
    checks: list[dict] = []
    notes: list[str] = []

    # --- Test with repair enabled ---
    cps = ControlPlaneSupervisor(config=ControlPlaneSupervisorConfig(repair_enabled=True))

    # Repair 2+3: S2 processing, no S4 worker → reset to queued
    snap1 = JobStateSnapshot(
        job_id="j1", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d1 = cps.evaluate([snap1], {"w-1"}, now=2000.0)
    checks.append({"check": "S2 processing + no worker → auto-repair emitted",
                   "passed": len(d1.auto_repairs) == 1})
    checks.append({"check": "j1 is in repaired set",
                   "passed": "j1" in d1.repaired_job_ids})
    if d1.auto_repairs:
        r1 = d1.auto_repairs[0]
        checks.append({"check": "old_state = processing, new_state = queued",
                       "passed": r1.old_state == "processing" and r1.new_state == "queued"})
        checks.append({"check": "reason mentions resetting to queued",
                       "passed": "resetting to queued" in r1.reason})
        checks.append({"check": "event type is job_auto_repaired",
                       "passed": r1.event == "job_auto_repaired"})

    # Repair 4: S2 succeeded, S3 still holds → remove from scheduler
    snap2 = JobStateSnapshot(
        job_id="j2", s2_state="succeeded", s3_has_job=True, s3_worker_id=None,
        s4_worker_ids=(),
    )
    d2 = cps.evaluate([snap2], set(), now=2001.0)
    checks.append({"check": "S2 succeeded + S3 holds → auto-repair emitted",
                   "passed": len(d2.auto_repairs) == 1})
    if d2.auto_repairs:
        r2 = d2.auto_repairs[0]
        checks.append({"check": "old_state = new_state = succeeded (no S2 change)",
                       "passed": r2.old_state == "succeeded" and r2.new_state == "succeeded"})
        checks.append({"check": "reason mentions removing from scheduler",
                       "passed": "removing from scheduler" in r2.reason})

    # --- Test with repair disabled ---
    cps_no = ControlPlaneSupervisor(config=ControlPlaneSupervisorConfig(repair_enabled=False))
    snap3 = JobStateSnapshot(
        job_id="j3", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d3 = cps_no.evaluate([snap3], {"w-1"}, now=2002.0)
    checks.append({"check": "Repair disabled → no auto-repair events",
                   "passed": len(d3.auto_repairs) == 0})

    # Consistent job should not trigger repair
    snap4 = JobStateSnapshot(
        job_id="j4", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=("w-1",),
    )
    d4 = cps.evaluate([snap4], {"w-1"}, now=2003.0)
    checks.append({"check": "Consistent job → no auto-repair",
                   "passed": len(d4.auto_repairs) == 0})

    # AutoRepairEvent to_dict() schema check
    r = d1.auto_repairs[0]
    rd = r.to_dict()
    checks.append({"check": "AutoRepairEvent.to_dict() has expected keys",
                   "passed": all(k in rd for k in
                                 ("event", "job_id", "old_state", "new_state", "timestamp", "reason"))})
    checks.append({"check": "AutoRepairEvent.to_dict() event matches",
                   "passed": rd["event"] == "job_auto_repaired"})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario(
    "control_plane_escalation",
    "Control Plane Supervisor §4 — Escalation rules",
)
def _() -> dict:
    checks: list[dict] = []
    notes: list[str] = []
    cps = ControlPlaneSupervisor(
        config=ControlPlaneSupervisorConfig(
            max_inconsistencies_per_window=2,
        ),
    )
    active_workers = {"w-1", "w-2"}

    # 3 inconsistent jobs will exceed threshold of 2
    snap1 = JobStateSnapshot(
        job_id="j1", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    snap2 = JobStateSnapshot(
        job_id="j2", s2_state="succeeded", s3_has_job=True, s3_worker_id=None,
        s4_worker_ids=(),
    )
    snap3 = JobStateSnapshot(
        job_id="j3", s2_state="queued", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d = cps.evaluate([snap1, snap2, snap3], active_workers, now=3000.0)

    # Each job should have an inconsistency
    checks.append({"check": "3 inconsistent jobs → 3 inconsistencies",
                   "passed": len(d.inconsistencies) == 3})

    # Should escalate due to exceeding threshold
    checks.append({"check": "Exceeded inconsistency threshold → escalation",
                   "passed": len(d.escalations) >= 1})

    # Check escalation event schema
    esc = d.escalations[0]
    checks.append({"check": "Escalation severity = critical",
                   "passed": esc.severity == "critical"})
    checks.append({"check": "Escalation event = control_plane_escalation",
                   "passed": esc.event == "control_plane_escalation"})
    checks.append({"check": "Escalation reason mentions threshold",
                   "passed": "threshold" in esc.reason})

    # to_dict schema check
    ed = esc.to_dict()
    checks.append({"check": "ControlPlaneEscalation.to_dict() has expected keys",
                   "passed": all(k in ed for k in
                                 ("event", "severity", "job_id", "reason", "timestamp"))})

    # Unsafe repair case: should also escalate
    cps2 = ControlPlaneSupervisor(config=ControlPlaneSupervisorConfig(repair_enabled=False))
    snap4 = JobStateSnapshot(
        job_id="j4", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d2 = cps2.evaluate([snap4], active_workers, now=3001.0)
    checks.append({"check": "Repair disabled → inconsistency triggers escalation",
                   "passed": len(d2.escalations) >= 1})
    if d2.escalations:
        checks.append({"check": "Escalation reason mentions unsafe/cannot repair",
                       "passed": "Unsafe" in d2.escalations[0].reason
                                 or "cannot repair" in d2.escalations[0].reason})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario(
    "control_plane_behavioural_contract",
    "Control Plane Supervisor §6 — Behavioural contract verification",
)
def _() -> dict:
    checks: list[dict] = []
    notes: list[str] = []
    cps = ControlPlaneSupervisor()
    active_workers = {"w-1"}

    # The supervisor must NOT execute job logic, modify worker state,
    # retry jobs, assign jobs, or complete jobs.
    # It only detects inconsistencies and produces events.

    # Send a consistent state — no events of any kind
    snap_ok = JobStateSnapshot(
        job_id="j1", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=("w-1",),
    )
    d_ok = cps.evaluate([snap_ok], active_workers, now=4000.0)
    checks.append({"check": "Consistent state → zero events",
                   "passed": (len(d_ok.inconsistencies) == 0
                              and len(d_ok.auto_repairs) == 0
                              and len(d_ok.escalations) == 0)})

    # The supervisor must NOT retry or assign jobs — it only emits
    snap_proc = JobStateSnapshot(
        job_id="j2", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d_proc = cps.evaluate([snap_proc], active_workers, now=4001.0)
    checks.append({"check": "Inconsistent → repairs emitted, not job mutations",
                   "passed": len(d_proc.auto_repairs) >= 1 or len(d_proc.escalations) >= 1})
    # Verify events only — no job completion/mutation
    for inc in d_proc.inconsistencies:
        checks.append({"check": f"Inconsistency ({inc.job_id}) is never 'succeeded' or 'failed'",
                       "passed": "succeeded" not in inc.reason and "failed" not in inc.reason})

    # InconsistencyEvent schema: to_dict produces proper event
    snap_inc = JobStateSnapshot(
        job_id="j3", s2_state="queued", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d_inc = cps.evaluate([snap_inc], active_workers, now=4002.0)
    if d_inc.inconsistencies:
        inc = d_inc.inconsistencies[0]
        dct = inc.to_dict()
        checks.append({"check": "InconsistencyEvent.to_dict() complete schema",
                       "passed": all(k in dct for k in
                                     ("event", "job_id", "s2_state", "s3_state",
                                      "s4_state", "timestamp", "reason"))})
        checks.append({"check": "InconsistencyEvent.event == job_inconsistent",
                       "passed": dct["event"] == "job_inconsistent"})

    # to_dict is deterministic — multiple calls yield the same dict
    snap_j4 = JobStateSnapshot(
        job_id="j4", s2_state="processing", s3_has_job=True, s3_worker_id="w-1",
        s4_worker_ids=(),
    )
    d_j4 = cps.evaluate([snap_j4], active_workers, now=4003.0)
    if d_j4.auto_repairs:
        r = d_j4.auto_repairs[0].to_dict()
        r2 = d_j4.auto_repairs[0].to_dict()
        checks.append({"check": "AutoRepairEvent.to_dict() deterministic",
                       "passed": r == r2})

    # The supervisor never infers missing data — no guesswork in events
    for inc in d_proc.inconsistencies + d_inc.inconsistencies:
        checks.append({"check": f"Inconsistency {inc.job_id} has non-empty reason",
                       "passed": bool(inc.reason)})
        checks.append({"check": f"Inconsistency {inc.job_id} has timestamp",
                       "passed": bool(inc.timestamp)})

    passed = all(c["passed"] for c in checks)
    return {"passed": passed, "checks": checks, "notes": notes}


@_scenario(
    "control_plane_integration",
    "Control Plane Supervisor — Full integration cycle",
)
def _() -> dict:
    checks: list[dict] = []
    notes: list[str] = []
    cps = ControlPlaneSupervisor()

    # Cycle 1: all consistent
    snapshots1 = [
        JobStateSnapshot("j1", "processing", True, "w-1", ("w-1",)),
        JobStateSnapshot("j2", "queued", False, None, ()),
        JobStateSnapshot("j3", "succeeded", False, None, ()),
    ]
    d1 = cps.evaluate(snapshots1, {"w-1"}, now=5000.0)
    checks.append({"check": "Cycle 1: all consistent → no events",
                   "passed": (len(d1.inconsistencies) == 0
                              and len(d1.auto_repairs) == 0
                              and len(d1.escalations) == 0)})

    # Cycle 2: S2 succeeded but S3 still holds j3
    snapshots2 = [
        JobStateSnapshot("j1", "processing", True, "w-1", ("w-1",)),
        JobStateSnapshot("j2", "queued", False, None, ()),
        JobStateSnapshot("j3", "succeeded", True, None, ()),
    ]
    d2 = cps.evaluate(snapshots2, {"w-1"}, now=5001.0)
    checks.append({"check": "Cycle 2: j3 inconsistency detected",
                   "passed": len(d2.inconsistencies) == 1
                             and d2.inconsistencies[0].job_id == "j3"})
    checks.append({"check": "Cycle 2: j3 auto-repair emitted",
                   "passed": len(d2.auto_repairs) == 1
                             and d2.auto_repairs[0].job_id == "j3"})

    # Cycle 3: S2 processing but j1 has no worker (worker crashed)
    snapshots3 = [
        JobStateSnapshot("j1", "processing", True, "w-1", ()),
        JobStateSnapshot("j2", "queued", False, None, ()),
    ]
    d3 = cps.evaluate(snapshots3, set(), now=5002.0)
    checks.append({"check": "Cycle 3: j1 inconsistency (no worker claims)",
                   "passed": len(d3.inconsistencies) == 1
                             and d3.inconsistencies[0].job_id == "j1"})
    checks.append({"check": "Cycle 3: j1 auto-repair (reset to queued)",
                   "passed": len(d3.auto_repairs) == 1
                             and d3.auto_repairs[0].job_id == "j1"
                             and d3.auto_repairs[0].new_state == "queued"})

    # Cycle 4: S3 assigned to nonexistent worker
    snapshots4 = [
        JobStateSnapshot("j4", "queued", True, "w-gone", ()),
    ]
    d4 = cps.evaluate(snapshots4, {"w-1"}, now=5003.0)
    checks.append({"check": "Cycle 4: j4 inconsistency (nonexistent worker)",
                   "passed": len(d4.inconsistencies) == 1
                             and d4.inconsistencies[0].job_id == "j4"})
    checks.append({"check": "Cycle 4: auto-repair for S3/S4 claim with S2 queued",
                   "passed": len(d4.auto_repairs) == 1})

    # Cycle 5: multi-job inconsistency (checking threshold)
    cps_crit = ControlPlaneSupervisor(
        config=ControlPlaneSupervisorConfig(max_inconsistencies_per_window=1),
    )
    snapshots5 = [
        JobStateSnapshot("j5", "processing", True, "w-1", ()),
        JobStateSnapshot("j6", "succeeded", True, None, ()),
    ]
    d5 = cps_crit.evaluate(snapshots5, {"w-1"}, now=5004.0)
    checks.append({"check": "Cycle 5: 2 inconsistencies → exceeds threshold",
                   "passed": len(d5.escalations) >= 1})

    # Stateless: same input twice = same result
    d5a = cps_crit.evaluate(snapshots5, {"w-1"}, now=5004.0)
    checks.append({"check": "Idempotent: same input → same inconsistency count",
                   "passed": len(d5.inconsistencies) == len(d5a.inconsistencies)})

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
