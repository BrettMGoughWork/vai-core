"""Tests for Phase 3.15: Deterministic Plugin Hot-Reload.

These tests verify:
- Deterministic registry ordering (3.15.1)
- Stable embedding IDs (3.15.2)
- Registry snapshots with hash-based IDs (3.15.3)
- Hot-reload flow — load/unload/reload triggers snapshot updates (3.15.4)
"""

from __future__ import annotations

import pytest
from pathlib import Path

from src.capabilities.registry.plugin_loader import PluginLoader
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.registry.snapshot import SnapshotManager, RegistrySnapshot
from src.capabilities.registry.sorter import sorted_skills, sorted_primitives


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fresh_registries():
    """Return a fresh (PrimitiveRegistry, CapabilitySkillRegistry) pair."""
    prim = PrimitiveRegistry()
    skill = CapabilitySkillRegistry()
    return prim, skill


@pytest.fixture
def plugins_dir() -> str:
    """Absolute path to the test plugins directory."""
    return str(Path(__file__).resolve().parent / "plugins")


@pytest.fixture
def loader(plugins_dir, fresh_registries):
    """Return a PluginLoader pointed at the test plugin directory."""
    prim, skill = fresh_registries
    return PluginLoader(prim, skill)


# ── 3.15.1: Deterministic ordering ───────────────────────────────────


class TestDeterministicOrdering:
    def test_ordered_list_is_deterministic(self, loader, plugins_dir):
        """Ordered list is stable across multiple calls."""
        loader.load_all(plugins_dir)
        skills1 = loader._skill_registry.ordered_list()
        skills2 = loader._skill_registry.ordered_list()
        assert [s.manifest.name for s in skills1] == [s.manifest.name for s in skills2]

    def test_ordered_list_sorts_by_name(self, loader, plugins_dir):
        """Skills are sorted by name, version, plugin_name."""
        loader.load_all(plugins_dir)
        skills = loader._skill_registry.ordered_list()
        names = [s.manifest.name for s in skills]
        assert names == sorted(names)

    def test_ordered_list_primitives(self, loader, plugins_dir):
        """Primitives support ordered_list."""
        loader.load_all(plugins_dir)
        primitives = loader._prim_registry.ordered_list()
        names = [p.name for p in primitives]
        assert names == sorted(names)


# ── 3.15.2: Stable embedding IDs (manifest_hash) ─────────────────────


class TestStableEmbeddingIds:
    def test_manifest_hash_is_computed(self, loader, plugins_dir):
        """Every loaded skill has a manifest_hash."""
        loader.load_all(plugins_dir)
        for skill in loader._skill_registry.list():
            assert skill.manifest.manifest_hash is not None
            assert len(skill.manifest.manifest_hash) == 64  # SHA-256 hex

    def test_manifest_hash_is_deterministic(self, loader, plugins_dir):
        """Same skill yields same hash on reload."""
        loader.load_all(plugins_dir)
        skill1 = loader._skill_registry.get("echo_a")
        hash1 = skill1.manifest.manifest_hash

        loader.unload_plugin("test-plugin-a")
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin_a"))
        skill2 = loader._skill_registry.get("echo_a")
        hash2 = skill2.manifest.manifest_hash

        assert hash1 == hash2


# ── 3.15.3: Registry snapshots ───────────────────────────────────────


class TestRegistrySnapshots:
    def test_snapshot_has_stable_id(self, loader, plugins_dir):
        """Identical registry state produces identical snapshot ID."""
        loader.load_all(plugins_dir)
        snap1 = loader._snapshot_manager.current
        assert snap1 is not None
        sid1 = snap1.snapshot_id

        # Unload and reload — snapshot ID must be the same
        loader.unload_plugin("test-plugin")
        loader.load_all(plugins_dir)
        snap2 = loader._snapshot_manager.current
        assert snap2 is not None
        assert snap2.snapshot_id == sid1

    def test_snapshot_changes_when_registry_changes(self, loader, plugins_dir):
        """Snapshot ID changes when registry is empty vs loaded."""
        sid_empty = loader._snapshot_manager.capture([], []).snapshot_id
        loader.load_all(plugins_dir)
        sid_loaded = loader._snapshot_manager.current.snapshot_id
        assert sid_empty != sid_loaded

    def test_snapshot_manager_stores_previous(self, loader, plugins_dir):
        """SnapshotManager retains the previous snapshot."""
        sid_empty = loader._snapshot_manager.capture([], []).snapshot_id
        loader.load_all(plugins_dir)
        sid_loaded = loader._snapshot_manager.current.snapshot_id

        # Previous snapshot should still be retrievable
        prev = loader._snapshot_manager.get(sid_empty)
        assert prev is not None
        assert prev.snapshot_id == sid_empty
        assert len(prev.skills) == 0

    def test_snapshot_manager_callback(self):
        """Callback fires when snapshot changes."""
        called: list[RegistrySnapshot] = []

        def on_change(snap: RegistrySnapshot) -> None:
            called.append(snap)

        mgr = SnapshotManager(change_callback=on_change)
        assert mgr.current is None

        snap1 = mgr.capture([], [])
        assert len(called) == 1
        assert called[0] is snap1

        # Same state → no callback
        snap2 = mgr.capture([], [])
        assert len(called) == 1  # unchanged
        assert snap2.snapshot_id == snap1.snapshot_id


# ── 3.15.4: Hot-reload flow ──────────────────────────────────────────


class TestHotReloadFlow:
    def test_hot_reload_triggers_snapshot(self, loader, plugins_dir):
        """Reloading a plugin captures a fresh snapshot."""
        loader.load_plugin(str(Path(plugins_dir) / "test_plugin_a"))
        snap_before = loader._snapshot_manager.current
        assert snap_before is not None

        # Reload
        loader.reload_plugin("test-plugin-a")
        snap_after = loader._snapshot_manager.current
        assert snap_after is not None

        # Same content → same snapshot ID
        assert snap_before.snapshot_id == snap_after.snapshot_id

    def test_unload_removes_from_registry(self, loader, plugins_dir):
        """Unloading a plugin removes its primitives and skills."""
        loader.load_all(plugins_dir)
        assert loader._skill_registry.get("echo_a") is not None
        assert loader._prim_registry.get("echo_a") is not None

        loader.unload_plugin("test-plugin-a")
        assert loader._skill_registry.get("echo_a") is None
        assert loader._prim_registry.get("echo_a") is None

    def test_full_cycle_deterministic(self, loader, plugins_dir):
        """Full load → unload → reload cycle preserves determinism."""
        loader.load_all(plugins_dir)
        skills_before = [s.manifest.name for s in loader._skill_registry.ordered_list()]

        loader.unload_plugin("test-plugin-b")
        loader.unload_plugin("test-plugin-a")
        loader.load_all(plugins_dir)
        skills_after = [s.manifest.name for s in loader._skill_registry.ordered_list()]

        assert skills_after == skills_before

    def test_plugin_tracking_on_primitives(self, loader, plugins_dir):
        """Primitives from loaded plugins carry plugin_name and plugin_version."""
        loader.load_all(plugins_dir)
        prim_a = loader._prim_registry.get("echo_a")
        prim_b = loader._prim_registry.get("echo_b")

        assert prim_a.plugin_name == "test-plugin-a"
        assert prim_a.plugin_version == "1.0"
        assert prim_b.plugin_name == "test-plugin-b"
        assert prim_b.plugin_version == "2.0"
