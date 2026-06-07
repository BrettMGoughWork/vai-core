"""
Phase 3.5.1 — Capability metadata dataclasses.

PrimitiveMetadata and CapabilitySkillMetadata describe cost, determinism,
side-effects, output shape, failure modes, safety, and prerequisites.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union
import json


@dataclass
class PrimitiveMetadata:
    cost_latency: int
    cost_resources: str
    determinism: str
    side_effects: List[str]
    output_schema: Dict[str, Any]
    failure_modes: List[str]
    safety_level: str
    prerequisites: List[str]

    def validate(self) -> None:
        _validate_metadata(self)


@dataclass
class CapabilitySkillMetadata:
    cost_latency: int
    cost_resources: str
    determinism: str
    side_effects: List[str]
    output_schema: Dict[str, Any]
    failure_modes: List[str]
    safety_level: str
    prerequisites: List[str]

    def validate(self) -> None:
        _validate_metadata(self)


def validate_metadata(obj: Union[PrimitiveMetadata, CapabilitySkillMetadata]) -> None:
    """Validate that all metadata fields are present and correctly typed."""
    _validate_metadata(obj)


def _validate_metadata(obj: Union[PrimitiveMetadata, CapabilitySkillMetadata]) -> None:
    required_fields = [
        "cost_latency",
        "cost_resources",
        "determinism",
        "side_effects",
        "output_schema",
        "failure_modes",
        "safety_level",
        "prerequisites",
    ]

    for field_name in required_fields:
        if not hasattr(obj, field_name):
            raise ValueError(f"missing metadata field: {field_name}")

    if not isinstance(obj.cost_latency, int):
        raise ValueError("cost_latency must be an int")
    if not isinstance(obj.cost_resources, str):
        raise ValueError("cost_resources must be a str")
    if not isinstance(obj.determinism, str):
        raise ValueError("determinism must be a str")
    if not isinstance(obj.side_effects, list) or not all(
        isinstance(s, str) for s in obj.side_effects
    ):
        raise ValueError("side_effects must be a list of str")
    if not isinstance(obj.output_schema, dict):
        raise ValueError("output_schema must be a dict")
    if not isinstance(obj.failure_modes, list) or not all(
        isinstance(s, str) for s in obj.failure_modes
    ):
        raise ValueError("failure_modes must be a list of str")
    if not isinstance(obj.safety_level, str):
        raise ValueError("safety_level must be a str")
    if not isinstance(obj.prerequisites, list) or not all(
        isinstance(s, str) for s in obj.prerequisites
    ):
        raise ValueError("prerequisites must be a list of str")

    try:
        json.dumps(obj.output_schema)
    except (TypeError, ValueError):
        raise ValueError("output_schema must be JSON-serializable")
