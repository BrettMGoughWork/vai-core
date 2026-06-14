"""Unified Instruction Dispatch — maps instruction objects to canonical daemon actions.

This module is the single point of decision for instruction routing in Stratum-4.
It uses a configurable registry (INSTRUCTION_ACTION_MAP) so that new instruction
types can be added by configuration alone — no code changes required.

Usage
-----
    dispatcher = default_dispatcher()
    action, event = dispatcher.dispatch({
        "type": "PanicInstruction",
        "reason": "Worker exceeded max memory",
        "metadata": {"worker_id": "w-42"},
    })
    assert action == "panic"
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Default dispatch registry
# ---------------------------------------------------------------------------

DEFAULT_ACTION_MAP: dict[str, str] = {
    "PanicInstruction": "panic",
    "PoisonInstruction": "fail",
    "RecoveryInstruction": "recover",
    "DegradedInstruction": "degrade",
    "RetryInstruction": "retry",
}

VALID_ACTIONS = frozenset({"fail", "retry", "recover", "degrade", "panic", "noop"})

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class InstructionDispatchConfig:
    """Configuration for the instruction dispatcher registry.

    Attributes:
        action_map: Mapping of instruction type → canonical daemon action.
            Unknown types resolve to ``"noop"``.
    """

    action_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ACTION_MAP))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class UnifiedInstructionDispatcher:
    """Deterministic, side-effect-free instruction-to-action dispatcher.

    The dispatcher never inspects instruction *content* — it only reads the
    ``type`` key and consults the registry.  This guarantees forward
    compatibility with S4.9+ instruction additions.
    """

    def __init__(
        self,
        config: InstructionDispatchConfig | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config or InstructionDispatchConfig()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def validate(instruction: Any) -> dict[str, Any]:
        """Validate that *instruction* conforms to the dispatch schema.

        Returns the instruction dict unchanged (no mutation).

        Raises:
            TypeError: If structure is wrong.
            ValueError: If required fields are missing or empty.
        """
        if not isinstance(instruction, dict):
            raise TypeError(
                f"Instruction must be a dict, got {type(instruction).__name__}"
            )
        if "type" not in instruction:
            raise ValueError("Instruction missing required key 'type'")
        if not isinstance(instruction["type"], str):
            raise TypeError(
                f"Instruction 'type' must be a string, "
                f"got {type(instruction['type']).__name__}"
            )
        if not instruction["type"]:
            raise ValueError("Instruction 'type' must not be empty")
        if "reason" in instruction and not isinstance(instruction["reason"], str):
            raise TypeError(
                f"Instruction 'reason' must be a string, "
                f"got {type(instruction['reason']).__name__}"
            )
        if "metadata" in instruction and not isinstance(instruction["metadata"], dict):
            raise TypeError(
                f"Instruction 'metadata' must be a dict, "
                f"got {type(instruction['metadata']).__name__}"
            )
        return instruction

    @property
    def config(self) -> InstructionDispatchConfig:
        """Expose the underlying config for introspection."""
        return self._config

    def dispatch(
        self,
        instruction: dict[str, Any],
        *,
        action_map_override: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Map an instruction object to a canonical daemon action.

        The dispatch algorithm:

        1. Validate the instruction schema.
        2. Extract ``instruction["type"]``.
        3. Look up the action in the registry.
        4. If unknown → use ``"noop"``.
        5. Unrecognised actions in registry → ``"noop"``.
        6. Emit a dispatch event.
        7. Return ``(action, dispatch_event)``.

        Args:
            instruction: An instruction dict with at least a ``"type"`` key.
            action_map_override: Optional temporary override of the registry
                (for testing or dynamic scoping).

        Returns:
            A 2-tuple ``(action, dispatch_event)``.

        Raises:
            TypeError: If *instruction* is not a dict.
            ValueError: If ``type`` is missing or empty.
        """
        validated = self.validate(instruction)
        _map = action_map_override if action_map_override is not None else self._config.action_map

        action = _map.get(validated["type"], "noop")
        if action not in VALID_ACTIONS:
            action = "noop"

        event = {
            "event": "instruction_dispatched",
            "instruction_type": validated["type"],
            "action": action,
            "timestamp": self._clock().isoformat(),
        }
        return action, event


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def default_dispatcher(
    *,
    clock: Callable[[], datetime] | None = None,
) -> UnifiedInstructionDispatcher:
    """Return a ``UnifiedInstructionDispatcher`` with the default registry."""
    return UnifiedInstructionDispatcher(clock=clock)
