from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any
import time

from src.core.types.json_pure import ensure_json_pure


class SignalType(str, Enum):
    DRIFT = "drift"
    STUCK = "stuck"
    UNSAFE = "unsafe"


class SignalSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass(frozen=True)
class GovernedSignal:
    """
    Immutable, JSON‑pure signal emitted by deterministic substrate checks.
    Consumed by 2.5.x reflection, repair, and recovery layers.
    """

    signal_type: SignalType
    severity: SignalSeverity
    confidence: float # 0.0 → 1.0
    source: str # e.g. "subgoals", "segments", "runtime"
    payload: Dict[str, Any]

    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def __post_init__(self):
        ensure_json_pure(self.payload)