"""Tests for Phase 3.5.1 — capability_metadata.py"""
import pytest
import json
from dataclasses import asdict

from src.capabilities.metadata.capability_metadata import (
    PrimitiveMetadata,
    SkillMetadata,
    validate_metadata,
)


MINIMAL_PRIMITIVE_META = dict(
    cost_latency=50,
    cost_resources="low",
    determinism="pure",
    side_effects=[],
    output_schema={"type": "string"},
    failure_modes=[],
    safety_level="low",
    prerequisites=[],
)


MINIMAL_SKILL_META = dict(
    cost_latency=200,
    cost_resources="medium",
    determinism="impure",
    side_effects=["fs"],
    output_schema={"type": "object", "properties": {"path": {"type": "string"}}},
    failure_modes=["TimeoutError"],
    safety_level="medium",
    prerequisites=["auth:admin"],
)


class TestPrimitiveMetadata:
    def test_constructs_with_valid_fields(self):
        meta = PrimitiveMetadata(**MINIMAL_PRIMITIVE_META)
        assert meta.cost_latency == 50
        assert meta.cost_resources == "low"
        assert meta.determinism == "pure"
        assert meta.side_effects == []
        assert meta.output_schema == {"type": "string"}
        assert meta.failure_modes == []
        assert meta.safety_level == "low"
        assert meta.prerequisites == []

    def test_all_fields_required(self):
        for field in MINIMAL_PRIMITIVE_META:
            bad = dict(MINIMAL_PRIMITIVE_META)
            del bad[field]
            with pytest.raises(TypeError):
                PrimitiveMetadata(**bad)

    def test_validate_passes_with_valid_data(self):
        meta = PrimitiveMetadata(**MINIMAL_PRIMITIVE_META)
        meta.validate()

    def test_cost_latency_must_be_int(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["cost_latency"] = "50"
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="cost_latency must be an int"):
            meta.validate()

    def test_cost_resources_must_be_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["cost_resources"] = 42
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="cost_resources must be a str"):
            meta.validate()

    def test_determinism_must_be_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["determinism"] = None
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="determinism must be a str"):
            meta.validate()

    def test_side_effects_must_be_list_of_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["side_effects"] = ["fs", 1]
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="side_effects must be a list of str"):
            meta.validate()

    def test_side_effects_must_be_list(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["side_effects"] = "fs"
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="side_effects must be a list of str"):
            meta.validate()

    def test_output_schema_must_be_dict(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["output_schema"] = "string"
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="output_schema must be a dict"):
            meta.validate()

    def test_output_schema_must_be_json_serializable(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["output_schema"] = {"fn": lambda x: x}
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="JSON-serializable"):
            meta.validate()

    def test_failure_modes_must_be_list_of_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["failure_modes"] = ["TimeoutError", None]
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="failure_modes must be a list of str"):
            meta.validate()

    def test_safety_level_must_be_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["safety_level"] = 1
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="safety_level must be a str"):
            meta.validate()

    def test_prerequisites_must_be_list_of_str(self):
        bad = dict(MINIMAL_PRIMITIVE_META)
        bad["prerequisites"] = [42]
        meta = PrimitiveMetadata(**bad)
        with pytest.raises(ValueError, match="prerequisites must be a list of str"):
            meta.validate()

    def test_non_empty_fields_accepted(self):
        meta = PrimitiveMetadata(
            cost_latency=500,
            cost_resources="high",
            determinism="nondeterministic",
            side_effects=["network", "dangerous"],
            output_schema={"type": "array", "items": {"type": "number"}},
            failure_modes=["TimeoutError", "HTTPError", "ConnectionError"],
            safety_level="high",
            prerequisites=["auth:admin", "env:gpu", "env:cuda"],
        )
        meta.validate()


class TestSkillMetadata:
    def test_constructs_with_valid_fields(self):
        meta = SkillMetadata(**MINIMAL_SKILL_META)
        assert meta.cost_latency == 200
        assert meta.cost_resources == "medium"
        assert meta.determinism == "impure"
        assert meta.side_effects == ["fs"]
        assert "path" in meta.output_schema["properties"]
        assert meta.failure_modes == ["TimeoutError"]
        assert meta.safety_level == "medium"
        assert meta.prerequisites == ["auth:admin"]

    def test_validate_passes_with_valid_data(self):
        meta = SkillMetadata(**MINIMAL_SKILL_META)
        meta.validate()

    def test_validate_rejects_bad_cost_latency(self):
        bad = dict(MINIMAL_SKILL_META)
        bad["cost_latency"] = "200"
        meta = SkillMetadata(**bad)
        with pytest.raises(ValueError, match="cost_latency"):
            meta.validate()

    def test_validate_rejects_non_list_side_effects(self):
        bad = dict(MINIMAL_SKILL_META)
        bad["side_effects"] = "fs"
        meta = SkillMetadata(**bad)
        with pytest.raises(ValueError, match="side_effects"):
            meta.validate()

    def test_validate_rejects_non_json_output_schema(self):
        bad = dict(MINIMAL_SKILL_META)
        bad["output_schema"] = {"handler": object()}
        meta = SkillMetadata(**bad)
        with pytest.raises(ValueError, match="JSON-serializable"):
            meta.validate()


class TestValidateMetadata:
    def test_accepts_primitive_metadata(self):
        meta = PrimitiveMetadata(**MINIMAL_PRIMITIVE_META)
        validate_metadata(meta)

    def test_accepts_skill_metadata(self):
        meta = SkillMetadata(**MINIMAL_SKILL_META)
        validate_metadata(meta)

    def test_rejects_bad_primitive(self):
        meta = PrimitiveMetadata(**MINIMAL_PRIMITIVE_META)
        meta.cost_latency = "bad"  # type: ignore
        with pytest.raises(ValueError):
            validate_metadata(meta)

    def test_rejects_bad_skill(self):
        meta = SkillMetadata(**MINIMAL_SKILL_META)
        meta.output_schema = "bad"  # type: ignore
        with pytest.raises(ValueError):
            validate_metadata(meta)


class TestMetadataRoundtrip:
    def test_primitive_metadata_is_dataclass(self):
        meta = PrimitiveMetadata(**MINIMAL_PRIMITIVE_META)
        d = asdict(meta)
        assert d == MINIMAL_PRIMITIVE_META

    def test_skill_metadata_is_dataclass(self):
        meta = SkillMetadata(**MINIMAL_SKILL_META)
        d = asdict(meta)
        assert d == MINIMAL_SKILL_META
