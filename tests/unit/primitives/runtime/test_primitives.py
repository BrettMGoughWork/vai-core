"""
Contract tests for src.primitives.runtime — SkillRegistry.

Tests SkillRegistry as a standalone unit: registration contract,
lookup contract, filtering contract (all_specs, all_specs_for_agent,
filter_by_category, filter_allowed).
"""
import pytest

from src.primitives.runtime.registry import SkillRegistry
from src.primitives.runtime.toolspec import ToolSpec
from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect
from src.core.state.config import AgentConfig


# ── Isolation fixture ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate():
    """Each test gets a clean SkillRegistry."""
    previous = SkillRegistry._skills.copy()
    SkillRegistry._skills = {}
    yield
    SkillRegistry._skills = previous


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spec(
    name,
    *,
    enabled=True,
    hidden=False,
    dev_only=False,
    category=SkillCategory.GENERAL,
    side_effects=SideEffect.NONE,
):
    return ToolSpec(
        name=name,
        description=f"The {name} tool",
        schema={"type": "object", "properties": {}},
        handler=lambda: name,
        enabled=enabled,
        hidden=hidden,
        dev_only=dev_only,
        category=category,
        side_effects=side_effects,
    )


def _config(allowed_tools=None, categories=None, side_effects=None):
    return AgentConfig(
        model="test-model",
        allowed_tools=allowed_tools or [],
        allowed_categories=categories or [SkillCategory.GENERAL],
        allowed_side_effects=side_effects or [SideEffect.NONE],
        max_steps=4,
    )


# ── Registration contract ─────────────────────────────────────────────────────

class TestSkillRegistryRegistration:
    def test_register_stores_spec(self):
        spec = _spec("echo")
        SkillRegistry._skills["echo"] = spec  # direct insert for unit test

        assert SkillRegistry.get("echo") is spec

    def test_get_raises_key_error_for_unknown(self):
        with pytest.raises(KeyError, match="Unknown skill: ghost"):
            SkillRegistry.get("ghost")

    def test_get_spec_returns_none_for_unknown(self):
        assert SkillRegistry.get_spec("ghost") is None

    def test_get_spec_returns_spec_when_registered(self):
        spec = _spec("echo")
        SkillRegistry._skills["echo"] = spec

        assert SkillRegistry.get_spec("echo") is spec

    def test_all_returns_all_registered_specs(self):
        SkillRegistry._skills["a"] = _spec("a")
        SkillRegistry._skills["b"] = _spec("b")

        names = {s.name for s in SkillRegistry.all()}
        assert names == {"a", "b"}

    def test_duplicate_registration_raises_value_error(self):
        class FakeSkill:
            spec = _spec("dup")

        SkillRegistry.register(FakeSkill())

        with pytest.raises(ValueError, match="Duplicate skill name: dup"):
            SkillRegistry.register(FakeSkill())


# ── all_specs() filtering contract ────────────────────────────────────────────

class TestAllSpecs:
    def test_enabled_visible_non_dev_spec_included(self):
        SkillRegistry._skills["ok"] = _spec("ok")

        assert any(s.name == "ok" for s in SkillRegistry.all_specs())

    def test_disabled_spec_excluded(self):
        SkillRegistry._skills["off"] = _spec("off", enabled=False)

        assert not any(s.name == "off" for s in SkillRegistry.all_specs())

    def test_hidden_spec_excluded(self):
        SkillRegistry._skills["secret"] = _spec("secret", hidden=True)

        assert not any(s.name == "secret" for s in SkillRegistry.all_specs())

    def test_dev_only_spec_excluded(self):
        SkillRegistry._skills["devtool"] = _spec("devtool", dev_only=True)

        assert not any(s.name == "devtool" for s in SkillRegistry.all_specs())

    def test_multiple_specs_filtered_independently(self):
        SkillRegistry._skills["visible"] = _spec("visible")
        SkillRegistry._skills["hidden"] = _spec("hidden", hidden=True)
        SkillRegistry._skills["disabled"] = _spec("disabled", enabled=False)

        names = {s.name for s in SkillRegistry.all_specs()}
        assert names == {"visible"}


# ── all_specs_for_agent() filtering contract ──────────────────────────────────

class TestAllSpecsForAgent:
    def test_spec_in_allowed_tools_returned(self):
        SkillRegistry._skills["echo"] = _spec("echo")
        config = _config(allowed_tools=["echo"])

        result = SkillRegistry.all_specs_for_agent(config)

        assert any(s.name == "echo" for s in result)

    def test_spec_not_in_allowed_tools_excluded(self):
        SkillRegistry._skills["echo"] = _spec("echo")
        config = _config(allowed_tools=["other"])

        result = SkillRegistry.all_specs_for_agent(config)

        assert not any(s.name == "echo" for s in result)

    def test_spec_with_disallowed_category_excluded(self):
        SkillRegistry._skills["fs_tool"] = _spec("fs_tool", category=SkillCategory.FILESYSTEM)
        config = _config(allowed_tools=["fs_tool"], categories=[SkillCategory.GENERAL])

        result = SkillRegistry.all_specs_for_agent(config)

        assert not any(s.name == "fs_tool" for s in result)

    def test_spec_with_disallowed_side_effects_excluded(self):
        from src.primitives.runtime.side_effects import SideEffect
        SkillRegistry._skills["writer"] = _spec("writer", side_effects=SideEffect.WRITE)
        config = _config(allowed_tools=["writer"], side_effects=[SideEffect.NONE])

        result = SkillRegistry.all_specs_for_agent(config)

        assert not any(s.name == "writer" for s in result)

    def test_empty_allowed_tools_returns_empty(self):
        SkillRegistry._skills["echo"] = _spec("echo")
        config = _config(allowed_tools=[])

        result = SkillRegistry.all_specs_for_agent(config)

        assert result == []

    def test_hidden_spec_excluded_even_if_in_allowed_tools(self):
        SkillRegistry._skills["secret"] = _spec("secret", hidden=True)
        config = _config(allowed_tools=["secret"])

        result = SkillRegistry.all_specs_for_agent(config)

        assert not any(s.name == "secret" for s in result)


# ── filter helpers ────────────────────────────────────────────────────────────

class TestFilterHelpers:
    def test_filter_by_category_returns_matching_specs(self):
        from src.primitives.runtime.categories import SkillCategory
        SkillRegistry._skills["math"] = _spec("math", category=SkillCategory.MATH)
        SkillRegistry._skills["text"] = _spec("text", category=SkillCategory.GENERAL)

        result = SkillRegistry.filter_by_category(SkillCategory.MATH)

        assert any(s.name == "math" for s in result)
        assert not any(s.name == "text" for s in result)

    def test_filter_allowed_returns_specs_in_list(self):
        SkillRegistry._skills["a"] = _spec("a")
        SkillRegistry._skills["b"] = _spec("b")
        SkillRegistry._skills["c"] = _spec("c")

        result = SkillRegistry.filter_allowed(["a", "c"])

        names = {s.name for s in result}
        assert names == {"a", "c"}
