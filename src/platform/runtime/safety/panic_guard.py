"""Panic Guard v1 — Stratum-4 runtime safety.

Last-resort safety wrapper that catches unexpected exceptions inside the
worker execution path and converts them into structured
``StructuredFailure`` envelopes.  Pure logic — no IO, no side effects, no
state mutation.

Panic Guard does NOT:
  - mutate job state
  - write to persistence
  - push to queue
  - retry
  - log or trace

Idempotency rules:
  - Panic always produces the same StructuredFailure for the same exception.
  - Panic must not advance cycle counters.
  - Panic must not mutate ExecutionContext.
  - Panic must not emit lifecycle events.
  - Panic must not retry.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StructuredFailure:
    """Structured failure envelope from an unexpected exception.

    Attributes:
        error_type:  The exception class name (e.g. ``"ValueError"``).
        message:     The exception message string.
        exception:   Fully qualified exception type name
                     (e.g. ``"builtins.ValueError"``).
    """

    error_type: str
    message: str
    exception: str | None = None

    @classmethod
    def from_exception(cls, exc: Exception) -> StructuredFailure:
        """Construct a ``StructuredFailure`` from any Python exception.

        Args:
            exc: The exception to convert.

        Returns:
            A frozen ``StructuredFailure`` with the exception's type name,
            message, and fully qualified type path.
        """
        return cls(
            error_type=type(exc).__name__,
            message=str(exc),
            exception=f"{type(exc).__module__}.{type(exc).__qualname__}",
        )


@dataclass(frozen=True)
class PanicDecision:
    """Result of a panic guard evaluation.

    Attributes:
        is_panic:     ``True`` when a panic (unexpected exception) occurred.
        safe_failure: The structured failure envelope, or ``None``.
        reason:       Human-readable explanation of the panic.
    """

    is_panic: bool
    safe_failure: StructuredFailure | None
    reason: str | None


@dataclass(frozen=True)
class PanicInstruction:
    """Instruction for the worker to safely fail a job after a panic.

    Attributes:
        safe_failure: The structured failure envelope.
        reason:       Why the panic occurred.
    """

    safe_failure: StructuredFailure
    reason: str


# ---------------------------------------------------------------------------
# Panic Guard
# ---------------------------------------------------------------------------


class PanicGuard:
    """Last-resort safety wrapper.

    Wraps a callable so that any unexpected exception is caught and returned
    as a ``PanicDecision`` rather than propagating upward.

    Usage::

        guard = PanicGuard()

        @guard.wrap
        def run_cycle():
            return executor.run_cycle(job, resume_token)

        result = run_cycle()
        if isinstance(result, PanicDecision) and result.is_panic:
            # emit PanicInstruction and recover
            ...
    """

    @staticmethod
    def handle_exception(exc: Exception) -> PanicDecision:
        """Convert an unexpected exception into a ``PanicDecision``.

        Pure deterministic logic:

        1. Convert ``exc`` → ``StructuredFailure.from_exception(exc)``.
        2. Return ``PanicDecision(is_panic=True, safe_failure=..., reason=...)``.

        Args:
            exc: The unexpected exception.

        Returns:
            A ``PanicDecision`` with ``is_panic=True``.
        """
        safe_failure = StructuredFailure.from_exception(exc)
        return PanicDecision(
            is_panic=True,
            safe_failure=safe_failure,
            reason=f"Panic caught: {safe_failure.error_type}",
        )

    def wrap(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Return a wrapped function that catches ALL unexpected exceptions.

        The wrapped function either returns ``fn()``'s normal output or a
        ``PanicDecision`` if an exception occurred.

        Args:
            fn: The callable to wrap.

        Returns:
            A callable with the same signature as ``fn``.
        """

        @functools.wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                return self.handle_exception(e)

        return _wrapped


def default_panic_guard() -> PanicGuard:
    """Factory: return a ``PanicGuard`` instance with default settings."""
    return PanicGuard()
