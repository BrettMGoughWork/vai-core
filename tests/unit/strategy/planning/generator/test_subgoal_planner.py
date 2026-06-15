"""Tests for src.strategy.planning.generator.subgoal_planner — plan hydration and decomposition."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from src.strategy.llm.mock_llm import MockLLM, MOCK_PLAN_RESPONSE
from src.strategy.memory.drift_memory import DriftMemory
from src.strategy.memory.governance.memory_governance import MemoryGovernance
from src.strategy.memory.governance.governance_errors import MemoryGovernanceError
from src.strategy.memory.plan_memory import PlanMemory
from src.strategy.memory.segment_memory import SegmentMemory
from src.strategy.memory.subgoal_memory import SubgoalMemory
from src.strategy.planning.generator.subgoal_planner import SubgoalPlanner
from src.strategy.types.hashing import stable_hash
from src.strategy.types.plan_segment import PlanSegment
from src.strategy.types.subgoal import Subgoal, SubgoalLifecycleState

NOW_MS = int(time.time() * 1000)
TIMESTAMP = datetime.fromtimestamp(NOW_MS / 1000.0, tz=timezone.utc).isoformat()
SG_ID = stable_hash({"test": "subgoal_planner_suite"})


def _make_governance(sg_id: str = SG_ID) -> tuple[MemoryGovernance, SubgoalMemory, SegmentMemory, PlanMemory]:
    """Return (governance, sm, seg_mem, plan_mem) with a single CREATED subgoal pre-loaded."""
    sm = SubgoalMemory()
    seg_mem = SegmentMemory()
    pm = PlanMemory()
    dm = DriftMemory()

    subgoal = Subgoal(
        subgoal_id=sg_id,
        goal="Verify Stratum-2 agent planning architecture",
        context={},
        metadata={},
        state=SubgoalLifecycleState.CREATED,
        created_at=NOW_MS,
    )
    sm.put(subgoal)

    governance = MemoryGovernance(sm, seg_mem, pm, dm)
    return governance, sm, seg_mem, pm


class TestSubgoalPlannerHydration:

    def test_plan_written_to_plan_memory(self):
        governance, _, _, pm = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        plan_id = planner.plan_for_subgoal(SG_ID, "test goal", governance, TIMESTAMP)
        record = pm.get_latest_for_subgoal(SG_ID)
        assert record is not None
        assert record.plan_id == plan_id

    def test_segments_written_to_segment_memory(self):
        governance, _, seg_mem, _ = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        planner.plan_for_subgoal(SG_ID, "test goal", governance, TIMESTAMP)
        snap = seg_mem.snapshot()
        # All LLM steps are grouped into one PlanSegment
        assert len(snap.records) == 1

    def test_plan_content_matches_mock_response(self):
        governance, _, _, pm = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        planner.plan_for_subgoal(SG_ID, "test goal", governance, TIMESTAMP)
        record = pm.get_latest_for_subgoal(SG_ID)
        assert record.intent == MOCK_PLAN_RESPONSE["plan"]["subgoal"]
        assert record.targetskillid == MOCK_PLAN_RESPONSE["plan"]["steps"][0]["capability"]

    def test_segment_steps_match_mock_response(self):
        governance, _, seg_mem, _ = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        planner.plan_for_subgoal(SG_ID, "test goal", governance, TIMESTAMP)
        snap = seg_mem.snapshot()
        assert len(snap.records) == 1
        record = snap.records[0]
        expected_steps = [s["description"] for s in MOCK_PLAN_RESPONSE["plan"]["steps"]]
        assert list(record.content) == expected_steps

    def test_plan_references_all_segment_ids(self):
        governance, _, seg_mem, pm = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        planner.plan_for_subgoal(SG_ID, "test goal", governance, TIMESTAMP)
        record = pm.get_latest_for_subgoal(SG_ID)
        known_segment_ids = {r.segment_id for r in seg_mem.snapshot().records}
        for seg_id in record.segments:
            assert seg_id in known_segment_ids


class TestSubgoalPlannerDeterminism:

    def test_plan_id_is_deterministic_for_same_timestamp(self):
        governance1, _, _, pm1 = _make_governance(sg_id=stable_hash({"t": "det1"}))
        governance2, _, _, pm2 = _make_governance(sg_id=stable_hash({"t": "det1"}))
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        sg_id = stable_hash({"t": "det1"})
        id1 = planner.plan_for_subgoal(sg_id, "test", governance1, TIMESTAMP)
        id2 = planner.plan_for_subgoal(sg_id, "test", governance2, TIMESTAMP)
        assert id1 == id2

    def test_segment_ids_are_deterministic_for_same_timestamp(self):
        sg_id = stable_hash({"t": "det2"})
        governance1, _, seg1, _ = _make_governance(sg_id=sg_id)
        governance2, _, seg2, _ = _make_governance(sg_id=sg_id)
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        planner.plan_for_subgoal(sg_id, "test", governance1, TIMESTAMP)
        planner.plan_for_subgoal(sg_id, "test", governance2, TIMESTAMP)
        ids1 = {r.segment_id for r in seg1.snapshot().records}
        ids2 = {r.segment_id for r in seg2.snapshot().records}
        assert ids1 == ids2

    def test_different_timestamps_produce_different_plan_ids(self):
        sg_id = stable_hash({"t": "det3"})
        governance1, _, _, _ = _make_governance(sg_id=sg_id)
        governance2, _, _, _ = _make_governance(sg_id=sg_id)
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        id1 = planner.plan_for_subgoal(sg_id, "test", governance1, "2025-01-01T00:00:00+00:00")
        id2 = planner.plan_for_subgoal(sg_id, "test", governance2, "2025-01-02T00:00:00+00:00")
        assert id1 != id2


class TestSubgoalPlannerGovernanceEnforcement:

    def test_raises_when_subgoal_not_in_memory(self):
        """Governance rejects segment write if subgoal_id doesn't exist."""
        sm = SubgoalMemory()
        governance = MemoryGovernance(sm, SegmentMemory(), PlanMemory(), DriftMemory())
        planner = SubgoalPlanner(llm_complete=MockLLM().make_complete())
        with pytest.raises(MemoryGovernanceError):
            planner.plan_for_subgoal("nonexistent-sg-id", "test", governance, TIMESTAMP)

    def test_hallucination_plan_missing_fields_raises(self):
        """Hallucinated plan missing targetskillid/reasoning_summary raises on parse/governance."""
        governance, _, _, _ = _make_governance()
        planner = SubgoalPlanner(llm_complete=MockLLM(simulate_hallucination=True).make_complete())
        with pytest.raises((KeyError, MemoryGovernanceError)):
            planner.plan_for_subgoal(SG_ID, "test", governance, TIMESTAMP)