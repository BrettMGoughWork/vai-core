"""
Interaction request/response dataclasses for the workflow HITL layer.

Defines the schema and data types used when a workflow pauses for
human input — the ``user_input`` step type.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Input schema model
# ---------------------------------------------------------------------------

# Supported field types for input validation.
VALID_FIELD_TYPES = {"string", "number", "boolean", "array"}


@dataclass
class InputField:
    """Schema definition for a single input field.

    Mirrors a subset of JSON Schema suitable for CLI/chat-based input
    collection.
    """

    name: str
    type: str = "string"
    label: str = ""
    description: Optional[str] = None
    required: bool = True
    default: Any = None
    choices: Optional[List[str]] = None  # enum constraint
    nullable: bool = False
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    def __post_init__(self) -> None:
        if self.type not in VALID_FIELD_TYPES:
            raise ValueError(f"Unsupported input field type: {self.type!r}")


@dataclass
class InputSchema:
    """The input schema for a ``user_input`` workflow step.

    Describes what fields the workflow expects from the human operator.
    Behaves as a typed wrapper around the raw ``Dict[str, Any]`` that
    comes from YAML config.
    """

    fields: List[InputField] = field(default_factory=list)
    title: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "InputSchema":
        """Parse a JSON-Schema-like dict into an ``InputSchema``.

        Supports the ``{type: object, properties: {...}, required: [...]}``
        format used by existing workflow YAML files.
        """
        if not raw:
            return cls(fields=[])

        title = raw.get("title", "")
        description = raw.get("description", "")
        properties = raw.get("properties", {})
        required_set = set(raw.get("required", []))

        fields: List[InputField] = []
        for prop_name, prop_schema in properties.items():
            fields.append(
                InputField(
                    name=prop_name,
                    type=prop_schema.get("type", "string"),
                    label=prop_schema.get("title", prop_name),
                    description=prop_schema.get("description"),
                    required=prop_name in required_set,
                    default=prop_schema.get("default"),
                    choices=prop_schema.get("enum"),
                    nullable=prop_schema.get("nullable", False),
                    min_length=prop_schema.get("minLength"),
                    max_length=prop_schema.get("maxLength"),
                    min_value=prop_schema.get("minimum"),
                    max_value=prop_schema.get("maximum"),
                )
            )
        return cls(fields=fields, title=title, description=description)

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to the JSON-Schema-like dict format."""
        if not self.fields:
            return {}

        required: List[str] = []
        properties: Dict[str, Any] = {}

        for f in self.fields:
            if f.required:
                required.append(f.name)
            prop: Dict[str, Any] = {"type": f.type}
            if f.label and f.label != f.name:
                prop["title"] = f.label
            if f.description is not None:
                prop["description"] = f.description
            if f.default is not None:
                prop["default"] = f.default
            if f.choices is not None:
                prop["enum"] = f.choices
            if f.nullable:
                prop["nullable"] = True
            if f.min_length is not None:
                prop["minLength"] = f.min_length
            if f.max_length is not None:
                prop["maxLength"] = f.max_length
            if f.min_value is not None:
                prop["minimum"] = f.min_value
            if f.max_value is not None:
                prop["maximum"] = f.max_value
            properties[f.name] = prop

        result: Dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            result["required"] = required
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        return result

    def is_empty(self) -> bool:
        """``True`` when no fields are defined — accept any input."""
        return len(self.fields) == 0


# ---------------------------------------------------------------------------
# Interaction request / response
# ---------------------------------------------------------------------------


def _make_request_id(instance_id: str, step_id: str) -> str:
    """Deterministic request ID based on instance and step."""
    raw = f"{instance_id}::{step_id}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw))


@dataclass
class InteractionRequest:
    """A request for human input, created when a workflow hits a ``user_input`` step."""

    request_id: str
    instance_id: str
    step_id: str
    prompt: str
    input_schema: InputSchema
    timeout_seconds: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

    def __post_init__(self) -> None:
        # Auto-convert raw dict to InputSchema for ergonomics
        if isinstance(self.input_schema, dict):
            object.__setattr__(self, "input_schema", InputSchema.from_dict(self.input_schema))
        if self.expires_at is None and self.timeout_seconds is not None:
            object.__setattr__(self, "expires_at", self.created_at + self.timeout_seconds)

    @classmethod
    def from_step_config(
        cls,
        instance_id: str,
        step_id: str,
        config: Dict[str, Any],
    ) -> "InteractionRequest":
        """Create from a workflow step config dict (from YAML)."""
        schema_raw = config.get("input_schema", {})
        if isinstance(schema_raw, InputSchema):
            schema = schema_raw
        else:
            schema = InputSchema.from_dict(schema_raw)

        req = cls(
            request_id=_make_request_id(instance_id, step_id),
            instance_id=instance_id,
            step_id=step_id,
            prompt=config.get("prompt", "Input required"),
            input_schema=schema,
            timeout_seconds=config.get("timeout_seconds"),
        )
        return req

    @property
    def is_expired(self) -> bool:
        """``True`` if this request has passed its expiration time."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


@dataclass
class InteractionResponse:
    """A validated response to an ``InteractionRequest``."""

    request_id: str
    data: Dict[str, Any]
    received_at: float = field(default_factory=time.time)
