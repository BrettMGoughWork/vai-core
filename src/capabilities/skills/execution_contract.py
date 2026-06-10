"""
Phase 3.21.2 — Skill Execution Semantics
==========================================

Pure contract types that declare *how* a skill should be executed.
These are data contracts only — enforcement is handled by the executor.

All types are pure S3 — no LLM, no I/O, deterministic by construction.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Step failure policy constants
# ---------------------------------------------------------------------------

STEP_FAILURE_ABORT = "abort"
"""Stop execution immediately on step failure (default)."""

STEP_FAILURE_CONTINUE = "continue"
"""Skip the failed step and continue with the next."""

STEP_FAILURE_RETRY = "retry"
"""Retry the failed step according to the skill's SkillRetryPolicy."""

STEP_FAILURE_SKIP = "skip"
"""Mark the step as skipped and proceed (only for optional steps)."""

VALID_STEP_FAILURE_POLICIES = frozenset(
    {STEP_FAILURE_ABORT, STEP_FAILURE_CONTINUE, STEP_FAILURE_RETRY, STEP_FAILURE_SKIP}
)


# ---------------------------------------------------------------------------
# Atomicity mode constants
# ---------------------------------------------------------------------------

ATOMICITY_ALL_OR_NOTHING = "all_or_nothing"
"""All steps must succeed; on any failure, compensate and roll back."""

ATOMICITY_BEST_EFFORT = "best_effort"
"""Complete as many steps as possible; partial success is acceptable."""

ATOMICITY_CHECKPOINT = "checkpoint"
"""Resume from the last successful step on retry."""

VALID_ATOMICITY_MODES = frozenset(
    {ATOMICITY_ALL_OR_NOTHING, ATOMICITY_BEST_EFFORT, ATOMICITY_CHECKPOINT}
)


# ---------------------------------------------------------------------------
# SkillRetryPolicy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillRetryPolicy:
    """
    Declarative retry policy for a skill.

    max_attempts:
        Maximum number of execution attempts including the first.
        Must be >= 1. A value of 1 means no retries.
    backoff_factor:
        Multiplier applied to delay between attempts. 1.0 = no backoff,
        2.0 = exponential doubling. Must be >= 1.0.
    retryable_error_types:
        Tuple of error type strings (PrimitiveError subclass names) that
        are eligible for retry. Empty tuple means retry on any error.
    """

    max_attempts: int = 3
    backoff_factor: float = 2.0
    retryable_error_types: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be >= 1, got {self.max_attempts}")
        if self.backoff_factor < 1.0:
            raise ValueError(
                f"backoff_factor must be >= 1.0, got {self.backoff_factor}"
            )


# ---------------------------------------------------------------------------
# SkillCompensationStep
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillCompensationStep:
    """
    A single undo/compensating action to run when a skill fails.

    Compensation steps are executed in reverse order when the skill's
    atomicity mode is ATOMICITY_ALL_OR_NOTHING and execution fails.

    step_name:
        The name of the forward step this compensates for.
    call:
        The primitive name to call for compensation.
    args:
        Arguments to pass to the compensation primitive.
    """

    step_name: str
    call: str
    args: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.step_name:
            raise ValueError("step_name must be non-empty")
        if not self.call:
            raise ValueError("call must be non-empty")
        object.__setattr__(self, "args", copy.deepcopy(self.args))


# ---------------------------------------------------------------------------
# SkillSideEffectBudget
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillSideEffectBudget:
    """
    Declares the maximum allowed side effects for a skill execution.

    Used by the governance layer to enforce mutation budgets.
    A value of -1 means unlimited (no constraint on that dimension).

    max_mutations:
        Maximum total state mutations across all steps.
    max_file_writes:
        Maximum number of file write operations.
    max_network_calls:
        Maximum number of outbound network calls.
    """

    max_mutations: int = -1
    max_file_writes: int = -1
    max_network_calls: int = -1

    def __post_init__(self) -> None:
        for name, val in (
            ("max_mutations", self.max_mutations),
            ("max_file_writes", self.max_file_writes),
            ("max_network_calls", self.max_network_calls),
        ):
            if val < -1:
                raise ValueError(f"{name} must be >= -1 (use -1 for unlimited), got {val}")

    def is_unlimited(self) -> bool:
        """True if all budgets are unconstrained."""
        return (
            self.max_mutations == -1
            and self.max_file_writes == -1
            and self.max_network_calls == -1
        )


