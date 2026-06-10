"""
Tests for quarantine and governance (Phase 3.17.4).

Covers: quarantine placement, approval, rejection, pending listing,
        provenance tracking, and registry invisibility.
"""

from __future__ import annotations

import pytest

from src.capabilities.primitives.base import PrimitiveBase
from src.capabilities.primitives.types import PrimitiveType, PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.registry.quarantine import (
    ProvenanceRecord,
    SkillQuarantineManager,
)
from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.registry.skill_safety import SkillSafetyValidator
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill


# ---------------------------------------------------------------------------
# Fake primitive
# ---------------------------------------------------------------------------

class FakePrimitive(PrimitiveBase):
    def __init__(self, *, name: str, description: str = "",
                 primitive_type: PrimitiveType = PrimitiveType.PYTHON) -> None:
        super().__init__(name=name, description=description, primitive_type=primitive_type)

    def validate_args(self, _args: dict) -> None:
        return

    def execute(self, _args: dict, _context: dict) -> PrimitiveResult:
        return PrimitiveResult(status="success", data={"ok": True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manifest(**overrides) -> SkillManifest:
    data: dict[str, object] = {
        "name": "test-skill",
        "description": "A test skill",
        "primitives": ["file.read"],
        "inputs": {"type": "object", "properties": {}, "required": []},
        "steps": [{"call": "file.read", "args": {"path": "/tmp/test.txt"}}],
    }
    data.update(overrides)
    return SkillManifest.from_dict(data)


def make_skill(name: str = "test-skill", prim_registry=None) -> CapabilitySkill:
    m = make_manifest(name=name)
    return CapabilitySkill.from_manifest(m, prim_registry)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def prim_reg():
    reg = PrimitiveRegistry()
    reg.register("file.read", FakePrimitive(name="file.read"))
    reg.register("file.write", FakePrimitive(name="file.write"))
    return reg


@pytest.fixture
def skill_reg():
    return CapabilitySkillRegistry()


@pytest.fixture
def quarantine_mgr():
    return SkillQuarantineManager()


# ---------------------------------------------------------------------------
# SkillQuarantineManager unit tests
# ---------------------------------------------------------------------------

class TestQuarantineManager:
    def test_quarantine_placement(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        q = quarantine_mgr.quarantine(skill, prov)
        assert q.is_pending
        assert not q.is_approved
        assert not q.is_rejected

    def test_approve_moves_to_approved(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        approved = quarantine_mgr.approve("test-skill")
        assert approved is skill
        q = quarantine_mgr.get("test-skill")
        assert q is not None
        assert not q.is_pending  # no longer pending after approval

    def test_reject_marks_rejected(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        quarantine_mgr.reject("test-skill", reason="unsafe")
        q = quarantine_mgr.get("test-skill")
        assert q is not None
        assert q.is_rejected
        assert not q.is_pending

    def test_list_pending_excludes_approved(self, quarantine_mgr, prim_reg):
        for i in range(3):
            skill = make_skill(name=f"skill-{i}", prim_registry=prim_reg)
            prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
            quarantine_mgr.quarantine(skill, prov)
        quarantine_mgr.approve("skill-0")
        quarantine_mgr.reject("skill-1")
        pending = quarantine_mgr.list_pending()
        assert len(pending) == 1
        assert pending[0].skill.manifest.name == "skill-2"

    def test_count_returns_pending_only(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        assert quarantine_mgr.count() == 1
        quarantine_mgr.approve("test-skill")
        assert quarantine_mgr.count() == 0

    def test_duplicate_quarantine_rejected(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        with pytest.raises(ValueError, match="already in quarantine"):
            quarantine_mgr.quarantine(skill, prov)

    def test_approve_nonexistent_raises(self, quarantine_mgr):
        with pytest.raises(ValueError, match="not in quarantine"):
            quarantine_mgr.approve("ghost-skill")

    def test_reject_nonexistent_raises(self, quarantine_mgr):
        with pytest.raises(ValueError, match="not in quarantine"):
            quarantine_mgr.reject("ghost-skill")

    def test_reject_already_resolved_raises(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        quarantine_mgr.approve("test-skill")
        with pytest.raises(ValueError, match="not in a pending state"):
            quarantine_mgr.reject("test-skill")

    def test_remove_clears_record(self, quarantine_mgr, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        quarantine_mgr.quarantine(skill, prov)
        quarantine_mgr.approve("test-skill")
        quarantine_mgr.remove("test-skill")
        assert quarantine_mgr.get("test-skill") is None


# ---------------------------------------------------------------------------
# CapabilitySkillRegistry quarantine integration
# ---------------------------------------------------------------------------

class TestRegistryQuarantine:
    def test_quarantine_skill_invisible_to_get(self, skill_reg, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        skill_reg.quarantine_skill(skill, prov)
        assert skill_reg.get("test-skill") is None

    def test_quarantine_skill_invisible_to_ordered_list(self, skill_reg, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        skill_reg.quarantine_skill(skill, prov)
        names = [s.manifest.name for s in skill_reg.ordered_list()]
        assert "test-skill" not in names

    def test_quarantine_approve_registers(self, skill_reg, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        skill_reg.quarantine_skill(skill, prov)
        approved = skill_reg.quarantine_approve("test-skill")
        assert skill_reg.get("test-skill") is approved
        assert skill_reg.quarantine_count() == 0

    def test_quarantine_reject_does_not_register(self, skill_reg, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        skill_reg.quarantine_skill(skill, prov)
        skill_reg.quarantine_reject("test-skill")
        assert skill_reg.get("test-skill") is None
        assert skill_reg.quarantine_count() == 0  # rejected, not pending
        all_q = skill_reg.quarantine_list_all()
        assert len(all_q) == 1
        assert all_q[0].is_rejected

    def test_quarantine_skill_appears_in_pending(self, skill_reg, prim_reg):
        skill = make_skill(prim_registry=prim_reg)
        prov = ProvenanceRecord(author="agent", created_at=None)  # type: ignore
        skill_reg.quarantine_skill(skill, prov)
        pending = skill_reg.quarantine_list_pending()
        assert len(pending) == 1
        assert pending[0].skill.manifest.name == "test-skill"


# ---------------------------------------------------------------------------
# ProvenanceRecord
# ---------------------------------------------------------------------------

class TestProvenanceRecord:
    def test_provenance_stores_origin(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        prov = ProvenanceRecord(
            author="agent-42",
            created_at=now,
            plugin_name="test-plugin",
            plugin_version="1.2.3",
            sandbox_passed=True,
        )
        assert prov.author == "agent-42"
        assert prov.created_at is now
        assert prov.plugin_name == "test-plugin"
        assert prov.plugin_version == "1.2.3"
        assert prov.sandbox_passed is True
        assert prov.safety_errors == []
        assert prov.approved_at is None
        assert prov.rejected_at is None

    def test_provenance_approval_timestamps(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        prov = ProvenanceRecord(author="agent", created_at=now)
        assert prov.approved_at is None
        prov.approved_at = datetime.now(timezone.utc)
        assert prov.approved_at is not None

    def test_provenance_rejection_timestamps(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        prov = ProvenanceRecord(author="agent", created_at=now)
        assert prov.rejected_at is None
        prov.rejected_at = datetime.now(timezone.utc)
        assert prov.rejected_at is not None
