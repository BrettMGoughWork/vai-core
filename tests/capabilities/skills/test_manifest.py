"""
Tests for SkillManifest dataclass (Phase 3.3.2).

Covers: from_dict construction, field validation, step structure
validation, and primitive reference checks.
"""

from __future__ import annotations

import pytest

from src.capabilities.skills.manifest import SkillManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def minimal_manifest_dict(**overrides):
    """Return a minimal valid manifest dict with optional overrides."""
    data = {
        "name": "test-skill",
        "description": "A test skill manifest",
        "primitives": ["file.read", "http.get"],
        "inputs": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "steps": [
            {"call": "file.read", "args": {"path": "/tmp/test.txt"}},
            {"call": "http.get", "args": {"url": "https://example.com"}, "on_error": None},
        ],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# from_dict tests
# ---------------------------------------------------------------------------

class TestFromDict:
    """Tests for SkillManifest.from_dict."""

    def test_valid_manifest_succeeds(self):
        """A valid dict produces a validated SkillManifest."""
        m = SkillManifest.from_dict(minimal_manifest_dict())
        assert m.name == "test-skill"
        assert m.description == "A test skill manifest"
        assert m.primitives == ["file.read", "http.get"]
        assert len(m.steps) == 2

    def test_missing_name_raises(self):
        """Missing name raises ValueError."""
        data = minimal_manifest_dict()
        del data["name"]
        with pytest.raises(ValueError, match="name must be a non-empty str"):
            SkillManifest.from_dict(data)

    def test_empty_name_raises(self):
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="name must be a non-empty str"):
            SkillManifest.from_dict(minimal_manifest_dict(name=""))

    def test_missing_description_raises(self):
        """Missing description raises ValueError."""
        data = minimal_manifest_dict()
        del data["description"]
        with pytest.raises(ValueError, match="description must be a non-empty str"):
            SkillManifest.from_dict(data)

    def test_empty_description_raises(self):
        """Empty description raises ValueError."""
        with pytest.raises(ValueError, match="description must be a non-empty str"):
            SkillManifest.from_dict(minimal_manifest_dict(description=""))

    def test_non_list_primitives_raises(self):
        """primitives not being a list raises ValueError."""
        with pytest.raises(ValueError, match="primitives must be a list"):
            SkillManifest.from_dict(minimal_manifest_dict(primitives="not-a-list"))

    def test_non_string_primitive_items_raises(self):
        """primitives containing non-strings raises ValueError."""
        with pytest.raises(ValueError, match="primitives must be a list of str"):
            SkillManifest.from_dict(minimal_manifest_dict(primitives=[123]))

    def test_non_dict_inputs_raises(self):
        """inputs not being a dict raises ValueError."""
        with pytest.raises(ValueError, match="inputs must be a dict"):
            SkillManifest.from_dict(minimal_manifest_dict(inputs="not-a-dict"))

    def test_non_list_steps_raises(self):
        """steps not being a list raises ValueError."""
        with pytest.raises(ValueError, match="steps must be a list"):
            SkillManifest.from_dict(minimal_manifest_dict(steps="not-a-list"))


# ---------------------------------------------------------------------------
# Step validation tests
# ---------------------------------------------------------------------------

class TestStepValidation:
    """Tests for step structure validation within SkillManifest."""

    def test_step_not_a_dict_raises(self):
        """A step that is not a dict raises ValueError."""
        with pytest.raises(ValueError, match="must be a dict"):
            SkillManifest.from_dict(minimal_manifest_dict(steps=[42]))

    def test_step_missing_call_raises(self):
        """A step without 'call' raises ValueError."""
        with pytest.raises(ValueError, match="call must be a str"):
            SkillManifest.from_dict(minimal_manifest_dict(steps=[{"args": {}}]))

    def test_step_call_not_a_string_raises(self):
        """A step with a non-string call raises ValueError."""
        with pytest.raises(ValueError, match="call must be a str"):
            SkillManifest.from_dict(minimal_manifest_dict(
                steps=[{"call": 99, "args": {}}]
            ))

    def test_step_args_not_a_dict_raises(self):
        """A step with non-dict args raises ValueError."""
        with pytest.raises(ValueError, match="args must be a dict"):
            SkillManifest.from_dict(minimal_manifest_dict(
                steps=[{"call": "file.read", "args": "bad-args"}]
            ))

    def test_step_on_error_not_string_raises(self):
        """A step with non-string, non-None on_error raises ValueError."""
        with pytest.raises(ValueError, match="on_error must be str or None"):
            SkillManifest.from_dict(minimal_manifest_dict(
                steps=[{"call": "file.read", "args": {}, "on_error": 5}]
            ))

    def test_step_calls_unknown_primitive_raises(self):
        """A step referencing a primitive not in the list raises ValueError."""
        with pytest.raises(ValueError, match="not listed in SkillManifest.primitives"):
            SkillManifest.from_dict(minimal_manifest_dict(
                primitives=["file.read"],
                steps=[{"call": "http.get", "args": {}}],
            ))

    def test_step_with_none_on_error_ok(self):
        """on_error can be None (or omitted)."""
        m = SkillManifest.from_dict(minimal_manifest_dict(
            steps=[{"call": "file.read", "args": {}, "on_error": None}],
        ))
        assert m.steps[0].get("on_error") is None

    def test_step_with_continue_on_error_ok(self):
        """on_error='continue' is a valid string value."""
        m = SkillManifest.from_dict(minimal_manifest_dict(
            steps=[{"call": "file.read", "args": {}, "on_error": "continue"}],
        ))
        assert m.steps[0]["on_error"] == "continue"

    def test_step_without_on_error_ok(self):
        """Steps without on_error are valid (it is optional)."""
        m = SkillManifest.from_dict(minimal_manifest_dict(
            steps=[{"call": "file.read", "args": {}}],
        ))
        assert "on_error" not in m.steps[0]


# ---------------------------------------------------------------------------
# validate method tests
# ---------------------------------------------------------------------------

class TestValidate:
    """Tests for SkillManifest.validate called directly."""

    def test_validate_passes_on_valid_manifest(self):
        """validate() does not raise on a fully valid manifest."""
        m = SkillManifest(
            name="test",
            description="A test",
            primitives=["a"],
            inputs={"key": "value"},
            steps=[{"call": "a", "args": {}}],
        )
        m.validate()  # Should not raise.

    def test_validate_rejects_empty_primitives_list_on_step_call(self):
        """Steps referencing a primitive not in the list fails."""
        m = SkillManifest(
            name="test",
            description="A test",
            primitives=[],
            inputs={},
            steps=[{"call": "missing", "args": {}}],
        )
        with pytest.raises(ValueError, match="not listed in SkillManifest.primitives"):
            m.validate()

    def test_validate_allows_empty_steps(self):
        """A manifest with no steps is valid."""
        m = SkillManifest(
            name="test",
            description="A test",
            primitives=[],
            inputs={},
            steps=[],
        )
        m.validate()