# ---------------------------------------------------------------------------
# SkillExecutionContract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillExecutionContract:
    """
    Declarative contract specifying how a skill should be executed.

    This is a pure data type — the executor reads it and enforces it.
    Primitive authors and skill authors declare these semantics; the
    runtime is responsible for honouring them.

    Fields
    ------
    timeout_seconds:
        Maximum wall-clock seconds allowed for the entire skill execution.
        None means no timeout.
    cancellable:
        Whether in-flight execution may be interrupted by a cancellation
        signal from the planner or user.
    retry_policy:
        Retry policy for step-level failures. None means no retries.
    atomicity:
        One of VALID_ATOMICITY_MODES. Governs how partial failure is handled.
    compensation_steps:
        Ordered tuple of compensation steps to run on failure when
        atomicity is ATOMICITY_ALL_OR_NOTHING.
    side_effect_budget:
        Maximum allowed side effects. None means unconstrained.
    step_failure_policy:
        Default failure policy applied to steps that don't declare their own.
    allow_parallel_steps:
        Whether independent steps may be executed concurrently.
        Currently advisory — actual parallelism requires executor support.
    allow_step_skip:
        Whether steps may be skipped (e.g., if their pre-condition is
        not met). Only valid with ATOMICITY_BEST_EFFORT.
    """

    timeout_seconds: Optional[float] = None
    cancellable: bool = False
    retry_policy: Optional[SkillRetryPolicy] = None
    atomicity: str = ATOMICITY_BEST_EFFORT
    compensation_steps: Tuple[SkillCompensationStep, ...] = ()
    side_effect_budget: Optional[SkillSideEffectBudget] = None
    step_failure_policy: str = STEP_FAILURE_ABORT
    allow_parallel_steps: bool = False
    allow_step_skip: bool = False

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be > 0 or None, got {self.timeout_seconds}"
            )
        if self.atomicity not in VALID_ATOMICITY_MODES:
            raise ValueError(
                f"atomicity must be one of {sorted(VALID_ATOMICITY_MODES)}, "
                f"got {self.atomicity!r}"
            )
        if self.step_failure_policy not in VALID_STEP_FAILURE_POLICIES:
            raise ValueError(
                f"step_failure_policy must be one of "
                f"{sorted(VALID_STEP_FAILURE_POLICIES)}, "
                f"got {self.step_failure_policy!r}"
            )
        if (
            self.compensation_steps
            and self.atomicity != ATOMICITY_ALL_OR_NOTHING
        ):
            raise ValueError(
                "compensation_steps are only valid with "
                f"atomicity={ATOMICITY_ALL_OR_NOTHING!r}"
            )
        if self.allow_step_skip and self.atomicity == ATOMICITY_ALL_OR_NOTHING:
            raise ValueError(
                f"allow_step_skip is incompatible with atomicity={ATOMICITY_ALL_OR_NOTHING!r}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillExecutionContract":
        """Construct a SkillExecutionContract from a JSON-compatible dict.

        Supports the subset of fields that can be declared in a skill manifest.
        """
        retry_data = data.get("retry_policy")
        retry_policy = (
            SkillRetryPolicy(
                max_attempts=retry_data.get("max_attempts", 3),
                backoff_factor=retry_data.get("backoff_factor", 2.0),
                retryable_error_types=tuple(
                    retry_data.get("retryable_error_types", [])
                ),
            )
            if retry_data
            else None
        )

        budget_data = data.get("side_effect_budget")
        side_effect_budget = (
            SkillSideEffectBudget(
                max_mutations=budget_data.get("max_mutations", -1),
                max_file_writes=budget_data.get("max_file_writes", -1),
                max_network_calls=budget_data.get("max_network_calls", -1),
            )
            if budget_data
            else None
        )

        comp_steps = tuple(
            SkillCompensationStep(
                step_name=c["step_name"],
                call=c["call"],
                args=c.get("args", {}),
            )
            for c in data.get("compensation_steps", [])
        )

        return cls(
            timeout_seconds=data.get("timeout_seconds"),
            cancellable=data.get("cancellable", False),
            retry_policy=retry_policy,
            atomicity=data.get("atomicity", ATOMICITY_BEST_EFFORT),
            compensation_steps=comp_steps,
            side_effect_budget=side_effect_budget,
            step_failure_policy=data.get("step_failure_policy", STEP_FAILURE_ABORT),
            allow_parallel_steps=data.get("allow_parallel_steps", False),
            allow_step_skip=data.get("allow_step_skip", False),
        )


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SKILL_EXECUTION_CONTRACT = SkillExecutionContract(
    timeout_seconds=None,
    cancellable=False,
    retry_policy=None,
    atomicity=ATOMICITY_BEST_EFFORT,
    compensation_steps=(),
    side_effect_budget=None,
    step_failure_policy=STEP_FAILURE_ABORT,
    allow_parallel_steps=False,
    allow_step_skip=False,
)
