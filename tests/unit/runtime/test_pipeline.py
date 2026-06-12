"""Comprehensive unit tests for S4.4.6 Pipeline Abstraction.

Covers:
  - PipelineContext construction
  - PipelineStage structural protocol
  - EvaluatorPipeline: ordering, short-circuit, one-stage requirement
  - CrashRecoveryStage: recovery path, poison gate, normal path
  - IdempotencyStage: token match, token mismatch, no stored job
  - DegradedModeStage: degraded triggered, normal path
  - ExecutionStage: normal cycle, panic, poison, retry, multi-cycle
"""

from __future__ import annotations

from typing import Any

import pytest

from src.platform.runtime.control_plane import ControlPlane
from src.platform.runtime.execution_context import ExecutionContext
from src.platform.runtime.job import Job
from src.platform.runtime.job_state import JobState
from src.platform.runtime.job_store import InMemoryJobStore
from src.platform.runtime.pipeline import (
    CrashRecoveryStage,
    DegradedModeStage,
    EvaluatorPipeline,
    ExecutionStage,
    IdempotencyStage,
    PipelineContext,
    PipelineStage,
)
from src.platform.runtime.recovery.crash_recovery import CrashRecovery
from src.platform.runtime.safety.degraded_mode import DegradedMode
from src.platform.runtime.safety.panic_guard import PanicGuard
from src.platform.runtime.retry.tool_wrapper import (
    PoisonInstruction,
    RetryInstruction,
    ToolRetryWrapper,
)
from src.platform.transport.normalization import ChannelMessage


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def channel_message() -> ChannelMessage:
    return ChannelMessage(input={"text": "hello"}, channel="test")


@pytest.fixture
def cp() -> ControlPlane:
    return ControlPlane(job_store=InMemoryJobStore())


@pytest.fixture
def pending_job(channel_message: ChannelMessage) -> Job:
    return Job(payload=channel_message)


@pytest.fixture
def running_job(pending_job: Job) -> Job:
    pending_job.state = JobState.RUNNING
    pending_job.execution_context = ExecutionContext()
    return pending_job


@pytest.fixture
def ctx(pending_job: Job, cp: ControlPlane) -> PipelineContext:
    """Minimal PipelineContext — PENDING job, no stored_job."""
    return PipelineContext(job=pending_job, control_plane=cp, stored_job=None)


@pytest.fixture
def running_ctx(pending_job: Job, cp: ControlPlane) -> PipelineContext:
    """PipelineContext with a job already in RUNNING state."""
    pending_job.state = JobState.RUNNING
    return PipelineContext(job=pending_job, control_plane=cp)


@pytest.fixture
def ctx_with_store(running_job: Job, cp: ControlPlane) -> PipelineContext:
    """PipelineContext with a RUNNING job that has a stored counterpart."""
    cp.job_store.save(running_job)
    return PipelineContext(job=running_job, control_plane=cp, stored_job=running_job)


@pytest.fixture
def crash_recovery() -> CrashRecovery:
    return CrashRecovery()


@pytest.fixture
def degraded_mode() -> DegradedMode:
    return DegradedMode({"failures": 3, "panics": 1, "crashes": 1})


# ---- helper execution functions for ExecutionStage tests ----


def _fake_success(**kwargs: Any) -> dict:
    return {"done": True, "cognitive_state": {}, "memory": {}, "result": {"echo": "ok"}}


def _fake_always_raises(**kwargs: Any) -> Any:
    raise RuntimeError("Simulated crash")


def _fake_retry_once(**kwargs: Any) -> RetryInstruction:
    return RetryInstruction(delay_seconds=0.01, next_attempt=2)


def _fake_poison(**kwargs: Any) -> PoisonInstruction:
    return PoisonInstruction(is_poison=True, reason="Test poison")


# =========================================================================
# 1. PipelineContext
# =========================================================================


class TestPipelineContext:
    """PipelineContext is a mutable dataclass for pipeline state."""

    def test_construct(self, pending_job: Job, cp: ControlPlane) -> None:
        ctx = PipelineContext(job=pending_job, control_plane=cp)
        assert ctx.job is pending_job
        assert ctx.control_plane is cp
        assert ctx.stored_job is None

    def test_construct_with_stored(
        self, pending_job: Job, running_job: Job, cp: ControlPlane
    ) -> None:
        ctx = PipelineContext(
            job=pending_job, control_plane=cp, stored_job=running_job
        )
        assert ctx.stored_job is running_job


# =========================================================================
# 2. PipelineStage protocol
# =========================================================================


