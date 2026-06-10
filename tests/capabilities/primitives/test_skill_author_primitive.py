"""Tests for SkillAuthorPrimitive — agent capability discovery (Phase 3.17.5)."""

from __future__ import annotations

import pytest

from src.capabilities.primitives.stdlib import skill_author as _sa_mod
from src.capabilities.primitives.stdlib.skill_author import (
    SkillAuthorPrimitive,
    set_author_pipeline,
)
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.registry.skill_safety import SkillSafetyValidator
from src.capabilities.skills.author import SkillAuthor


@pytest.fixture(autouse=True)
def _reset_lazy_pipeline():
    """Reset the module-level author instance between tests."""
    import src.capabilities.primitives.stdlib.skill_author as mod
    old = mod._author_instance
    mod._author_instance = None
    yield
    mod._author_instance = old


@pytest.fixture
def wired_pipeline():
    """Return a fully wired SkillAuthorPrimitive."""
    prim_reg = PrimitiveRegistry()
    from src.capabilities.primitives.stdlib import load_all_primitives
    load_all_primitives(prim_reg)

    skill_reg = CapabilitySkillRegistry()
    safety = SkillSafetyValidator(
        primitive_registry=prim_reg,
        skill_registry=skill_reg,
    )
    author = SkillAuthor(
        primitive_registry=prim_reg,
        skill_registry=skill_reg,
        safety_validator=safety,
    )
    set_author_pipeline(author)
    return SkillAuthorPrimitive(), prim_reg, skill_reg


# ── Construction & discovery ────────────────────────────────────────────


class TestSkillAuthorPrimitiveConstruction:
    """No-arg construction (required for stdlib auto-discovery)."""

    def test_no_arg_construction(self):
        """SkillAuthorPrimitive can be instantiated with no arguments."""
        p = SkillAuthorPrimitive()
        assert p.name == "stdlib.skill.author"
        assert "Author a new capability skill" in p.description

    def test_class_attributes_for_auto_discovery(self):
        """Class-level attributes are set for stdlib loader pattern."""
        assert SkillAuthorPrimitive.name == "stdlib.skill.author"
        assert SkillAuthorPrimitive.description
        assert SkillAuthorPrimitive.primitive_type is not None


# ── Validation ──────────────────────────────────────────────────────────


class TestSkillAuthorPrimitiveValidation:
    def test_valid_minimal_args(self):
        p = SkillAuthorPrimitive()
        p.validate_args({"skill_text": "---\nname: test\n---"})

    def test_missing_skill_text(self):
        p = SkillAuthorPrimitive()
        with pytest.raises(ValueError, match="skill_text"):
            p.validate_args({})

    def test_empty_skill_text(self):
        p = SkillAuthorPrimitive()
        with pytest.raises(ValueError, match="not be empty"):
            p.validate_args({"skill_text": "   "})

    def test_skill_text_not_string(self):
        p = SkillAuthorPrimitive()
        with pytest.raises(ValueError, match="must be a string"):
            p.validate_args({"skill_text": 123})

    def test_arg_type_must_be_dict(self):
        p = SkillAuthorPrimitive()
        with pytest.raises(ValueError, match="must be a dict"):
            p.validate_args(None)  # type: ignore[arg-type]

    def test_optional_args_type_checked(self):
        p = SkillAuthorPrimitive()
        with pytest.raises(ValueError, match="must be a boolean"):
            p.validate_args({"skill_text": "---", "quarantine": "yes"})


# ── Execution (unwired) ─────────────────────────────────────────────────


class TestSkillAuthorPrimitiveUnwired:
    def test_execute_without_pipeline_returns_error(self):
        """When set_author_pipeline() hasn't been called, execute returns error."""
        p = SkillAuthorPrimitive()
        result = p.execute({"skill_text": "---\ntest\n---"}, {})
        assert result.status == "error"
        assert "not wired" in result.error

    def test_execute_after_pipeline_set_then_reset(self):
        """Mixing wired/unwired works correctly."""
        prim_reg = PrimitiveRegistry()
        skill_reg = CapabilitySkillRegistry()
        safety = SkillSafetyValidator(prim_reg, skill_reg)
        author = SkillAuthor(prim_reg, skill_reg, safety)

        p = SkillAuthorPrimitive()
        set_author_pipeline(author)
        assert _sa_mod._author_instance is not None

        _sa_mod._author_instance = None

        result = p.execute({"skill_text": "test"}, {})
        assert result.status == "error"
        assert "not wired" in result.error


# ── Execution (wired) ───────────────────────────────────────────────────


class TestSkillAuthorPrimitiveWired:
    def test_execute_valid_skill(self, wired_pipeline):
        """A valid skill text produces a quarantined skill."""
        p, prim_reg, skill_reg = wired_pipeline

        skill_text = """---
name: agent.test_skill
description: A test skill authored by the agent
primitives:
  - stdlib.echo
inputs:
  value:
    type: any
    required: true
outputs:
  value: any
steps:
  - call: stdlib.echo
    args:
      value: "{{ value }}"
---
"""
        result = p.execute({"skill_text": skill_text}, {})
        assert result.status == "success"
        assert result.data["name"] == "agent.test_skill"
        assert result.data["status"] == "quarantined"

        # Verify it's in quarantine, not active registry
        quarantined = skill_reg.quarantine_list_all()
        assert len(quarantined) == 1
        assert quarantined[0].skill.manifest.name == "agent.test_skill"

    def test_execute_invalid_skill_returns_error(self, wired_pipeline):
        """Invalid skill text returns error status."""
        p, prim_reg, skill_reg = wired_pipeline

        result = p.execute({"skill_text": "not a valid skill"}, {})
        assert result.status == "error"
        assert result.error

    def test_execute_with_explicit_plugin_name(self, wired_pipeline):
        """plugin_name is forwarded correctly."""
        p, prim_reg, skill_reg = wired_pipeline

        skill_text = """---
name: my.test_skill
description: Test
primitives:
  - stdlib.echo
inputs:
  value:
    type: any
    required: true
outputs:
  value: any
steps:
  - call: stdlib.echo
    args:
      value: "{{ value }}"
---
"""
        result = p.execute(
            {"skill_text": skill_text, "plugin_name": "custom_plugin"},
            {},
        )
        assert result.status == "success"
        assert result.data["name"] == "my.test_skill"

    def test_execute_with_quarantine_false(self, wired_pipeline):
        """quarantine=False does direct registration."""
        p, prim_reg, skill_reg = wired_pipeline

        skill_text = """---
name: direct.register_skill
description: Directly registered
primitives:
  - stdlib.echo
inputs:
  value:
    type: any
    required: true
outputs:
  value: any
steps:
  - call: stdlib.echo
    args:
      value: "{{ value }}"
---
"""
        result = p.execute(
            {"skill_text": skill_text, "quarantine": False},
            {},
        )
        assert result.status == "success"
        assert result.data["status"] == "registered"
        assert skill_reg.get("direct.register_skill") is not None
