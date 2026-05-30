from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TransitionError:
    """
    Structured error produced when a transition is not permitted.

    Per spec §2.5.2:
      { "from": "...", "event": "...", "reason": "...", "allowed": false }

    `event` may be "[direct]" for direct state transitions that have no event trigger.
    `allowed` is always False; included for JSON serialisability parity with the spec.
    """

    from_state: str
    event: str
    reason: str
    allowed: bool = False


@dataclass(frozen=True)
class TransitionResult:
    """
    Outcome of applying a transition (event-driven or direct).

    success=True  → to_state is set, error is None
    success=False → to_state is None, error carries the reason
    """

    success: bool
    to_state: Optional[str]
    error: Optional[TransitionError]
    explanation: str