class TestPipelineStageProtocol:
    """Structural subtyping: any object with name + evaluate(ctx) is valid."""

    def test_duck_type_satisfies_protocol(self) -> None:
        class _DuckStage:
            name = "duck"

            def evaluate(self, ctx: object) -> Job | None:
                return None  # continue

        stage: PipelineStage = _DuckStage()  # type: ignore[assignment]
        assert stage.name == "duck"
        assert stage.evaluate(object()) is None

    def test_returns_job_halts(self, pending_job: Job) -> None:
        class _ReturnJobStage:
            name = "return_job"

            def evaluate(self, ctx: object) -> Job | None:
                return pending_job

        stage: PipelineStage = _ReturnJobStage()  # type: ignore[assignment]
        result = stage.evaluate(object())
        assert result is pending_job


# =========================================================================
# 3. EvaluatorPipeline
# =========================================================================


class TestEvaluatorPipeline:
    """EvaluatorPipeline runs stages in order; first non-None wins."""

    def test_empty_pipeline_raises(self) -> None:
        with pytest.raises(ValueError):
            EvaluatorPipeline([])

    def test_single_stage_returns_job(
        self, ctx: PipelineContext, pending_job: Job
    ) -> None:
        class _ReturnJob:
            name = "return"

            def evaluate(self, ctx: object) -> Job | None:
                return pending_job

        pipeline = EvaluatorPipeline([_ReturnJob()])
        result = pipeline.run(ctx)
        assert result is pending_job

    def test_single_stage_none_falls_through(self, ctx: PipelineContext) -> None:
        class _ContinueStage:
            name = "continue"

            def evaluate(self, ctx: object) -> Job | None:
                return None

        pipeline = EvaluatorPipeline([_ContinueStage()])
        result = pipeline.run(ctx)
        # No stage returned a job → falls through to ctx.job
        assert result is ctx.job

    def test_multiple_stages_continue(self, ctx: PipelineContext) -> None:
        """When every stage returns None, the pipeline returns ctx.job."""
        pipeline = EvaluatorPipeline([
            _make_continue_stage("s1"),
            _make_continue_stage("s2"),
            _make_continue_stage("s3"),
        ])
        result = pipeline.run(ctx)
        assert result is ctx.job

    def test_first_non_none_short_circuits(
        self, ctx: PipelineContext, pending_job: Job
    ) -> None:
        """The first stage that returns a Job short-circuits."""

        class _FirstWins:
            name = "first"

            def evaluate(self, ctx: object) -> Job | None:
                return pending_job

        class _ShouldNotRun:
            name = "should_not_run"

            def evaluate(self, ctx: object) -> Job | None:
                raise AssertionError("Should not be called")

        pipeline = EvaluatorPipeline([_FirstWins(), _ShouldNotRun()])
        result = pipeline.run(ctx)
        assert result is pending_job

    def test_stages_execute_in_order(self, ctx: PipelineContext) -> None:
        """Stages run in registration order."""
        events: list[str] = []

        class _Stage:
            def __init__(self, name: str):
                self.name = name

            def evaluate(self, ctx: object) -> Job | None:
                events.append(self.name)
                return None

        pipeline = EvaluatorPipeline([_Stage("A"), _Stage("B"), _Stage("C")])
        pipeline.run(ctx)
        assert events == ["A", "B", "C"]

    def test_middle_stage_can_short_circuit(
        self, ctx: PipelineContext, pending_job: Job
    ) -> None:
        """A middle stage that returns a Job prevents later stages."""

        class _MiddleHalt:
            name = "middle"

            def evaluate(self, ctx: object) -> Job | None:
                return pending_job

        class _ShouldNotRun:
            name = "should_not_run"

            def evaluate(self, ctx: object) -> Job | None:
                raise AssertionError("Should not be called")

        pipeline = EvaluatorPipeline([
            _make_continue_stage("first"),
            _MiddleHalt(),
            _ShouldNotRun(),
        ])
        result = pipeline.run(ctx)
        assert result is pending_job


def _make_continue_stage(stage_name: str) -> PipelineStage:
    """Helper: create a PipelineStage that always returns None."""

    class _Continue:
        name = stage_name

        def evaluate(self, ctx: object) -> Job | None:
            return None

    return _Continue()  # type: ignore[return-value]


# =========================================================================
# 4. CrashRecoveryStage
# =========================================================================


