"""
Phase 2.15.5 — Planner Contract Tests
======================================

Contract shape, version stability, round-trip serialization, and
multi-subgoal plan shapes for AgentPlan and StepSpec.
"""

from __future__ import annotations

import json

import pytest

from src.strategy.planning.contracts.agent_plan import (
    AgentPlan,
    CURRENT_CONTRACT_VERSION,
)
from src.strategy.planning.contracts.step_spec import (
    StepSpec,
    CURRENT_STEP_SPEC_VERSION,
)
from src.strategy.planning.models.plan import Plan
from src.strategy.memory.plan_memory_types import PlanMemoryRecord
from src.capabilities.contracts import (
    SkillCallRequest,
    SkillResult,
    S2_S3_CONTRACT_VERSION,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def make_plan(**overrides) -> Plan:
    kwargs = {
        "intent": "test intent",
        "targetskillid": "test-skill",
        "arguments": {"key": "val"},
        "reasoning_summary": "because reasons",
    }
    kwargs.update(overrides)
    return Plan(**kwargs)


def make_record(**overrides) -> PlanMemoryRecord:
    kwargs = {
        "plan_id": "plan-1",
        "subgoal_id": "sg-1",
        "segments": ["seg-a", "seg-b"],
        "created_at": "2025-01-01T00:00:00Z",
        "metadata": {},
        "intent": "test intent",
        "targetskillid": "test-skill",
        "arguments": {"key": "val"},
        "reasoning_summary": "because reasons",
    }
    kwargs.update(overrides)
    return PlanMemoryRecord(**kwargs)


def make_agent_plan(**overrides) -> AgentPlan:
    kwargs = {
        "plan_id": "plan-1",
        "subgoal_id": "sg-1",
        "segments": ["seg-a"],
        "intent": "test intent",
        "targetskillid": "test-skill",
        "arguments": {"key": "val"},
        "reasoning_summary": "because reasons",
        "created_at": "2025-01-01T00:00:00Z",
    }
    kwargs.update(overrides)
    return AgentPlan(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# AgentPlan — shape and field presence
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentPlanShape:
    """2.15.5a — AgentPlan field presence and types."""

    def test_all_required_fields_present(self):
        ap = make_agent_plan()
        assert ap.plan_id == "plan-1"
        assert ap.subgoal_id == "sg-1"
        assert ap.segments == ["seg-a"]
        assert ap.intent == "test intent"
        assert ap.targetskillid == "test-skill"
        assert ap.arguments == {"key": "val"}
        assert ap.reasoning_summary == "because reasons"
        assert ap.created_at == "2025-01-01T00:00:00Z"

    def test_optional_fields_defaults(self):
        ap = make_agent_plan()
        assert ap.metadata == {}
        assert ap.subgoals == ["sg-1"]  # auto-populated when empty
        assert ap.version == CURRENT_CONTRACT_VERSION

    def test_is_frozen(self):
        ap = make_agent_plan()
        with pytest.raises(Exception):
            ap.intent = "mutated"  # type: ignore[misc]

    def test_status_default_pending(self):
        ap = make_agent_plan()
        from src.strategy.planning.models.plan_state import PlanStatus
        assert ap.status == PlanStatus.PENDING

    def test_multi_subgoal_detection(self):
        single = make_agent_plan(subgoals=["sg-1"])
        assert not single.is_multi_subgoal

        multi = make_agent_plan(subgoal_id="sg-1", subgoals=["sg-1", "sg-2", "sg-3"])
        assert multi.is_multi_subgoal

    def test_segment_count(self):
        ap = make_agent_plan(segments=["a", "b", "c"])
        assert ap.segment_count == 3

    def test_not_hashable_by_default(self):
        """AgentPlan contains list/dict fields — Python refuses auto-hash.
        This is fine: these are data carriers, not hash keys."""
        ap = make_agent_plan()
        with pytest.raises(TypeError):
            hash(ap)


# ═══════════════════════════════════════════════════════════════════════════════
# AgentPlan — validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentPlanValidation:
    """2.15.5b — AgentPlan validation rules."""

    def test_empty_plan_id_rejected(self):
        with pytest.raises(ValueError, match="plan_id"):
            make_agent_plan(plan_id="")

    def test_empty_subgoal_id_rejected(self):
        with pytest.raises(ValueError, match="subgoal_id"):
            make_agent_plan(subgoal_id="")

    def test_empty_intent_rejected(self):
        with pytest.raises(ValueError, match="intent"):
            make_agent_plan(intent="")

    def test_empty_targetskillid_rejected(self):
        with pytest.raises(ValueError, match="targetskillid"):
            make_agent_plan(targetskillid="")

    def test_empty_created_at_rejected(self):
        with pytest.raises(ValueError, match="created_at"):
            make_agent_plan(created_at="")

    def test_empty_version_rejected(self):
        with pytest.raises(ValueError, match="version"):
            make_agent_plan(version="")

    def test_subgoal_id_auto_added_to_subgoals(self):
        """If subgoals is non-empty but missing subgoal_id, it is prepended."""
        ap = AgentPlan(
            plan_id="p1", subgoal_id="sg-primary", segments=["s1"],
            intent="test", targetskillid="ts", arguments={},
            reasoning_summary="rs", created_at="t",
            subgoals=["sg-other"],
        )
        assert ap.subgoals == ["sg-primary", "sg-other"]


# ═══════════════════════════════════════════════════════════════════════════════
# AgentPlan — serialization round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentPlanSerialization:
    """2.15.5c — AgentPlan JSON round-trip stability."""

    def test_round_trip_minimal(self):
        ap = make_agent_plan()
        d = ap.to_dict()
        ap2 = AgentPlan.from_dict(d)
        assert ap == ap2

    def test_round_trip_full(self):
        ap = AgentPlan(
            plan_id="p-full", subgoal_id="sg-full",
            segments=["seg-1", "seg-2", "seg-3"],
            intent="full round-trip test",
            targetskillid="http_fetch",
            arguments={"url": "https://example.com", "depth": 3},
            reasoning_summary="test serialization",
            created_at="2025-06-10T00:00:00Z",
            metadata={"origin": "test"},
            subgoals=["sg-full", "sg-extra"],
            version="1.0",
        )
        d = ap.to_dict()
        ap2 = AgentPlan.from_dict(d)
        assert ap == ap2
        assert ap2.segments == ["seg-1", "seg-2", "seg-3"]
        assert ap2.arguments == {"url": "https://example.com", "depth": 3}
        assert ap2.metadata == {"origin": "test"}
        assert ap2.subgoals == ["sg-full", "sg-extra"]

    def test_dict_is_json_serializable(self):
        ap = make_agent_plan()
        d = ap.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        # Should be parseable back
        parsed = json.loads(json_str)
        assert parsed["plan_id"] == "plan-1"

    def test_from_dict_missing_optional_fields(self):
        """from_dict should handle dicts missing optional fields."""
        d = {
            "plan_id": "p1", "subgoal_id": "sg1",
            "intent": "test", "targetskillid": "ts",
            "created_at": "t",
        }
        ap = AgentPlan.from_dict(d)
        assert ap.segments == []
        assert ap.arguments == {}
        assert ap.reasoning_summary == ""
        assert ap.metadata == {}
        assert ap.subgoals == ["sg1"]  # auto-populated from subgoal_id

    def test_version_preserved_across_round_trip(self):
        ap = make_agent_plan(version="1.0")
        d = ap.to_dict()
        assert d["version"] == "1.0"
        ap2 = AgentPlan.from_dict(d)
        assert ap2.version == "1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# AgentPlan — from_plan_and_record
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentPlanFromLegacy:
    """2.15.5d — Construction from Plan + PlanMemoryRecord."""

    def test_basic_construction(self):
        plan = make_plan()
        record = make_record()
        ap = AgentPlan.from_plan_and_record(plan, record)
        assert ap.plan_id == record.plan_id
        assert ap.subgoal_id == record.subgoal_id
        assert ap.segments == list(record.segments)
        assert ap.intent == plan.intent
        assert ap.targetskillid == plan.targetskillid
        assert ap.arguments == plan.arguments
        assert ap.reasoning_summary == plan.reasoning_summary
        assert ap.created_at == record.created_at
        assert ap.metadata == record.metadata

    def test_default_subgoals(self):
        """Without explicit subgoals, subgoals = [record.subgoal_id]."""
        plan = make_plan()
        record = make_record(subgoal_id="sg-only")
        ap = AgentPlan.from_plan_and_record(plan, record)
        assert ap.subgoals == ["sg-only"]

    def test_explicit_subgoals(self):
        plan = make_plan()
        record = make_record(subgoal_id="sg-1")
        ap = AgentPlan.from_plan_and_record(
            plan, record, subgoals=["sg-1", "sg-2"],
        )
        assert ap.subgoals == ["sg-1", "sg-2"]

    def test_arguments_deep_copied(self):
        """Arguments from Plan are dict-copied, not shared."""
        plan = make_plan(arguments={"mutable": [1, 2, 3]})
        record = make_record()
        ap = AgentPlan.from_plan_and_record(plan, record)
        # Mutating the original should not affect AgentPlan
        plan.arguments["mutable"].append(4)
        assert ap.arguments["mutable"] == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════════════════════
# StepSpec — shape and field presence
# ═══════════════════════════════════════════════════════════════════════════════

class TestStepSpecShape:
    """2.15.5e — StepSpec field presence and types."""

    def test_minimal_construction(self):
        ss = StepSpec(intent="do something")
        assert ss.intent == "do something"
        assert ss.args == {}
        assert ss.target_skill is None
        assert ss.expected_output is None
        assert ss.fallback_strategies == []
        assert ss.version == CURRENT_STEP_SPEC_VERSION

    def test_full_construction(self):
        ss = StepSpec(
            intent="fetch URL",
            args={"url": "https://example.com"},
            target_skill="http_fetch",
            expected_output={"title": "str", "body": "str"},
            fallback_strategies=["http_hardened", "http_headless"],
        )
        assert ss.target_skill == "http_fetch"
        assert ss.expected_output == {"title": "str", "body": "str"}
        assert ss.fallback_strategies == ["http_hardened", "http_headless"]

    def test_is_frozen(self):
        ss = StepSpec(intent="do")
        with pytest.raises(Exception):
            ss.intent = "mutated"  # type: ignore[misc]

    def test_has_fallback(self):
        no_fb = StepSpec(intent="x")
        assert not no_fb.has_fallback

        with_fb = StepSpec(intent="x", fallback_strategies=["alt"])
        assert with_fb.has_fallback

    def test_has_target_skill(self):
        no_skill = StepSpec(intent="x")
        assert not no_skill.has_target_skill

        with_skill = StepSpec(intent="x", target_skill="http_fetch")
        assert with_skill.has_target_skill

    def test_not_hashable_by_default(self):
        """StepSpec contains dict fields — Python refuses auto-hash.
        This is fine: these are data carriers, not hash keys."""
        ss = StepSpec(intent="do", args={"a": 1})
        with pytest.raises(TypeError):
            hash(ss)


# ═══════════════════════════════════════════════════════════════════════════════
# StepSpec — validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestStepSpecValidation:
    """2.15.5f — StepSpec validation rules."""

    def test_empty_intent_rejected(self):
        with pytest.raises(ValueError, match="intent"):
            StepSpec(intent="")

    def test_non_dict_args_rejected(self):
        with pytest.raises(ValueError, match="dict"):
            StepSpec(intent="x", args=[])  # type: ignore[arg-type]

    def test_empty_version_rejected(self):
        with pytest.raises(ValueError, match="version"):
            StepSpec(intent="x", version="")


# ═══════════════════════════════════════════════════════════════════════════════
# StepSpec — serialization round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestStepSpecSerialization:
    """2.15.5g — StepSpec JSON round-trip stability."""

    def test_round_trip_minimal(self):
        ss = StepSpec(intent="do something")
        d = ss.to_dict()
        ss2 = StepSpec.from_dict(d)
        assert ss == ss2
        # Minimal dict should not carry empty optional fields
        assert "args" not in d
        assert "target_skill" not in d

    def test_round_trip_full(self):
        ss = StepSpec(
            intent="fetch with fallback",
            args={"url": "https://example.com", "headers": {"Accept": "text/html"}},
            target_skill="http_fetch",
            expected_output={"status": "int", "body": "str"},
            fallback_strategies=["http_hardened", "http_stealth"],
        )
        d = ss.to_dict()
        ss2 = StepSpec.from_dict(d)
        assert ss == ss2
        assert ss2.fallback_strategies == ["http_hardened", "http_stealth"]

    def test_dict_is_json_serializable(self):
        ss = StepSpec(intent="x", args={"nested": {"deep": True}})
        d = ss.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["intent"] == "x"
        assert parsed["args"]["nested"]["deep"] is True

    def test_from_dict_missing_optional_fields(self):
        d = {"intent": "just intent"}
        ss = StepSpec.from_dict(d)
        assert ss.args == {}
        assert ss.target_skill is None
        assert ss.expected_output is None
        assert ss.fallback_strategies == []

    def test_version_preserved_across_round_trip(self):
        ss = StepSpec(intent="x", version="1.0")
        d = ss.to_dict()
        assert d["version"] == "1.0"
        ss2 = StepSpec.from_dict(d)
        assert ss2.version == "1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# StepSpec — from_llm_step
# ═══════════════════════════════════════════════════════════════════════════════

class TestStepSpecFromLLM:
    """2.15.5h — Construction from LLM-produced step dictionaries."""

    def test_description_key(self):
        llm = {"description": "fetch the page", "inputs": {"url": "x"}, "capability": "http_fetch"}
        ss = StepSpec.from_llm_step(llm)
        assert ss.intent == "fetch the page"
        assert ss.args == {"url": "x"}
        assert ss.target_skill == "http_fetch"

    def test_intent_key_fallback(self):
        """When 'description' is missing, use 'intent'."""
        llm = {"intent": "do thing", "args": {"k": "v"}}
        ss = StepSpec.from_llm_step(llm)
        assert ss.intent == "do thing"
        assert ss.args == {"k": "v"}

    def test_inputs_key(self):
        """'inputs' takes precedence over 'args'."""
        llm = {"description": "x", "inputs": {"a": 1}, "args": {"b": 2}}
        ss = StepSpec.from_llm_step(llm)
        assert ss.args == {"a": 1}

    def test_args_key_fallback(self):
        llm = {"description": "x", "args": {"b": 2}}
        ss = StepSpec.from_llm_step(llm)
        assert ss.args == {"b": 2}

    def test_no_capability(self):
        llm = {"description": "simple step"}
        ss = StepSpec.from_llm_step(llm)
        assert ss.target_skill is None

    def test_explicit_target_skill_override(self):
        llm = {"description": "x", "capability": "built-in"}
        ss = StepSpec.from_llm_step(llm, target_skill="override-skill")
        assert ss.target_skill == "built-in"  # LLM value wins

    def test_target_skill_fallback(self):
        """When LLM dict has no capability, the explicit arg is used."""
        llm = {"description": "x"}
        ss = StepSpec.from_llm_step(llm, target_skill="fallback-skill")
        assert ss.target_skill == "fallback-skill"

    def test_expected_output_forwarded(self):
        llm = {"description": "x"}
        ss = StepSpec.from_llm_step(llm, expected_output={"key": "type"})
        assert ss.expected_output == {"key": "type"}

    def test_empty_llm_step(self):
        """Empty LLM dict should raise clear validation error."""
        with pytest.raises(ValueError, match="intent must be non-empty"):
            StepSpec.from_llm_step({})


# ═══════════════════════════════════════════════════════════════════════════════
# S2↔S3 contract version (2.15.4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestS3ContractVersion:
    """2.15.5i — contract_version on S2↔S3 boundary types."""

    def test_skill_call_request_has_version(self):
        sr = SkillCallRequest(skill_name="test", request_id="r1")
        assert sr.contract_version == S2_S3_CONTRACT_VERSION
        assert sr.contract_version == "1.0"

    def test_skill_result_has_version(self):
        res = SkillResult(request_id="r1", success=True, output={"k": "v"})
        assert res.contract_version == S2_S3_CONTRACT_VERSION

    def test_skill_result_error_has_version(self):
        res = SkillResult(request_id="r1", success=False, error="boom")
        assert res.contract_version == S2_S3_CONTRACT_VERSION

    def test_empty_contract_version_rejected(self):
        with pytest.raises(ValueError, match="contract_version"):
            SkillCallRequest(skill_name="test", request_id="r1", contract_version="")

        with pytest.raises(ValueError, match="contract_version"):
            SkillResult(request_id="r1", success=True, output={"k": "v"}, contract_version="")
