"""
Phase 2.14.3 — S1 Simulation Fixtures
======================================

Deterministic, JSON-safe fixtures for simulation backend outputs.
No randomness, no inference, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List

# ──────────────────────────────────────────────────────────────────────────────
# Default drift output — used when no drift is detected
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_DRIFT_OUTPUT: Dict[str, Any] = {
    "drift_detected": False,
    "drift_type": None,
    "drift_severity": "minor",
    "drift_detail": {},
}

# ──────────────────────────────────────────────────────────────────────────────
# Default repair output — used when no repair is needed
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_REPAIR_OUTPUT: Dict[str, Any] = {
    "repairs": [],
}

# ──────────────────────────────────────────────────────────────────────────────
# Default reflection output — used when execution completes normally
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_REFLECTION_OUTPUT: Dict[str, Any] = {
    "progress": 1.0,
    "is_complete": True,
    "confidence": 0.9,
    "next_action": "continue",
    "blockers": [],
}

# ──────────────────────────────────────────────────────────────────────────────
# Default plan shaping output — used when no shaping changes are needed
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_PLAN_SHAPING_OUTPUT: Dict[str, Any] = {
    "shaped": True,
    "steps": [],
    "segments": [],
}

# ──────────────────────────────────────────────────────────────────────────────
# Drift fixture templates (for when drift *is* detected)
# ──────────────────────────────────────────────────────────────────────────────

STRUCTURAL_DRIFT_TEMPLATE: Dict[str, Any] = {
    "drift_detected": True,
    "drift_type": "structural",
    "drift_severity": "minor",
    "drift_detail": {"reason": "missing_required_field", "field": None},
}

BEHAVIOURAL_DRIFT_TEMPLATE: Dict[str, Any] = {
    "drift_detected": True,
    "drift_type": "behavioural",
    "drift_severity": "minor",
    "drift_detail": {"reason": "wrong_capability", "expected": None},
}

# ──────────────────────────────────────────────────────────────────────────────
# Repair fixture templates
# ──────────────────────────────────────────────────────────────────────────────

REPAIR_FILL_MISSING_TEMPLATE: Dict[str, Any] = {
    "target": None,
    "action": "fill_default",
    "replacement": None,
}

# ──────────────────────────────────────────────────────────────────────────────
# Default successful output (the "everything is fine" response)
# ──────────────────────────────────────────────────────────────────────────────

def make_default_output() -> Dict[str, Any]:
    """Return the default successful output that the simulation assumes."""
    return {
        **DEFAULT_DRIFT_OUTPUT,
        **DEFAULT_REPAIR_OUTPUT,
        **DEFAULT_REFLECTION_OUTPUT,
        **DEFAULT_PLAN_SHAPING_OUTPUT,
        "quality": {"below_threshold": False},
        "structural_deviation": {},
    }


def make_minimal_plan_context() -> Dict[str, Any]:
    """Return a minimal valid plan_context dict for testing."""
    return {
        "subgoal": {"index": 0, "state": "pending"},
        "segment": {"index": 0, "state": "pending"},
        "agent": {"is_complete": False},
    }