class TestCrashRecoveryStage:
    """Stage 1: crash recovery detection, poison gate, normal init."""

    def test_stage_name(self, crash_recovery: CrashRecovery) -> None:
        stage = CrashRecoveryStage(crash_recovery)
        assert stage.name == "crash_recovery"

    def test_normal_path_returns_none(
        self, ctx: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """PENDING job → None (continue)."""
        stage = CrashRecoveryStage(crash_recovery)
        result = stage.evaluate(ctx)
        assert result is None

    def test_normal_path_transitions_to_running(
        self, ctx: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """PENDING job → mark_running called."""
        stage = CrashRecoveryStage(crash_recovery)
        stage.evaluate(ctx)
        assert ctx.job.state == JobState.RUNNING

    def test_recovery_path_returns_none(
        self, ctx_with_store: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """RUNNING job with checkpoint → recovery, returns None (continue)."""
        stage = CrashRecoveryStage(crash_recovery)
        result = stage.evaluate(ctx_with_store)
        assert result is None

    def test_recovery_increments_crash_count(
        self, ctx_with_store: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """Recovery path increments crash_count."""
        stage = CrashRecoveryStage(crash_recovery)
        before = ctx_with_store.job.crash_count
        stage.evaluate(ctx_with_store)
        assert ctx_with_store.job.crash_count == before + 1

    def test_poison_job_returns_job(
        self, pending_job: Job, cp: ControlPlane, crash_recovery: CrashRecovery
    ) -> None:
        """POISON state → return job immediately (halt)."""
        pending_job.state = JobState.POISON
        ctx = PipelineContext(job=pending_job, control_plane=cp, stored_job=None)
        stage = CrashRecoveryStage(crash_recovery)
        result = stage.evaluate(ctx)
        assert result is pending_job

    def test_poison_skips_mark_running(
        self, pending_job: Job, cp: ControlPlane, crash_recovery: CrashRecovery
    ) -> None:
        """POISON job should not be marked running."""
        pending_job.state = JobState.POISON
        ctx = PipelineContext(job=pending_job, control_plane=cp, stored_job=None)
        stage = CrashRecoveryStage(crash_recovery)
        stage.evaluate(ctx)
        assert pending_job.state == JobState.POISON  # unchanged

    def test_no_recovery_for_pending(
        self, ctx: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """PENDING with no checkpoint → normal path."""
        stage = CrashRecoveryStage(crash_recovery)
        result = stage.evaluate(ctx)
        assert result is None


# =========================================================================
# 5. IdempotencyStage
# =========================================================================


class TestIdempotencyStage:
    """Stage 2: resume-token validation."""

    def test_stage_name(self, crash_recovery: CrashRecovery) -> None:
        stage = IdempotencyStage(crash_recovery)
        assert stage.name == "idempotency"

    def test_no_stored_job_returns_none(
        self, ctx: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """No stored_job → no validation needed."""
        stage = IdempotencyStage(crash_recovery)
        result = stage.evaluate(ctx)
        assert result is None

    def test_stored_no_token_returns_none(
        self, ctx_with_store: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """Stored job with None resume_token → first cycle."""
        ctx_with_store.stored_job = ctx_with_store.job
        ctx_with_store.stored_job.resume_token = None
        stage = IdempotencyStage(crash_recovery)
        result = stage.evaluate(ctx_with_store)
        assert result is None

    def test_token_match_returns_none(
        self, ctx_with_store: PipelineContext, crash_recovery: CrashRecovery
    ) -> None:
        """Matching tokens → safe to advance."""
        ctx_with_store.job.resume_token = "tok-1"
        ctx_with_store.stored_job = ctx_with_store.job
        ctx_with_store.stored_job.resume_token = "tok-1"
        stage = IdempotencyStage(crash_recovery)
        result = stage.evaluate(ctx_with_store)
        assert result is None

    def test_token_mismatch_rehydrates(
        self, cp: ControlPlane, crash_recovery: CrashRecovery
    ) -> None:
        """Mismatch → re-hydrate from stored checkpoint."""
        msg = ChannelMessage(input={"x": 1})
        job = Job(payload=msg, resume_token="tok-new")
        job.state = JobState.RUNNING
        stored_ctx = ExecutionContext()
        stored_ctx.cognitive_state = {"key": "stored"}
        stored = Job(
            payload=msg, resume_token="tok-old", execution_context=stored_ctx
        )
        ctx = PipelineContext(job=job, control_plane=cp, stored_job=stored)
        stage = IdempotencyStage(crash_recovery)
        result = stage.evaluate(ctx)
        assert result is None
        assert ctx.job.execution_context is not None
        assert ctx.job.execution_context.cognitive_state == {"key": "stored"}
        assert ctx.job.resume_token == "tok-old"


# =========================================================================
# 6. DegradedModeStage
# =========================================================================


class TestDegradedModeStage:
    """Stage 3: degraded mode detection."""

    def test_stage_name(self, degraded_mode: DegradedMode) -> None:
        stage = DegradedModeStage(degraded_mode)
        assert stage.name == "degraded_mode"

    def test_normal_path_returns_none(
        self, running_ctx: PipelineContext, degraded_mode: DegradedMode
    ) -> None:
        """No thresholds exceeded → continue."""
        stage = DegradedModeStage(degraded_mode)
        result = stage.evaluate(running_ctx)
        assert result is None

    def test_high_failures_returns_job(
        self, running_ctx: PipelineContext, degraded_mode: DegradedMode
    ) -> None:
        """Consecutive failures exceed threshold → return job."""
        running_ctx.job.consecutive_failures = 5
        stage = DegradedModeStage(degraded_mode)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job

    def test_high_failures_marks_succeeded(
        self, running_ctx: PipelineContext, degraded_mode: DegradedMode
    ) -> None:
        """Degraded → job marked as succeeded with fallback result."""
        running_ctx.job.consecutive_failures = 5
        stage = DegradedModeStage(degraded_mode)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job
        assert result.state == JobState.SUCCEEDED
        assert result.result is not None
        assert result.result.get("fallback") is True

    def test_high_panics_returns_job(
        self, running_ctx: PipelineContext, degraded_mode: DegradedMode
    ) -> None:
        """Panic count exceeds threshold → return job."""
        running_ctx.job.panic_count = 2
        stage = DegradedModeStage(degraded_mode)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job

    def test_high_crashes_returns_job(
        self, running_ctx: PipelineContext, degraded_mode: DegradedMode
    ) -> None:
        """Crash count exceeds threshold → return job."""
        running_ctx.job.crash_count = 2
        stage = DegradedModeStage(degraded_mode)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job

    def test_custom_thresholds(
        self, running_ctx: PipelineContext
    ) -> None:
        """Custom thresholds can be injected."""
        running_ctx.job.consecutive_failures = 10
        high_threshold = DegradedMode(
            {"failures": 100, "panics": 100, "crashes": 100}
        )
        stage = DegradedModeStage(high_threshold)
        result = stage.evaluate(running_ctx)
        assert result is None  # Continue — threshold not exceeded


# =========================================================================
# 7. ExecutionStage
# =========================================================================


class TestExecutionStage:
    """Stage 4: multi-cycle execution loop."""

    def test_stage_name(self) -> None:
        wrapper = ToolRetryWrapper(_fake_success)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        assert stage.name == "execution"

    def test_normal_cycle_returns_job(self, running_ctx: PipelineContext) -> None:
        """Successful execution returns the completed job."""
        wrapper = ToolRetryWrapper(_fake_success)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job

    def test_normal_cycle_transitions_to_succeeded(
        self, running_ctx: PipelineContext
    ) -> None:
        """Successful execution → SUCCEEDED state."""
        wrapper = ToolRetryWrapper(_fake_success)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        result = stage.evaluate(running_ctx)
        assert result.state == JobState.SUCCEEDED

    def test_panic_job_fails(self, running_ctx: PipelineContext) -> None:
        """Runtime error → panic → FAILED state."""
        wrapper = ToolRetryWrapper(_fake_always_raises)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job
        assert result.state == JobState.FAILED

    def test_panic_increments_failure_count(
        self, running_ctx: PipelineContext
    ) -> None:
        """Panic increments consecutive_failures and panic_count."""
        wrapper = ToolRetryWrapper(_fake_always_raises)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        before_cons = running_ctx.job.consecutive_failures
        before_panic = running_ctx.job.panic_count
        stage.evaluate(running_ctx)
        assert running_ctx.job.consecutive_failures == before_cons + 1
        assert running_ctx.job.panic_count == before_panic + 1

    def test_panic_increments_consecutive_failures(
        self, running_ctx: PipelineContext
    ) -> None:
        """Panic increments consecutive_failures."""
        wrapper = ToolRetryWrapper(_fake_always_raises)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        before = running_ctx.job.consecutive_failures
        stage.evaluate(running_ctx)
        assert running_ctx.job.consecutive_failures == before + 1

    def test_retry_instruction_retries(self, running_ctx: PipelineContext) -> None:
        """RetryInstruction → multi-cycle: retries then succeeds."""
        call_count: list[int] = [0]

        def _retry_then_succeed(**kwargs: Any) -> Any:
            call_count[0] += 1
            if call_count[0] < 3:
                return RetryInstruction(
                    delay_seconds=0.01, next_attempt=call_count[0] + 1
                )
            return {
                "done": True,
                "cognitive_state": {},
                "memory": {},
                "result": {"echo": "ok"},
            }

        wrapper = ToolRetryWrapper(_retry_then_succeed)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job
        assert result.state == JobState.SUCCEEDED
        assert call_count[0] == 3

    def test_poison_instruction_poisons(
        self, running_ctx: PipelineContext
    ) -> None:
        """PoisonInstruction → POISON state."""
        wrapper = ToolRetryWrapper(_fake_poison)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        result = stage.evaluate(running_ctx)
        assert result is running_ctx.job
        assert result.state == JobState.POISON

    def test_poison_increments_failure_count(
        self, running_ctx: PipelineContext
    ) -> None:
        """Poison increments failure_count."""
        wrapper = ToolRetryWrapper(_fake_poison)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        before = running_ctx.job.failure_count
        stage.evaluate(running_ctx)
        assert running_ctx.job.failure_count == before + 1

    def test_cycle_trace_appended(self, running_ctx: PipelineContext) -> None:
        """Successful execution appends trace events."""
        wrapper = ToolRetryWrapper(_fake_success)
        guard = PanicGuard()
        stage = ExecutionStage(wrapper, guard)
        stage.evaluate(running_ctx)
        assert len(running_ctx.job.trace) >= 1


# =========================================================================
# 8. Full Pipeline Integration
# =========================================================================


class TestFullPipelineIntegration:
    """End-to-end pipeline with realistic stage configuration."""

    def test_all_stages_healthy_job(
        self, pending_job: Job, cp: ControlPlane
    ) -> None:
        """A PENDING job flows through all stages and completes."""
        ctx = PipelineContext(job=pending_job, control_plane=cp)
        pipeline = EvaluatorPipeline([
            CrashRecoveryStage(CrashRecovery()),
            IdempotencyStage(CrashRecovery()),
            DegradedModeStage(
                DegradedMode({"failures": 3, "panics": 1, "crashes": 1})
            ),
            ExecutionStage(ToolRetryWrapper(_fake_success), PanicGuard()),
        ])
        result = pipeline.run(ctx)
        assert result is pending_job
        assert result.state == JobState.SUCCEEDED

    def test_pipeline_with_panic(
        self, pending_job: Job, cp: ControlPlane
    ) -> None:
        """A job that panics → FAILED state."""
        ctx = PipelineContext(job=pending_job, control_plane=cp)
        pipeline = EvaluatorPipeline([
            CrashRecoveryStage(CrashRecovery()),
            IdempotencyStage(CrashRecovery()),
            DegradedModeStage(
                DegradedMode({"failures": 3, "panics": 1, "crashes": 1})
            ),
            ExecutionStage(
                ToolRetryWrapper(_fake_always_raises), PanicGuard()
            ),
        ])
        result = pipeline.run(ctx)
        assert result.state == JobState.FAILED

    def test_pipeline_degraded_before_execution(
        self, pending_job: Job, cp: ControlPlane
    ) -> None:
        """DegradedModeStage halts before ExecutionStage."""
        pending_job.consecutive_failures = 5
        ctx = PipelineContext(job=pending_job, control_plane=cp)

        class _ShouldNotRun:
            name = "should_not_run"

            def evaluate(self, ctx: object) -> Job | None:
                raise AssertionError("Must not reach execution")

        pipeline = EvaluatorPipeline([
            CrashRecoveryStage(CrashRecovery()),
            IdempotencyStage(CrashRecovery()),
            DegradedModeStage(
                DegradedMode({"failures": 3, "panics": 1, "crashes": 1})
            ),
            _ShouldNotRun(),  # type: ignore[arg-type]
        ])
        result = pipeline.run(ctx)
        # DegradedMode marks succeeded with fallback
        assert result.state == JobState.SUCCEEDED

    def test_pipeline_poison_short_circuits(
        self, pending_job: Job, cp: ControlPlane
    ) -> None:
        """POISON job is caught by CrashRecoveryStage."""
        pending_job.state = JobState.POISON
        ctx = PipelineContext(job=pending_job, control_plane=cp)

        class _ShouldNotRun:
            name = "should_not_run"

            def evaluate(self, ctx: object) -> Job | None:
                raise AssertionError("Must not reach execution")

        pipeline = EvaluatorPipeline([
            CrashRecoveryStage(CrashRecovery()),
            _ShouldNotRun(),  # type: ignore[arg-type]
        ])
        result = pipeline.run(ctx)
        assert result is pending_job
        assert result.state == JobState.POISON  # Unchanged
