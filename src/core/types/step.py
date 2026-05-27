# Stratum: 1 # substrate
# CoreStep: minimal, pure, deterministic representation of a reasoning step.

from dataclasses import dataclass
from typing import Dict, Any

@dataclass(frozen=True)
class CoreStep:
    """
    Minimal structural representation of a reasoning step.
    Pure, deterministic, JSON-serialisable.
    """

    step_type: str
    payload: Dict[str, Any]