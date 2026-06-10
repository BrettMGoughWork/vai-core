"""
Tests for the filesystem plugin system (Phase 3.14).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.capabilities.registry.plugin_loader import PluginLoader
from src.capabilities.registry.plugin_schema import PluginManifest
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def plugins_dir() -> str:
    """Absolute path to the test plugins directory."""
    return str(Path(__file__).resolve().parent / "plugins")


@pytest.fixture
def fresh_registries() -> tuple[PrimitiveRegistry, CapabilitySkillRegistry]:
    """Return a fresh pair of empty registries for each test."""
    return PrimitiveRegistry(), CapabilitySkillRegistry()


# ── Manifest validation ────────────────────────────────────────────────


class TestPluginManifest:
    """3.14.1 — PluginManifest validation."""

    def test_valid_manifest(self):
        m = PluginManifest.from_dict({
            "name": "my-plugin",
            "version": "1.0.0",
            "description": "Does things",
        })
        assert m.name == "my-plugin"
        assert m.version == "1.0.0"

    def test_missing_name(self):
        with pytest.raises(ValueError, match="name"):
            PluginManifest.from_dict({"version": "1.0.0", "description": "x"})

    def test_missing_version(self):
        with pytest.raises(ValueError, match="version"):
            PluginManifest.from_dict({"name": "p", "description": "x"})

    def test_missing_description(self):
        with pytest.raises(ValueError, match="description"):
            PluginManifest.from_dict({"name": "p", "version": "1.0.0"})

    def test_empty_name(self):
        with pytest.raises(ValueError, match="name"):
            PluginManifest.from_dict({"name": "  ", "version": "1.0.0", "description": "x"})

    def test_optional_fields_default(self):
        m = PluginManifest.from_dict({
            "name": "p", "version": "1.0.0", "description": "x",
        })
        assert m.author == ""
        assert m.dependencies == {}
        assert m.primitives == []
        assert m.skills == []

    def test_invalid_dependencies_type(self):
        with pytest.raises(ValueError, match="dependencies"):
            PluginManifest.from_dict({
                "name": "p", "version": "1.0.0", "description": "x",
                "dependencies": "bad",
            })

    def test_invalid_primitives_type(self):
        with pytest.raises(ValueError, match="primitives"):
            PluginManifest.from_dict({
                "name": "p", "version": "1.0.0", "description": "x",
                "primitives": "not-a-list",
            })


# ── Plugin loading ─────────────────────────────────────────────────────


class TestPluginLoad:
    """3.14.2 — PluginLoader load / scan / load_all."""

    def test_scan_plugins(self, plugins_dir):
        loader = PluginLoader(PrimitiveRegistry(), CapabilitySkillRegistry())
        names = loader.scan_plugins(plugins_dir)
        assert "test_plugin" in names
        assert "test_plugin_collision" in names

    def test_load_valid_plugin(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        name = loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))
        assert name == "test-plugin"

    def test_loaded_primitives_registered(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))

        p = prim_reg.get("plugin.test-plugin.uppercase")
        assert p is not None
        assert p.name == "plugin.test-plugin.uppercase"

    def test_loaded_skills_registered(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))

        s = skill_reg.get("plugin.test-plugin.echo")
        assert s is not None
        assert s.manifest.name == "plugin.test-plugin.echo"

    def test_primitive_executes(self, plugins_dir, fresh_registries):
        prim_reg, _ = fresh_registries
        loader = PluginLoader(prim_reg, CapabilitySkillRegistry())
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))

        p = prim_reg.get("plugin.test-plugin.uppercase")
        result = p.execute({"text": "hello"}, {})
        assert result.status == "success"
        assert result.data["value"] == "HELLO"

    def test_skill_executes(self, plugins_dir, fresh_registries):
        """Run the plugin skill end-to-end: uppercase echo."""
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))

        skill = skill_reg.get("plugin.test-plugin.echo")
        output = skill.run(text="hello")
        assert output["value"] == "HELLO"

    def test_load_all(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loaded = loader.load_all(plugins_dir)
        # test_plugin loads, test_plugin_invalid fails silently,
        # test_plugin_collision needs stdlib.echo loaded first to collide — skip
        assert "test_plugin" in loaded

    def test_double_load_raises(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))
        with pytest.raises(ValueError, match="already loaded"):
            loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))

    def test_invalid_manifest_rejected(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        with pytest.raises(ValueError):
            loader.load_plugin(str(Path(plugins_dir) / "test_plugin_invalid"))

    def test_nonexistent_plugin_dir_raises(self, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        with pytest.raises(FileNotFoundError):
            loader.load_plugin("/nonexistent/plugin/path")

    def test_name_collision_with_stdlib_raises(self, plugins_dir):
        """A plugin named 'echo' should collide with stdlib.echo."""
        prim_reg = PrimitiveRegistry()
        skill_reg = CapabilitySkillRegistry()
        # Pre-register stdlib.echo as a skill
        from src.capabilities.skills.manifest import SkillManifest
        from src.capabilities.skills.skill import CapabilitySkill
        manifest = SkillManifest.from_dict({
            "name": "echo",
            "description": "stdlib echo",
            "primitives": [],
            "inputs": {"type": "object", "properties": {}, "required": []},
        })
        skill = CapabilitySkill.from_manifest(manifest, prim_reg)
        skill_reg.register(skill)

        loader = PluginLoader(prim_reg, skill_reg)
        with pytest.raises(ValueError, match="collides"):
            loader.load_plugin(str(Path(plugins_dir) / "test_plugin_collision"))

    def test_list_loaded(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        assert loader.list_loaded() == []
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))
        assert loader.list_loaded() == ["test-plugin"]


# ── Plugin lifecycle ───────────────────────────────────────────────────


class TestPluginLifecycle:
    """3.14.3 — Unload / reload."""

    @pytest.fixture
    def loaded(self, plugins_dir, fresh_registries):
        prim_reg, skill_reg = fresh_registries
        loader = PluginLoader(prim_reg, skill_reg)
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin"))
        return loader, prim_reg, skill_reg

    def test_unload_removes_primitives(self, loaded):
        loader, prim_reg, _ = loaded
        loader.unload_plugin("test-plugin")
        assert prim_reg.get("plugin.test-plugin.uppercase") is None

    def test_unload_removes_skills(self, loaded):
        loader, _, skill_reg = loaded
        loader.unload_plugin("test-plugin")
        assert skill_reg.get("plugin.test-plugin.echo") is None

    def test_unload_unknown_plugin_raises(self, loaded):
        loader, _, _ = loaded
        with pytest.raises(KeyError):
            loader.unload_plugin("nonexistent")

    def test_reload_restores(self, loaded):
        loader, prim_reg, skill_reg = loaded
        loader.unload_plugin("test-plugin")
        loader.reload_plugin("test-plugin")

        assert prim_reg.get("plugin.test-plugin.uppercase") is not None
        assert skill_reg.get("plugin.test-plugin.echo") is not None
        # Ensure it still works after reload
        p = prim_reg.get("plugin.test-plugin.uppercase")
        result = p.execute({"text": "reloaded"}, {})
        assert result.data["value"] == "RELOADED"

    def test_reload_unknown_plugin_raises(self):
        loader = PluginLoader(PrimitiveRegistry(), CapabilitySkillRegistry())
        with pytest.raises(KeyError):
            loader.reload_plugin("nonexistent")

    def test_list_loaded_after_unload(self, loaded):
        loader, _, _ = loaded
        loader.unload_plugin("test-plugin")
        assert loader.list_loaded() == []

    def test_list_loaded_after_reload(self, loaded):
        loader, _, _ = loaded
        loader.unload_plugin("test-plugin")
        loader.reload_plugin("test-plugin")
        assert loader.list_loaded() == ["test-plugin"]


# ── PluginSchema standalone ────────────────────────────────────────────


class TestPluginSchema:
    """JSON Schema validation."""

    def test_schema_present(self):
        from src.capabilities.registry.plugin_schema import PLUGIN_MANIFEST_SCHEMA
        assert PLUGIN_MANIFEST_SCHEMA["type"] == "object"
        assert "name" in PLUGIN_MANIFEST_SCHEMA["required"]
