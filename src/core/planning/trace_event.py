from __future__ import annotations
from typing import Any, Callable, Dict, Optional

from src.core.types.validation import validate_pure_structure
from src.core.types.hashing import stable_hash
from src.core.types.errors import ValidationError

TraceEvent = Dict[str, Any]
TraceSink = Callable[[TraceEvent], None]


class TraceEventBuilder:
    """
    Unified TraceEvent builder for Stratum 2.

    - Produces JSON-pure, deterministic, append-only trace events
    - Computes canonical_hash from the event payload
    - Optionally forwards events to an observability sink
    """

    def __init__(self, sink: Optional[TraceSink] = None) -> None:
        self._sink = sink

    def _finalise(self, base: Dict[str, Any], timestamp: int) -> TraceEvent:
        event: TraceEvent = {
            "event_type": base["event_type"],
            "timestamp": timestamp,
            "decision": base.get("decision", {}),
            "alternatives": base.get("alternatives", []),
            "validation": base.get("validation", {}),
            "drift": base.get("drift", {}),
            "metadata": base.get("metadata", {}),
        }

        try:
            validate_pure_structure(event)
        except Exception as e:
            raise ValidationError(f"TraceEvent is not pure: {e}")

        event["canonical_hash"] = stable_hash(event)

        if self._sink is not None:
            # Observability hook: forward trace events to the observability layer
            # (e.g., metrics, logs, external tracing).
            self._sink(event)

        return event

    # --- Specific event builders ---

    def classification(
        self,
        *,
        outcome: str,
        reason: str,
        raw_classifier_output: Dict[str, Any],
        timestamp: int,
    ) -> TraceEvent:
        base = {
            "event_type": "classification",
            "decision": {
                "outcome": outcome,
                "reason": reason,
            },
            "alternatives": [],
            "metadata": {
                "raw_classifier_output": raw_classifier_output,
            },
        }
        return self._finalise(base, timestamp)

    def transition(
        self,
        *,
        from_status: str,
        to_status: str,
        timestamp: int,
    ) -> TraceEvent:
        base = {
            "event_type": "transition",
            "decision": {
                "from": from_status,
                "to": to_status,
            },
        }
        return self._finalise(base, timestamp)

    def validation(
        self,
        *,
        input_valid: bool,
        output_valid: bool,
        timestamp: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        base = {
            "event_type": "validation",
            "validation": {
                "input_valid": input_valid,
                "output_valid": output_valid,
                "details": details or {},
            },
        }
        return self._finalise(base, timestamp)

    def drift(
        self,
        *,
        signal: str,
        severity: str,
        timestamp: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        base = {
            "event_type": "drift",
            "drift": {
                "signal": signal,
                "severity": severity,
                "details": details or {},
            },
        }
        return self._finalise(base, timestamp)

    def generic(
        self,
        *,
        event_type: str,
        timestamp: int,
        decision: Optional[Dict[str, Any]] = None,
        alternatives: Optional[list] = None,
        validation: Optional[Dict[str, Any]] = None,
        drift: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        base = {
            "event_type": event_type,
            "decision": decision or {},
            "alternatives": alternatives or [],
            "validation": validation or {},
            "drift": drift or {},
            "metadata": metadata or {},
        }
        return self._finalise(base, timestamp)