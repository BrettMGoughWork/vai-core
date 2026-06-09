"""
Ad-hoc LLM behavioral conformance test for stdlib.json.parse.

Uses SubgoalPlanner (the actual LLM skill-selection path) with a JSON
parsing goal, 25 repetitions, verifying the LLM consistently names
the correct skill.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from dotenv import load_dotenv
load_dotenv(override=True)

from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
from src.capabilities.runtime.skill_runner import SkillRunner
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.primitives.stdlib.echo import EchoPrimitive
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.discovery.providers.mock_provider import _simple_embedding_fn
from src.core.llm.llm_factory import factory
from src.stratum2.s3_adapter import S3Adapter
from src.core.memory.segment_memory import SegmentMemory
from src.core.memory.subgoal_memory import SubgoalMemory
from src.core.memory.plan_memory import PlanMemory
from src.core.memory.drift_memory import DriftMemory
from src.core.memory.governance.memory_governance import MemoryGovernance
from src.core.planning.generator.subgoal_planner import SubgoalPlanner
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState


class _TestEmbedder:
    def embed_query(self, text):
        return _simple_embedding_fn(text)

    def embed(self, text):
        return _simple_embedding_fn(text)


def make_json_parse_skill() -> CapabilitySkill:
    prim_registry = PrimitiveRegistry()
    prim_registry.register("echo", EchoPrimitive())
    manifest = SkillManifest(
        name="stdlib.json.parse",
        description="Parse a JSON string into a structured object",
        primitives=["echo"],
        inputs={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        steps=[
            {"call": "echo", "args": {"value": "{{ text }}"}, "save_as": "raw"}
        ],
    )
    return CapabilitySkill.from_manifest(manifest, prim_registry)


def main():
    skill_registry = CapabilitySkillRegistry()
    skill_registry.set_embedder(_TestEmbedder())
    skill_registry.register(make_json_parse_skill())
    runner = SkillRunner(registry=skill_registry, embedder=_TestEmbedder())
    s3_adapter = S3Adapter(runner)

    llm = factory.create("deepseek", "deepseek-chat")

    goal = 'parse the JSON string {"name": "Alice", "age": 30}'
    print(f"Goal: {goal}\n")

    passed = 0
    failed = 0
    wrong_skills: list[str] = []

    for rep in range(1, 26):
        # Fresh memory stores each run to avoid cross-run contamination
        segment_memory = SegmentMemory()
        subgoal_memory = SubgoalMemory()
        plan_memory = PlanMemory()
        drift_memory = DriftMemory()
        governance = MemoryGovernance(subgoal_memory, segment_memory, plan_memory, drift_memory)

        planner = SubgoalPlanner(llm=llm, model="deepseek-chat", s3_adapter=s3_adapter)

        subgoal_id = f"json-parse-{rep}"
        subgoal_memory.put(Subgoal(
            subgoal_id=subgoal_id, goal=goal, context={}, metadata={},
            parent_id=None, state=SubgoalLifecycleState.ACTIVE,
            created_at=1704067200000,
        ))

        plan_id = planner.plan_for_subgoal(
            subgoal_id=subgoal_id, goal=goal,
            governance=governance, timestamp="2025-01-01T00:00:00Z",
        )

        # Check what skill the LLM named in the plan
        plan_record = plan_memory.get_record(plan_id)
        llm_named = plan_record.targetskillid if plan_record else None

        # Check what skills ended up in the segment
        segment_ids = plan_memory.get_segments(plan_id)
        segment_skills = []
        if segment_ids:
            seg = governance.get_segment(segment_ids[0])
            if seg:
                segment_skills = seg.skills

        ok = "stdlib.json.parse" in segment_skills
        if ok:
            passed += 1
        else:
            failed += 1
            wrong_skills.append(llm_named or "NONE")

        marker = "PASS" if ok else f"WRONG: LLM={llm_named}, seg={segment_skills}"
        print(f"  [{rep:2d}/25] LLM->{llm_named!r}  seg={segment_skills}  [{marker}]")

    print(f"\n-- Result: {passed}/25 passed, {failed}/25 failed --")
    if wrong_skills:
        print(f"   Wrong skills named: {wrong_skills}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
