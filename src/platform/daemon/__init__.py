"""S4 — Daemon instruction dispatch for Stratum-4."""

from __future__ import annotations

from src.platform.daemon.instruction_dispatch import (
    DEFAULT_ACTION_MAP,
    VALID_ACTIONS,
    InstructionDispatchConfig,
    UnifiedInstructionDispatcher,
    default_dispatcher,
)

__all__ = [
    "DEFAULT_ACTION_MAP",
    "VALID_ACTIONS",
    "InstructionDispatchConfig",
    "UnifiedInstructionDispatcher",
    "default_dispatcher",
]
