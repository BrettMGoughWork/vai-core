"""
Phase 5.9 — Human-in-the-Loop Interaction Manager
===================================================

Clean wrapper around the engine's built-in pause/resume mechanism.
Provides typed interaction requests, input validation against schema,
timeout enforcement, and pending-request tracking.

The engine and supervisor already handle the core pause/resume flow.
This layer adds the missing polish:
  - InteractionRequest / InteractionResponse dataclasses
  - Schema validation before resume
  - Timeout expiry
  - Centralised pending-request registry
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.agent.workflow.engine import (
    StepOutcome,
    WorkflowEngine,
    WorkflowExecutionState,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InteractionRequest:
    """A request for human input, created when a workflow hits a user_input step."""

    request_id: str
    instance_id: str
    step_id: str
    prompt: str
    input_schema: Dict[str, Any]
    timeout_seconds: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

    def __post_init__(self) -> None:
        if self.expires_at is None and self.timeout_seconds is not None:
            object.__setattr__(self, "expires_at", self.created_at + self.timeout_seconds)


@dataclass
class InteractionResponse:
    """A validated response to an InteractionRequest."""

    request_id: str
    data: Dict[str, Any]
    received_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class UserInteractionManager:
    """Manages pending human-input interactions for workflow instances.

    Thread-safe note: this class is not thread-safe by itself. The caller
    (Supervisor) is expected to serialise access.
    """

    def __init__(self, engine: WorkflowEngine) -> None:
        self._engine = engine
        self._pending: Dict[str, InteractionRequest] = {}  # request_id → request
        self._responses: Dict[str, InteractionResponse] = {}  # request_id → response

    # ── Public API ──────────────────────────────────────────────────────

    def request_input(
        self,
        instance_id: str,
        step_id: str,
        prompt: str,
        schema: Dict[str, Any],
        *,
        timeout_seconds: Optional[float] = None,
    ) -> InteractionRequest:
        """Register a pending input request and return it.

        The caller (Supervisor) is responsible for persisting the
        workflow state in WAITING mode.  This method only tracks the
        interaction metadata.
        """
        request_id = _make_request_id(instance_id, step_id)
        now = time.time()
        expires_at = (now + timeout_seconds) if timeout_seconds is not None else None

        req = InteractionRequest(
            request_id=request_id,
            instance_id=instance_id,
            step_id=step_id,
            prompt=prompt,
            input_schema=schema,
            timeout_seconds=timeout_seconds,
            created_at=now,
            expires_at=expires_at,
        )
        self._pending[request_id] = req
        return req

    def submit_response(
        self,
        request_id: str,
        data: Dict[str, Any],
        state: WorkflowExecutionState,
    ) -> Tuple[bool, Optional[str], Optional[Tuple[WorkflowExecutionState, StepOutcome]]]:
        """Validate ``data`` against the request's schema and resume.

        Returns ``(valid, error_msg, (new_state, outcome))`` where
        ``valid`` is ``True`` only when validation passes *and* the
        engine successfully resumes.

        When ``valid`` is ``False``, ``error_msg`` contains a
        human-readable description and the engine is **not** called.
        """
        req = self._pending.get(request_id)
        if req is None:
            return False, f"Unknown request_id {request_id!r}", None

        # ── Validate ────────────────────────────────────────────────
        error = _validate_against_schema(data, req.input_schema)
        if error is not None:
            return False, error, None

        # ── Timeout check ───────────────────────────────────────────
        if req.expires_at is not None and time.time() > req.expires_at:
            self._expire_request(request_id)
            return False, "Interaction request has expired", None

        # ── Resume ──────────────────────────────────────────────────
        new_state, outcome = self._engine.resume_with_input(state, _serialise(data))

        self._responses[request_id] = InteractionResponse(
            request_id=request_id,
            data=data,
        )
        del self._pending[request_id]
        return True, None, (new_state, outcome)

    def get_pending(self) -> List[InteractionRequest]:
        """Return all pending interaction requests (excluding expired)."""
        self._purge_expired()
        return list(self._pending.values())

    def cancel_request(self, request_id: str, state: WorkflowExecutionState) -> bool:
        """Cancel a pending request and fail the workflow step.

        Returns ``True`` if the request existed and was cancelled.
        """
        req = self._pending.pop(request_id, None)
        if req is None:
            return False
        self._engine.fail_step(
            state, req.step_id,
            f"Cancelled by user (request_id={request_id})",
        )
        return True

    def get_request(
        self, request_id: str,
    ) -> Optional[InteractionRequest]:
        """Look up a single pending request by ID."""
        return self._pending.get(request_id)

    # ── Internal helpers ────────────────────────────────────────────────

    def _purge_expired(self) -> None:
        """Remove expired requests from the pending registry."""
        now = time.time()
        expired = [
            rid
            for rid, req in self._pending.items()
            if req.expires_at is not None and now > req.expires_at
        ]
        for rid in expired:
            self._expire_request(rid)

    def _expire_request(self, request_id: str) -> None:
        """Remove an expired request without notifying the engine.

        The engine timeout path is handled separately — the Supervisor
        checks ``outcome.type == "timeout"`` during the workflow loop.
        This method simply cleans up the pending registry.
        """
        self._pending.pop(request_id, None)

    def __len__(self) -> int:
        self._purge_expired()
        return len(self._pending)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

# Simple supported types for input_schema validation.
_VALID_TYPES = {"string", "number", "boolean", "array"}


def _validate_against_schema(
    data: Dict[str, Any],
    schema: Dict[str, Any],
) -> Optional[str]:
    """Validate ``data`` against a JSON-Schema-like dict.

    Supports:
      - ``type: object`` with ``properties`` and ``required`` fields
      - Property types: ``string``, ``number``, ``boolean``, ``array``
      - ``enum`` constraints on string properties
      - ``items.type`` for array items
      - ``nullable: true`` (property value may be None)

    Returns ``None`` on success, or an error message string on failure.
    """
    if not schema:
        return None  # no schema = no validation

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        # Top-level non-object schemas — validate directly
        return _validate_value(data, schema, "$root")

    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    # ── Check required fields are present ───────────────────────────
    for field_name in required:
        if field_name not in data or data[field_name] is None:
            return f"Missing required field: {field_name!r}"

    # ── Check no extra fields beyond schema ─────────────────────────
    for key in data:
        if key not in properties:
            return f"Unexpected field: {key!r}"

    # ── Validate each present field against its type ────────────────
    for field_name, prop_schema in properties.items():
        if field_name not in data:
            continue
        # Check nullable
        if prop_schema.get("nullable") and data[field_name] is None:
            continue
        error = _validate_value(data[field_name], prop_schema, field_name)
        if error is not None:
            return error

    return None


def _validate_value(
    value: Any,
    schema: Dict[str, Any],
    path: str,
) -> Optional[str]:
    """Validate a single value against a property schema."""
    expected_type = schema.get("type", "string")

    if expected_type not in _VALID_TYPES:
        return None  # skip unknown types

    # ── None check ──────────────────────────────────────────────────
    if value is None:
        if schema.get("nullable"):
            return None
        return f"Field {path!r} is required"

    # ── Type check ──────────────────────────────────────────────────
    if expected_type == "string":
        if not isinstance(value, str):
            return f"Field {path!r} expected string, got {type(value).__name__}"
        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            return (
                f"Field {path!r} must be one of {enum_values}, got {value!r}"
            )

    elif expected_type == "number":
        if not isinstance(value, (int, float)):
            return f"Field {path!r} expected number, got {type(value).__name__}"

    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return f"Field {path!r} expected boolean, got {type(value).__name__}"

    elif expected_type == "array":
        if not isinstance(value, list):
            return f"Field {path!r} expected array, got {type(value).__name__}"
        items_schema = schema.get("items")
        if items_schema is not None:
            for i, item in enumerate(value):
                error = _validate_value(item, items_schema, f"{path}[{i}]")
                if error is not None:
                    return error

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_id(instance_id: str, step_id: str) -> str:
    """Deterministic request ID based on instance and step."""
    raw = f"{instance_id}::{step_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw))


def _serialise(data: Dict[str, Any]) -> str:
    """Convert validated response data to a string for engine injection.

    If the data has a single ``text`` or ``message`` field, return that
    value directly (natural-language interaction).  Otherwise JSON.
    """
    if "text" in data and len(data) == 1:
        return str(data["text"])
    if "message" in data and len(data) == 1:
        return str(data["message"])
    import json
    return json.dumps(data)
