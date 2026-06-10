"""
Tests for Phase 3.21.4 — Capability Graph Consistency
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.capabilities.registry.graph_consistency import (
    CAPABILITY_CYCLE,
    DANGLING_PRIMITIVE,
    DANGLING_SKILL,
    PLUGIN_UNLOAD_UNSAFE,
    PRIVILEGE_DRIFT,
    SCHEMA_DRIFT,
    VALID_VIOLATION_KINDS,
    CapabilityGraphChecker,
    ConsistencyViolation,
    GraphConsistencyReport,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_skill(name: str, primitives: list[str], steps: list[dict] | None = None):
    """Build a mock CapabilitySkill with the given name and primitives."""
    skill = MagicMock()
    skill.manifest.name = name
    skill.manifest.primitives = primitives
    skill.manifest.steps = steps or []
    return skill


def _make_primitive(name: str, plugin_name: str | None = None):
    """Build a mock PrimitiveBase with the given name and optional plugin."""
    p = MagicMock()
    p.name = name
    p.plugin_name = plugin_name
    return p


def _make_registries(
    skills: list | None = None,
    primitives: list | None = None,
):
    """Build mock PrimitiveRegistry and CapabilitySkillRegistry."""
    skill_reg = MagicMock()
    prim_reg = MagicMock()

    skills = skills or []
    primitives = primitives or []

    skill_reg.list.return_value = skills
    prim_reg.list.return_value = primitives

    skill_map = {s.manifest.name: s for s in skills}
    prim_map = {p.name: p for p in primitives}

    skill_reg.get.side_effect = lambda name: skill_map.get(name)
    prim_reg.get.side_effect = lambda name: prim_map.get(name)

    return prim_reg, skill_reg


# ===========================================================================
# ConsistencyViolation
# ===========================================================================

class TestConsistencyViolation:
    def test_construction(self):
        v = ConsistencyViolation(
            kind=DANGLING_PRIMITIVE, skill_name="my.skill", detail="bad primitive"
        )
        assert v.kind == DANGLING_PRIMITIVE
        assert v.skill_name == "my.skill"
        assert v.detail == "bad primitive"

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="kind"):
            ConsistencyViolation(kind="unknown_kind", skill_name="s", detail="d")

    def test_empty_detail_raises(self):
        with pytest.raises(ValueError, match="detail"):
            ConsistencyViolation(kind=DANGLING_PRIMITIVE, skill_name="s", detail="")

    def test_empty_skill_name_allowed(self):
        v = ConsistencyViolation(kind=SCHEMA_DRIFT, skill_name="", detail="gone")
        assert v.skill_name == ""

    def test_is_frozen(self):
        v = ConsistencyViolation(kind=DANGLING_PRIMITIVE, skill_name="s", detail="d")
        with pytest.raises(Exception):
            v.kind = DANGLING_SKILL  # type: ignore[misc]

    @pytest.mark.parametrize("kind", sorted(VALID_VIOLATION_KINDS))
    def test_all_kinds_accepted(self, kind):
        v = ConsistencyViolation(kind=kind, skill_name="s", detail="detail")
        assert v.kind == kind


# ===========================================================================
# GraphConsistencyReport
# ===========================================================================

class TestGraphConsistencyReport:
    def test_clean_report(self):
        r = GraphConsistencyReport(violations=())
        assert r.is_clean is True
        assert len(r) == 0

    def test_dirty_report(self):
        v = ConsistencyViolation(kind=DANGLING_PRIMITIVE, skill_name="s", detail="d")
        r = GraphConsistencyReport(violations=(v,))
        assert r.is_clean is False
        assert len(r) == 1

    def test_violations_by_kind(self):
        v1 = ConsistencyViolation(kind=DANGLING_PRIMITIVE, skill_name="a", detail="d1")
        v2 = ConsistencyViolation(kind=SCHEMA_DRIFT, skill_name="", detail="d2")
        r = GraphConsistencyReport(violations=(v1, v2))
        assert len(r.violations_by_kind(DANGLING_PRIMITIVE)) == 1
        assert len(r.violations_by_kind(SCHEMA_DRIFT)) == 1
        assert len(r.violations_by_kind(DANGLING_SKILL)) == 0

    def test_is_frozen(self):
        r = GraphConsistencyReport(violations=())
        with pytest.raises(Exception):
            r.violations = ()  # type: ignore[misc]


# ===========================================================================
# check_dangling_primitives
# ===========================================================================

class TestCheckDanglingPrimitives:
    def test_no_violations_when_all_registered(self):
        prim = _make_primitive("stdlib.file.read")
        skill = _make_skill("read.skill", ["stdlib.file.read"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_dangling_primitives() == []

    def test_detects_missing_primitive(self):
        skill = _make_skill("broken.skill", ["stdlib.missing"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_dangling_primitives()
        assert len(violations) == 1
        assert violations[0].kind == DANGLING_PRIMITIVE
        assert "stdlib.missing" in violations[0].detail
        assert violations[0].skill_name == "broken.skill"

    def test_multiple_missing_primitives(self):
        skill = _make_skill("broken.skill", ["prim.a", "prim.b"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_dangling_primitives()
        assert len(violations) == 2

    def test_partial_missing(self):
        prim = _make_primitive("stdlib.ok")
        skill = _make_skill("mixed.skill", ["stdlib.ok", "stdlib.missing"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_dangling_primitives()
        assert len(violations) == 1
        assert "stdlib.missing" in violations[0].detail

    def test_empty_registries(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_dangling_primitives() == []

    def test_skill_with_no_primitives(self):
        skill = _make_skill("empty.skill", [])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_dangling_primitives() == []


# ===========================================================================
# check_dangling_skills
# ===========================================================================

class TestCheckDanglingSkills:
    def test_no_violations_when_all_present(self):
        skill = _make_skill("my.skill", [])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_dangling_skills({"my.skill"}) == []

    def test_detects_missing_skill(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_dangling_skills({"missing.skill"})
        assert len(violations) == 1
        assert violations[0].kind == DANGLING_SKILL
        assert "missing.skill" in violations[0].detail

    def test_multiple_missing_skills(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_dangling_skills({"a.skill", "b.skill"})
        assert len(violations) == 2

    def test_empty_referenced_set(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_dangling_skills(set()) == []


# ===========================================================================
# check_schema_drift
# ===========================================================================

class TestCheckSchemaDrift:
    def test_no_drift_when_all_present(self):
        prim = _make_primitive("stdlib.file.read")
        prim_reg, skill_reg = _make_registries(primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_schema_drift({"stdlib.file.read"}) == []

    def test_detects_removed_primitive(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_schema_drift({"stdlib.old.prim"})
        assert len(violations) == 1
        assert violations[0].kind == SCHEMA_DRIFT
        assert "stdlib.old.prim" in violations[0].detail
        assert violations[0].skill_name == ""

    def test_empty_baseline(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_schema_drift(set()) == []

    def test_partial_drift(self):
        prim = _make_primitive("stdlib.ok")
        prim_reg, skill_reg = _make_registries(primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_schema_drift({"stdlib.ok", "stdlib.gone"})
        assert len(violations) == 1
        assert "stdlib.gone" in violations[0].detail


# ===========================================================================
# check_privilege_drift
# ===========================================================================

class TestCheckPrivilegeDrift:
    def test_no_drift_when_baseline_matches(self):
        skill = _make_skill("my.skill", ["stdlib.read"])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_privilege_drift({"my.skill": {"stdlib.read"}}) == []

    def test_detects_new_primitive(self):
        skill = _make_skill("my.skill", ["stdlib.read", "stdlib.delete"])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_privilege_drift({"my.skill": {"stdlib.read"}})
        assert len(violations) == 1
        assert violations[0].kind == PRIVILEGE_DRIFT
        assert "stdlib.delete" in violations[0].detail
        assert violations[0].skill_name == "my.skill"

    def test_removed_primitive_not_a_violation(self):
        # If the skill lost a primitive, that's not privilege escalation
        skill = _make_skill("my.skill", ["stdlib.read"])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        # Baseline had two, current has one — no escalation
        assert checker.check_privilege_drift(
            {"my.skill": {"stdlib.read", "stdlib.write"}}
        ) == []

    def test_skill_not_in_registry_skipped(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        # Skill in baseline but not in registry — silently skip
        assert checker.check_privilege_drift({"ghost.skill": {"prim.a"}}) == []

    def test_empty_baseline(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_privilege_drift({}) == []

    def test_multiple_new_primitives(self):
        skill = _make_skill("my.skill", ["prim.a", "prim.b", "prim.c"])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_privilege_drift({"my.skill": {"prim.a"}})
        assert len(violations) == 2


# ===========================================================================
# check_capability_cycles
# ===========================================================================

class TestCheckCapabilityCycles:
    def test_no_cycles_with_primitive_only_steps(self):
        prim = _make_primitive("stdlib.file.read")
        skill = _make_skill(
            "read.skill",
            ["stdlib.file.read"],
            steps=[{"call": "stdlib.file.read", "args": {}}],
        )
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_capability_cycles() == []

    def test_detects_self_cycle_via_step(self):
        # Skill's step calls itself (step call matches own name)
        skill = _make_skill(
            "recursive.skill",
            [],
            steps=[{"call": "recursive.skill"}],
        )
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        # Self-reference in steps is filtered out (call != skill_name check)
        # so no cycle violation — step calls to self are ignored
        violations = checker.check_capability_cycles()
        assert violations == []

    def test_detects_mutual_cycle(self):
        # skill_a calls skill_b and skill_b calls skill_a
        skill_a = _make_skill(
            "skill.a",
            ["skill.b"],  # manifest.primitives lists skill.b as dependency
            steps=[{"call": "skill.b"}],
        )
        skill_b = _make_skill(
            "skill.b",
            ["skill.a"],
            steps=[{"call": "skill.a"}],
        )
        prim_reg, skill_reg = _make_registries(skills=[skill_a, skill_b])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_capability_cycles()
        assert len(violations) >= 1
        assert all(v.kind == CAPABILITY_CYCLE for v in violations)
        cycle_detail = " ".join(v.detail for v in violations)
        assert "skill.a" in cycle_detail or "skill.b" in cycle_detail

    def test_no_cycles_with_linear_chain(self):
        # a → b → c (no cycle)
        skill_a = _make_skill("skill.a", ["skill.b"], steps=[{"call": "skill.b"}])
        skill_b = _make_skill("skill.b", ["skill.c"], steps=[{"call": "skill.c"}])
        skill_c = _make_skill("skill.c", [], steps=[])
        prim_reg, skill_reg = _make_registries(skills=[skill_a, skill_b, skill_c])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_capability_cycles() == []

    def test_empty_registries(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_capability_cycles() == []


# ===========================================================================
# check_plugin_unload_safety
# ===========================================================================

class TestCheckPluginUnloadSafety:
    def test_safe_when_no_plugin_primitives(self):
        prim = _make_primitive("stdlib.file.read", plugin_name=None)
        skill = _make_skill("read.skill", ["stdlib.file.read"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        assert checker.check_plugin_unload_safety("my.plugin") == []

    def test_detects_affected_skill(self):
        prim = _make_primitive("plugin.prim", plugin_name="my.plugin")
        skill = _make_skill("dependent.skill", ["plugin.prim"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_plugin_unload_safety("my.plugin")
        assert len(violations) == 1
        assert violations[0].kind == PLUGIN_UNLOAD_UNSAFE
        assert "my.plugin" in violations[0].detail
        assert "plugin.prim" in violations[0].detail
        assert violations[0].skill_name == "dependent.skill"

    def test_only_affects_matching_plugin(self):
        prim_a = _make_primitive("plugin_a.prim", plugin_name="plugin.a")
        prim_b = _make_primitive("plugin_b.prim", plugin_name="plugin.b")
        skill = _make_skill("combined.skill", ["plugin_a.prim", "plugin_b.prim"])
        prim_reg, skill_reg = _make_registries(
            skills=[skill], primitives=[prim_a, prim_b]
        )
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        violations = checker.check_plugin_unload_safety("plugin.a")
        assert len(violations) == 1
        assert "plugin_a.prim" in violations[0].detail

    def test_primitive_without_name_attribute_skipped(self):
        prim = MagicMock(spec=[])  # no .name attribute
        prim.plugin_name = "my.plugin"
        prim_reg = MagicMock()
        prim_reg.list.return_value = [prim]
        prim_reg.get.return_value = None
        skill_reg = MagicMock()
        skill_reg.list.return_value = []
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        # Should not raise — primitives without .name are skipped
        assert checker.check_plugin_unload_safety("my.plugin") == []


# ===========================================================================
# run_all
# ===========================================================================

class TestRunAll:
    def test_clean_report(self):
        prim = _make_primitive("stdlib.read")
        skill = _make_skill("read.skill", ["stdlib.read"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        report = checker.run_all(
            referenced_skill_names={"read.skill"},
            baseline_primitive_names={"stdlib.read"},
            baseline_privileges={"read.skill": {"stdlib.read"}},
        )
        assert report.is_clean

    def test_aggregates_all_violation_types(self):
        # Dangling primitive
        skill = _make_skill("broken.skill", ["missing.prim"])
        prim_reg, skill_reg = _make_registries(skills=[skill])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        report = checker.run_all(
            referenced_skill_names={"also.missing.skill"},
            baseline_primitive_names={"gone.prim"},
        )
        kinds = {v.kind for v in report.violations}
        assert DANGLING_PRIMITIVE in kinds
        assert DANGLING_SKILL in kinds
        assert SCHEMA_DRIFT in kinds

    def test_skips_optional_checks_when_not_provided(self):
        prim_reg, skill_reg = _make_registries()
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        # Should not raise even with no optional args
        report = checker.run_all()
        assert isinstance(report, GraphConsistencyReport)

    def test_violations_sorted(self):
        skill_a = _make_skill("skill.a", ["missing.x"])
        skill_b = _make_skill("skill.b", ["missing.y"])
        prim_reg, skill_reg = _make_registries(skills=[skill_a, skill_b])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        report = checker.run_all()
        # All violations should be DANGLING_PRIMITIVE and sorted by skill_name
        names = [v.skill_name for v in report.violations]
        assert names == sorted(names)

    def test_plugin_check_included_when_provided(self):
        prim = _make_primitive("plugin.prim", plugin_name="my.plugin")
        skill = _make_skill("dep.skill", ["plugin.prim"])
        prim_reg, skill_reg = _make_registries(skills=[skill], primitives=[prim])
        checker = CapabilityGraphChecker(prim_reg, skill_reg)
        report = checker.run_all(plugin_name="my.plugin")
        assert not report.is_clean
        assert report.violations_by_kind(PLUGIN_UNLOAD_UNSAFE)
