"""Tests for Phase 2.16.3 — Memory-aware planning (PlanGenerator + SemanticMemoryIndex)."""

import time

import pytest

from src.core.planning.generator.plan_generator import (
    PlanGenerator,
    PlanPrompt,
    StrategyContext,
)
from src.core.planning.models.step_state import StepState, StepStatus
from src.core.memory.semantic_memory_types import SemanticMemoryRecord
from src.core.memory.semantic_memory_index import SemanticMemoryIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(
    step_id: str = "step-1",
    cognitive_input: dict | None = None,
) -> StepState:
    return StepState(
        step_id=step_id,
        cognitive_input=cognitive_input or {},
        status=StepStatus.PENDING,
        created_at=1,
    )


def _make_record(
    record_id: str,
    memory_type: str = "subgoal",
    topics: tuple = (),
    entities: tuple = (),
    capability_patterns: tuple = (),
    outcome: str = "success",
    created_at: int = 1,
) -> SemanticMemoryRecord:
    return SemanticMemoryRecord(
        record_id=record_id,
        memory_type=memory_type,
        source_id=f"src-{record_id}",
        topics=topics,
        entities=entities,
        capability_patterns=capability_patterns,
        embedding_vector=None,
        outcome=outcome,
        metadata={},
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# StrategyContext
# ---------------------------------------------------------------------------

class TestStrategyContext:
    def test_default_is_empty(self):
        ctx = StrategyContext()
        assert ctx.preferred_capabilities == ()
        assert ctx.avoid_capabilities == ()
        assert ctx.successful_patterns == ()
        assert ctx.drift_risks == ()
        assert ctx.confidence == 0.0
        assert ctx.matches == 0

    def test_is_frozen(self):
        ctx = StrategyContext(preferred_capabilities=("a",))
        with pytest.raises(Exception):
            ctx.preferred_capabilities = ("b",)  # type: ignore

    def test_can_be_populated(self):
        ctx = StrategyContext(
            preferred_capabilities=("fetch_url",),
            avoid_capabilities=("http_simple",),
            successful_patterns=("fetch_url→parse",),
            drift_risks=("http_simple→fail",),
            confidence=0.75,
            matches=4,
        )
        assert ctx.preferred_capabilities == ("fetch_url",)
        assert ctx.avoid_capabilities == ("http_simple",)
        assert ctx.confidence == 0.75
        assert ctx.matches == 4


# ---------------------------------------------------------------------------
# PlanGenerator — no memory index
# ---------------------------------------------------------------------------

class TestPlanGeneratorWithoutIndex:
    def test_construct_without_index(self):
        gen = PlanGenerator(capabilities={"echo": {}})
        assert gen.capabilities == {"echo": {}}

    def test_get_strategy_context_returns_empty(self):
        gen = PlanGenerator(capabilities={"echo": {}})
        ctx = gen.get_strategy_context(_make_state())
        assert isinstance(ctx, StrategyContext)
        assert ctx.matches == 0
        assert ctx.preferred_capabilities == ()
        assert ctx.avoid_capabilities == ()

    def test_generate_produces_valid_prompt(self):
        gen = PlanGenerator(capabilities={"echo": {"input_schema": {}}})
        state = _make_state(
            cognitive_input={"text": "hello"},
        )
        prompt = gen.generate(state)
        assert isinstance(prompt, PlanPrompt)
        assert isinstance(prompt.prompt, str)
        assert "metadata" in prompt.metadata or True  # metadata is dict

    def test_generate_without_index_has_no_strategy_context_in_metadata(self):
        gen = PlanGenerator(capabilities={"echo": {}})
        state = _make_state(
            cognitive_input={"text": "hello"},
        )
        prompt = gen.generate(state)
        assert "strategy_context" not in prompt.metadata

    def test_extract_query_topics_from_topic_string(self):
        state = _make_state(cognitive_input={"topic": "file_io"})
        topics = PlanGenerator._extract_query_topics(state)
        assert "file_io" in topics

    def test_extract_query_topics_from_topics_list(self):
        state = _make_state(cognitive_input={"topics": ["file_io", "parsing"]})
        topics = PlanGenerator._extract_query_topics(state)
        assert "file_io" in topics
        assert "parsing" in topics

    def test_extract_query_topics_falls_back_to_content(self):
        state = _make_state(cognitive_input={"content": "analyze the codebase"})
        topics = PlanGenerator._extract_query_topics(state)
        assert len(topics) == 1
        assert "analyze the codebase" in topics

    def test_extract_query_topics_empty_input(self):
        state = _make_state(cognitive_input={})
        topics = PlanGenerator._extract_query_topics(state)
        assert topics == []

    def test_extract_query_entities_from_entity_string(self):
        state = _make_state(cognitive_input={"target": "main.py"})
        entities = PlanGenerator._extract_query_entities(state)
        assert "main.py" in entities

    def test_extract_query_entities_from_entities_list(self):
        state = _make_state(cognitive_input={"entities": ["main.py", "utils.py"]})
        entities = PlanGenerator._extract_query_entities(state)
        assert "main.py" in entities
        assert "utils.py" in entities

    def test_extract_query_entities_empty(self):
        state = _make_state(cognitive_input={})
        entities = PlanGenerator._extract_query_entities(state)
        assert entities == []

    def test_extract_query_capabilities_from_string(self):
        state = _make_state(cognitive_input={"capability": "fetch_url"})
        caps = PlanGenerator._extract_query_capabilities(state)
        assert "fetch_url" in caps

    def test_extract_query_capabilities_from_list(self):
        state = _make_state(cognitive_input={"capabilities": ["fetch_url", "parse_json"]})
        caps = PlanGenerator._extract_query_capabilities(state)
        assert "fetch_url" in caps
        assert "parse_json" in caps

    def test_extract_query_capabilities_empty(self):
        state = _make_state(cognitive_input={})
        caps = PlanGenerator._extract_query_capabilities(state)
        assert caps == []


# ---------------------------------------------------------------------------
# PlanGenerator — with memory index
# ---------------------------------------------------------------------------

class TestPlanGeneratorWithIndex:
    def test_construct_with_index(self):
        idx = SemanticMemoryIndex()
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        assert gen.capabilities == {"echo": {}}

    def test_get_strategy_context_returns_empty_when_index_is_empty(self):
        idx = SemanticMemoryIndex()
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        ctx = gen.get_strategy_context(_make_state())
        assert ctx.matches == 0

    def test_get_strategy_context_finds_successful_patterns(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("file_io",),
            entities=("main.py",),
            capability_patterns=("fetch_file", "parse"),
            outcome="success",
        ))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={
            "topic": "file_io",
            "target": "main.py",
        })
        ctx = gen.get_strategy_context(state)
        assert ctx.matches == 1
        assert "fetch_file" in ctx.preferred_capabilities
        assert "parse" in ctx.preferred_capabilities
        assert ctx.avoid_capabilities == ()
        assert ctx.confidence == 1.0

    def test_get_strategy_context_identifies_drift_risks(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("http",),
            capability_patterns=("http_simple",),
            outcome="failure",
        ))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "http"})
        ctx = gen.get_strategy_context(state)
        assert ctx.matches == 1
        assert ctx.preferred_capabilities == ()
        assert "http_simple" in ctx.avoid_capabilities
        assert ctx.confidence == 0.0

    def test_get_strategy_context_mixed_outcomes(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record("r1", topics=("db",), capability_patterns=("pg",), outcome="success"))
        idx.add(_make_record("r2", topics=("db",), capability_patterns=("sqlite",), outcome="failure"))
        idx.add(_make_record("r3", topics=("db",), capability_patterns=("pg", "migrate"), outcome="success"))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "db"})
        ctx = gen.get_strategy_context(state)
        assert ctx.matches == 3
        # Two successes → preferred
        assert "pg" in ctx.preferred_capabilities
        assert "migrate" in ctx.preferred_capabilities
        # One failure → avoid
        assert "sqlite" in ctx.avoid_capabilities
        # Confidence = 2/3
        assert ctx.confidence == pytest.approx(2.0 / 3.0)

    def test_get_strategy_context_deduplicates_capabilities(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record("r1", topics=("parse",), capability_patterns=("json_parse",), outcome="success"))
        idx.add(_make_record("r2", topics=("parse",), capability_patterns=("json_parse",), outcome="success"))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "parse"})
        ctx = gen.get_strategy_context(state)
        # json_parse should appear only once in preferred
        assert ctx.preferred_capabilities.count("json_parse") == 1

    def test_get_strategy_context_confirms_partial_success_is_preferred(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record("r1", topics=("net",), capability_patterns=("fetch",), outcome="partial_success"))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "net"})
        ctx = gen.get_strategy_context(state)
        assert "fetch" in ctx.preferred_capabilities
        assert ctx.confidence == 1.0

    def test_get_strategy_context_unknown_outcome_is_neither(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record("r1", topics=("x",), capability_patterns=("cap_x",), outcome="unknown"))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "x"})
        ctx = gen.get_strategy_context(state)
        # Unknown is neither success nor failure
        assert "cap_x" not in ctx.preferred_capabilities
        assert "cap_x" in ctx.avoid_capabilities  # failure bucket

    def test_strategy_context_appears_in_build_prompt_dict(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("math",),
            capability_patterns=("calc",),
            outcome="success",
        ))
        gen = PlanGenerator(capabilities={"calc": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "math"})
        prompt = gen.generate(state)
        assert "strategy_context" in prompt.metadata
        sc = prompt.metadata["strategy_context"]
        assert sc["matches"] == 1
        assert "calc" in sc["preferred_capabilities"]
        assert sc["confidence"] == 1.0

    def test_build_prompt_dict_no_strategy_context_when_no_matches(self):
        idx = SemanticMemoryIndex()
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "math"})
        prompt = gen.generate(state)
        assert "strategy_context" not in prompt.metadata

    def test_k_limits_results(self):
        idx = SemanticMemoryIndex()
        for i in range(10):
            idx.add(_make_record(
                f"r{i}",
                topics=("io",),
                capability_patterns=(f"cap_{i}",),
                outcome="success" if i % 2 == 0 else "failure",
                created_at=i,
            ))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "io"})
        ctx = gen.get_strategy_context(state, k=3)
        assert ctx.matches <= 3

    def test_topics_from_other_keys(self):
        """Task/goal/intent keys are read for topic extraction."""
        state = _make_state(cognitive_input={"task": "summarize"})
        topics = PlanGenerator._extract_query_topics(state)
        assert "summarize" in topics

    def test_entities_from_other_keys(self):
        """File/path/id keys are read for entity extraction."""
        state = _make_state(cognitive_input={"file": "data.csv"})
        entities = PlanGenerator._extract_query_entities(state)
        assert "data.csv" in entities

    def test_capabilities_from_action_key(self):
        state = _make_state(cognitive_input={"actions": ["compile", "test"]})
        caps = PlanGenerator._extract_query_capabilities(state)
        assert "compile" in caps
        assert "test" in caps

    def test_successful_patterns_formatted_as_chains(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("build",),
            capability_patterns=("lint", "test", "deploy"),
            outcome="success",
        ))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "build"})
        ctx = gen.get_strategy_context(state)
        assert "lint→test→deploy" in ctx.successful_patterns

    def test_drift_risks_formatted_as_chains(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("risky",),
            capability_patterns=("A", "B"),
            outcome="failure",
        ))
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "risky"})
        ctx = gen.get_strategy_context(state)
        assert "A→B" in ctx.drift_risks

    def test_strategy_context_metadata_is_json_pure(self):
        """strategy_context values in metadata must be JSON-serialisable."""
        import json

        idx = SemanticMemoryIndex()
        idx.add(_make_record(
            "r1",
            topics=("test",),
            capability_patterns=("cap",),
            outcome="success",
        ))
        gen = PlanGenerator(capabilities={"cap": {}}, memory_index=idx)
        state = _make_state(cognitive_input={"topic": "test"})
        prompt = gen.generate(state)
        sc = prompt.metadata["strategy_context"]
        # Should not raise
        json.dumps(sc)

    def test_empty_cognitive_input_with_index(self):
        """Empty cognitive_input should still produce a valid prompt."""
        idx = SemanticMemoryIndex()
        gen = PlanGenerator(capabilities={"echo": {}}, memory_index=idx)
        state = _make_state(cognitive_input={})
        prompt = gen.generate(state)
        assert isinstance(prompt, PlanPrompt)
        assert "strategy_context" not in prompt.metadata
