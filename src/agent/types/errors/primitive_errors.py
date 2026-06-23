"""
Phase 3.21.1 — Primitive Error Taxonomy
=========================================

Strongly-typed exception hierarchy for primitive execution failures.

All error types inherit from both PrimitiveError and AgentError, making them:
  - raisable/catchable Python exceptions
  - planner-compatible via the AgentError interface
  - LLM-parsable through clear names and retryable semantics

Hierarchy
---------
PrimitiveError (base)
├── Category A: Execution
│   ├── PrimitiveExecutionError        retryable=maybe  (caller sets)
│   ├── PrimitiveTimeout               retryable=maybe
│   ├── PrimitiveRetryableError        retryable=True
│   ├── PrimitiveNonRetryableError     retryable=False
│   └── PrimitiveSideEffectError       retryable=False
├── Category B: Validation
│   ├── PrimitiveValidationError       retryable=False
│   └── PrimitiveContractError         retryable=False
├── Category C: Privilege & Safety
│   └── PrimitivePrivilegeError        retryable=False
└── Category D: Environment & Dependency
    ├── PrimitiveEnvironmentError      retryable=False
    ├── PrimitiveDependencyError       retryable=maybe
    └── PrimitiveNotFound              retryable=False
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agent.types.errors.AgentError import AgentError


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class PrimitiveError(AgentError, Exception):
    """
    Base class for all primitive-layer errors.

    Carries primitive_name for traceability. Subclasses set a default
    retryable value; callers may override it for context-specific handling.

    Parameters
    ----------
    primitive_name:
        The registered capability name of the failing primitive
        (e.g. "stdlib.file.read").
    message:
        Human-readable description of the failure.
    retryable:
        Whether the planner/executor may retry this primitive call.
        Subclasses set a sensible default; callers may override.
    details:
        Arbitrary JSON-compatible context (input values, stack info, etc.).
    """

    _DEFAULT_RETRYABLE: bool = False

    def __init__(
        self,
        primitive_name: str,
        message: str,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        resolved_retryable = (
            retryable if retryable is not None else self._DEFAULT_RETRYABLE
        )
        AgentError.__init__(
            self,
            type=self.__class__.__name__,
            message=message,
            details={**(details or {}), "primitive_name": primitive_name},
            timestamp=datetime.now(timezone.utc).isoformat(),
            recoverable=resolved_retryable,
        )
        Exception.__init__(self, message)
        self.primitive_name = primitive_name
        self.retryable = resolved_retryable

    def __str__(self) -> str:
        return f"[{self.__class__.__name__}] {self.primitive_name}: {self.message}"


# ---------------------------------------------------------------------------
# Category A — Execution Errors
# ---------------------------------------------------------------------------

class PrimitiveExecutionError(PrimitiveError):
    """
    Generic failure during primitive execution that does not fit a more
    specific category.

    Use when:
        A primitive raises an unclassified exception, or when wrapping a
        third-party library failure where the root cause is unknown.

    Typical causes:
        Unhandled exception in primitive body; library bug; unexpected
        return type; partial execution with no clean failure path.

    Planner handling:
        Retry once with backoff. If repeated, escalate. Check for a
        fallback capability.

    Plan revision:
        Does not imply the plan was wrong. Implies the primitive may be
        unstable. Log to RepairMemory. Demote skill after ≥3 occurrences.
    """

    _DEFAULT_RETRYABLE = False


class PrimitiveTimeout(PrimitiveError):
    """
    The primitive exceeded its allotted execution time.

    Use when:
        An explicit deadline was set and the primitive did not complete
        within it.

    Typical causes:
        Slow external API; large file I/O; network congestion; blocked
        thread; infinite loop in skill logic.

    Planner handling:
        Retry with a longer timeout (if budget allows); fall back to a
        faster alternative capability; abort if time budget is exhausted.

    Plan revision:
        Implies the primitive is slow or the environment is degraded.
        Consider substituting a lighter capability.
    """

    _DEFAULT_RETRYABLE = True


class PrimitiveRetryableError(PrimitiveError):
    """
    A transient failure that is safe and appropriate to retry.

    Use when:
        The primitive failed due to a temporary condition expected to
        resolve — network blip, rate limit, momentary lock contention.

    Typical causes:
        HTTP 429/503; DNS timeout; DB connection pool exhaustion;
        file lock held briefly.

    Planner handling:
        Retry with exponential backoff. Honor a max-retry budget. Do not
        rewrite the plan on first occurrence.

    Plan revision:
        Does not imply the plan is wrong. Does not imply the primitive is
        broken. Only escalate after budget exhausted.
    """

    _DEFAULT_RETRYABLE = True


class PrimitiveNonRetryableError(PrimitiveError):
    """
    A permanent failure where retrying will not help.

    Use when:
        The failure is deterministic — bad input, invalid logic,
        unsupported operation, corrupt data.

    Typical causes:
        Invalid argument passing schema but failing business logic;
        operation explicitly not supported; corrupt or malformed data.

    Planner handling:
        Do not retry. Rewrite the plan: substitute a different capability,
        decompose the step differently, or ask the user.

    Plan revision:
        Implies the plan step is wrong or the capability was misapplied.
        Triggers plan rewrite. May imply a missing capability is needed.
    """

    _DEFAULT_RETRYABLE = False


class PrimitiveSideEffectError(PrimitiveError):
    """
    The primitive produced an unexpected mutation or side effect.

    Use when:
        A primitive expected to be read-only performed a write; a mutation
        was broader than declared; cleanup of a prior step failed.

    Typical causes:
        Undeclared file write; unexpected DB row modification; external
        API call that triggered a callback; cache poisoned by side output.

    Planner handling:
        Abort. Do not retry. Escalate immediately. Attempt rollback if
        checkpointing is available.

    Plan revision:
        Implies the primitive's declared contract is wrong or the
        primitive is unsafe. Rebuild the plan without this primitive.
        Flag for governance review.
    """

    _DEFAULT_RETRYABLE = False


# ---------------------------------------------------------------------------
# Category B — Validation Errors
# ---------------------------------------------------------------------------

class PrimitiveValidationError(PrimitiveError):
    """
    The primitive received input that fails schema validation.

    Use when:
        The primitive's input does not match its declared schema before
        execution begins — type mismatch, missing required field,
        out-of-range value.

    Typical causes:
        LLM-generated plan passed wrong field type; required key missing
        from input dict; enum value not in declared set.

    Planner handling:
        Do not retry with the same input. Rewrite the plan step with
        corrected parameters. Ask the user if the correct value is unknown.

    Plan revision:
        Implies the plan step was constructed incorrectly. Re-examine
        the capability schema. May indicate the LLM hallucinated a field.
    """

    _DEFAULT_RETRYABLE = False


class PrimitiveContractError(PrimitiveError):
    """
    A pre-condition or post-condition of the primitive's contract was violated.

    Use when:
        Inputs were structurally valid but violated a declared semantic
        invariant; or the output did not meet the declared output contract.
        Distinct from PrimitiveValidationError (which is structural).

    Typical causes:
        Pre-condition: "file must exist before read" not met; "user must
        be authenticated" violated.
        Post-condition: output missing a required field; returned value
        failed a business-level invariant.

    Planner handling:
        Do not retry as-is. For pre-condition failures, rewrite the plan
        to satisfy the pre-condition first (insert a prior step). For
        post-condition failures, escalate.

    Plan revision:
        Pre-condition violations imply a missing step in the plan.
        Post-condition violations imply the primitive is unreliable.
    """

    _DEFAULT_RETRYABLE = False


# ---------------------------------------------------------------------------
# Category C — Privilege & Safety Errors
# ---------------------------------------------------------------------------

class PrimitivePrivilegeError(PrimitiveError):
    """
    The primitive attempted an operation it is not authorised to perform.

    Use when:
        A primitive tries to access a resource, invoke a system call, or
        perform an action that its governance declaration does not permit.

    Typical causes:
        Skill tried to write outside its sandbox; attempted network call
        from a network-isolated primitive; tried to invoke another
        primitive directly (bypassing the executor); accessed env vars
        not in its declared allowlist.

    Planner handling:
        Abort. Do not retry. Escalate immediately. Never rewrite the
        plan to grant more privilege.

    Plan revision:
        Implies either the skill has a bug or the plan routed work to the
        wrong primitive. Substitute a higher-privilege primitive that has
        the necessary authorisation. Flag the skill for governance review.
    """

    _DEFAULT_RETRYABLE = False


# ---------------------------------------------------------------------------
# Category D — Environment & Dependency Errors
# ---------------------------------------------------------------------------

class PrimitiveEnvironmentError(PrimitiveError):
    """
    The primitive cannot execute because a required environmental resource
    is absent or misconfigured.

    Use when:
        The primitive's failure is environmental, not logical — the code
        is correct but the environment is not set up correctly.

    Typical causes:
        Missing API_KEY env var; config file not found; required directory
        not mounted; wrong OS platform; database not reachable at startup.

    Planner handling:
        Do not retry immediately. Escalate to the operator — this is a
        deployment or configuration issue. If a fallback environment is
        available, try a different execution context.

    Plan revision:
        Does not imply the plan is wrong. Implies the execution environment
        is wrong. The planner cannot resolve this alone — operator
        intervention required.
    """

    _DEFAULT_RETRYABLE = False


class PrimitiveDependencyError(PrimitiveError):
    """
    The primitive depends on an upstream service, resource, or output that
    is unavailable, failed, or returned an unexpected result.

    Use when:
        The primitive's failure is caused by an external dependency — an
        API that is down, a prior step's output that is missing, a shared
        resource that has gone away.

    Typical causes:
        Upstream REST API returned 500; DB query returned no rows when at
        least one was required; a prior plan step's output was not written
        where expected; message queue consumer timed out.

    Planner handling:
        Retry if the dependency failure is transient. If persistent, fall
        back to an alternative dependency or rewrite the plan to avoid the
        failing resource.

    Plan revision:
        May imply a prior plan step failed silently. Check earlier steps'
        outputs. If the dependency is permanently unavailable, a plan
        rewrite is needed.
    """

    _DEFAULT_RETRYABLE = True


class PrimitiveNotFound(PrimitiveError):
    """
    The executor could not locate the primitive in the skill registry.

    Use when:
        The capability referenced in the plan does not exist, has been
        removed, or was renamed since the plan was generated.

    Typical causes:
        LLM hallucinated a capability name; skill was hot-unloaded between
        plan generation and execution; typo in the plan step action field;
        version mismatch between plan and registry.

    Planner handling:
        Do not retry. Rewrite the plan using semantic discovery fallback
        (Phase 3.19) to find the nearest equivalent capability. If none
        found, ask the user.

    Plan revision:
        Implies the plan referenced a non-existent capability. Trigger
        semantic search. If repeated for the same name, the LLM's
        capability knowledge is stale — consider a context refresh.
    """

    _DEFAULT_RETRYABLE = False


# ---------------------------------------------------------------------------
# Convenience: all primitive error types in declaration order
# ---------------------------------------------------------------------------

ALL_PRIMITIVE_ERROR_TYPES: tuple[type[PrimitiveError], ...] = (
    PrimitiveExecutionError,
    PrimitiveTimeout,
    PrimitiveRetryableError,
    PrimitiveNonRetryableError,
    PrimitiveSideEffectError,
    PrimitiveValidationError,
    PrimitiveContractError,
    PrimitivePrivilegeError,
    PrimitiveEnvironmentError,
    PrimitiveDependencyError,
    PrimitiveNotFound,
)
