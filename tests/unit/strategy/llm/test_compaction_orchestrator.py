"""Tests for CompactionOrchestrator and compaction infrastructure."""

from __future__ import annotations

import copy
from typing import Dict, List, Optional

import pytest

from src.agent.memory.compaction import (
    CompactionConfig,
    CompactionOrchestrator,
    CompactionResult,
    CompactionTrigger,
    StructuredState,
)
from src.agent.memory.compaction.compaction_orchestrator import (
    _parse_structured_state,
)
from src.agent.memory.compaction.summary_prompts import (
    CONVERSATION_SUMMARY_SYSTEM,
    CONVERSATION_SUMMARY_USER,
    STATE_EXTRACTION_SYSTEM,
    STATE_EXTRACTION_USER,
    SUBGOAL_COMPLETION_SYSTEM,
    SUBGOAL_COMPLETION_USER,
)
from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.types.subgoal import Subgoal, SubgoalLifecycleState


# ── Helpers ──────────────────────────────────────────────────────────────


def _dummy_llm(text: str) -> str:
    """Dummy LLM that returns a canned summary."""
    return "Compact summary of earlier conversation."


def _error_llm(text: str) -> str:
    """LLM that always raises."""
    raise RuntimeError("LLM call failed")


def _make_history(num_turns: int, tokens_per_turn: int = 100) -> List[Dict]:
    """Build a synthetic conversation history.

    Each turn consists of one user message and one assistant message.
    Messages are padded with filler text to approximate *tokens_per_turn*.
    """
    history: List[Dict] = []
    filler = "word " * (tokens_per_turn // 3)
    for i in range(num_turns):
        history.append({"role": "user", "content": f"Message {i}a. {filler}"})
        history.append({"role": "assistant", "content": f"Response {i}b. {filler}"})
    return history


# ── CompactionConfig tests ────────────────────────────────────────────────


class TestCompactionConfig:
    def test_defaults(self) -> None:
        cfg = CompactionConfig()
        assert cfg.enabled is True
        assert cfg.context_pressure_threshold == 0.8
        assert cfg.turn_count_threshold == 10
        assert cfg.keep_recent_turns == 4
        assert cfg.summary_style == "prose"
        assert cfg.min_tokens_for_compaction == 2000

    def test_from_dict_full(self) -> None:
        cfg = CompactionConfig.from_dict({
            "enabled": False,
            "context_pressure_threshold": 0.9,
            "turn_count_threshold": 5,
            "keep_recent_turns": 2,
            "summary_style": "structured",
            "min_tokens_for_compaction": 1000,
        })
        assert cfg.enabled is False
        assert cfg.context_pressure_threshold == 0.9
        assert cfg.turn_count_threshold == 5
        assert cfg.keep_recent_turns == 2
        assert cfg.summary_style == "structured"
        assert cfg.min_tokens_for_compaction == 1000

    def test_from_dict_partial(self) -> None:
        cfg = CompactionConfig.from_dict({"enabled": False})
        assert cfg.enabled is False
        # unspecified fields fall back to defaults
        assert cfg.turn_count_threshold == 10

    def test_from_dict_empty(self) -> None:
        cfg = CompactionConfig.from_dict({})
        assert cfg.enabled is True
        assert cfg.turn_count_threshold == 10


# ── CompactionResult tests ────────────────────────────────────────────────


class TestCompactionResult:
    def test_defaults(self) -> None:
        r = CompactionResult()
        assert r.triggered is False
        assert r.trigger is None
        assert r.turns_before == 0
        assert r.turns_after == 0
        assert r.tokens_before == 0
        assert r.tokens_after == 0
        assert r.summary is None
        assert r.error is None


# ── CompactionTrigger enum tests ──────────────────────────────────────────


class TestCompactionTrigger:
    def test_members(self) -> None:
        assert CompactionTrigger.CONTEXT_PRESSURE.value == "context_pressure"
        assert CompactionTrigger.TURN_COUNT.value == "turn_count"
        assert CompactionTrigger.SUBGOAL_CLOSED.value == "subgoal_closed"
        assert CompactionTrigger.MANUAL.value == "manual"


# ── CompactionOrchestrator – disabled / edge cases ────────────────────────


class TestCompactionOrchestratorDisabled:
    def test_disabled_via_config(self) -> None:
        cfg = CompactionConfig(enabled=False)
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(20)
        result = orch.compact_if_needed(hist)
        assert result.triggered is False
        # history is unchanged
        assert len(hist) == 40  # 20 turns × 2 entries

    def test_empty_history(self) -> None:
        orch = CompactionOrchestrator(llm_complete=_dummy_llm)
        result = orch.compact_if_needed([])
        assert result.triggered is False

    def test_history_below_min_tokens(self) -> None:
        """Trivially short history should not trigger compaction."""
        cfg = CompactionConfig(min_tokens_for_compaction=100_000)
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(5)
        result = orch.compact_if_needed(hist)
        assert result.triggered is False

    def test_history_shorter_than_keep_recent(self) -> None:
        cfg = CompactionConfig(turn_count_threshold=2)
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(1)  # 1 turn = 2 entries < keep_recent_turns*2
        result = orch.compact_if_needed(hist)
        assert result.triggered is False


# ── CompactionOrchestrator – turn-count trigger ───────────────────────────


class TestCompactionOrchestratorTurnCount:
    def test_below_threshold_does_not_trigger(self) -> None:
        cfg = CompactionConfig(turn_count_threshold=10)
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(5)  # 5 user turns < 10
        result = orch.compact_if_needed(hist)
        assert result.triggered is False

    def test_at_threshold_triggers(self) -> None:
        cfg = CompactionConfig(
            turn_count_threshold=5,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,  # low floor
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(6)  # 6 user turns ≥ 5
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.trigger == CompactionTrigger.TURN_COUNT
        assert result.summary == "Compact summary of earlier conversation."

    def test_above_threshold_triggers(self) -> None:
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=1,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(10)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.trigger == CompactionTrigger.TURN_COUNT
        # Should have 1 summary + keep_recent_turns*2 entries
        assert result.turns_after == 3  # 1 summary + 1 turn (2 entries)

    def test_compacted_history_structure(self) -> None:
        """After compaction, history starts with an assistant summary entry
        followed by the recent un-compacted turns."""
        cfg = CompactionConfig(
            turn_count_threshold=4,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(8)
        _ = orch.compact_if_needed(hist)
        # First entry should be an assistant summary
        assert hist[0]["role"] == "assistant"
        assert "[Compacted summary" in hist[0]["content"]
        # Remaining entries should be the last 2 turns
        assert len(hist) == 5  # 1 summary + 2 turns × 2 entries
        assert hist[1]["role"] == "user"
        assert "Message 6a" in hist[1]["content"]
        assert hist[3]["role"] == "user"
        assert "Message 7a" in hist[3]["content"]


# ── CompactionOrchestrator – context-pressure trigger ─────────────────────


class TestCompactionOrchestratorContextPressure:
    def test_low_pressure_does_not_trigger(self) -> None:
        cfg = CompactionConfig(
            context_pressure_threshold=0.8,
            turn_count_threshold=100,  # high enough to not fire
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(15)
        result = orch.compact_if_needed(hist, context_pressure=0.5)
        assert result.triggered is False

    def test_high_pressure_triggers(self) -> None:
        cfg = CompactionConfig(
            context_pressure_threshold=0.8,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(15)
        result = orch.compact_if_needed(hist, context_pressure=0.9)
        assert result.triggered is True
        assert result.trigger == CompactionTrigger.CONTEXT_PRESSURE

    def test_pressure_triggers_before_turn_count(self) -> None:
        """context_pressure should take priority over turn_count."""
        cfg = CompactionConfig(
            context_pressure_threshold=0.7,
            turn_count_threshold=5,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(15)
        result = orch.compact_if_needed(hist, context_pressure=0.9)
        assert result.trigger == CompactionTrigger.CONTEXT_PRESSURE


# ── CompactionOrchestrator – LLM error handling ──────────────────────────


class TestCompactionOrchestratorErrors:
    def test_llm_error_returns_result_with_error(self) -> None:
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=1,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_error_llm, config=cfg)
        hist = _make_history(10)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.error is not None
        assert "LLM call failed" in result.error
        # History should be unchanged on error
        assert len(hist) == 20


# ── CompactionOrchestrator – token tracking ──────────────────────────────


class TestCompactionOrchestratorTokenTracking:
    def test_tokens_before_and_after_reported(self) -> None:
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=1,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(10, tokens_per_turn=30)
        result = orch.compact_if_needed(hist)
        assert result.tokens_before > 0
        assert result.tokens_after > 0
        # Compacted history should have fewer tokens
        assert result.tokens_after < result.tokens_before


# ── CompactionOrchestrator – subgoal closed ────────────────────────────


class TestCompactionOrchestratorSubgoalClosed:
    def test_queues_subgoal_for_next_pass_without_memory(self) -> None:
        """Without subgoal_memory, on_subgoal_closed queues the subgoal."""
        orch = CompactionOrchestrator(llm_complete=_dummy_llm)
        result = orch.on_subgoal_closed(
            subgoal_id="sg-1", goal="test goal", context='{"key": "val"}'
        )
        assert result.triggered is True
        assert result.trigger == CompactionTrigger.SUBGOAL_CLOSED
        assert "sg-1" in orch._notified_subgoal_ids

    def test_queues_subgoal_with_memory(self) -> None:
        """With subgoal_memory, on_subgoal_closed queues known CLOSED subgoals."""
        mem = SubgoalMemory()
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="test goal",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CLOSED,
        )
        mem.put(sg)
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, subgoal_memory=mem)
        result = orch.on_subgoal_closed(
            subgoal_id="sg-1", goal="test goal", context="{}"
        )
        assert result.triggered is True
        assert "sg-1" in orch._notified_subgoal_ids

    def test_queues_unknown_subgoal(self) -> None:
        """Subgoal not in memory yet is still queued for later discovery."""
        mem = SubgoalMemory()
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, subgoal_memory=mem)
        result = orch.on_subgoal_closed(
            subgoal_id="sg-missing", goal="unknown", context="{}"
        )
        assert result.triggered is True
        assert "sg-missing" in orch._notified_subgoal_ids

    def test_idempotent(self) -> None:
        """Calling on_subgoal_closed twice for the same subgoal is a no-op."""
        orch = CompactionOrchestrator(llm_complete=_dummy_llm)
        orch._notified_subgoal_ids.add("sg-1")
        result = orch.on_subgoal_closed(
            subgoal_id="sg-1", goal="test", context="{}"
        )
        assert result.triggered is False
        assert result.trigger is None


# ── CompactionOrchestrator – SUBGOAL_CLOSED trigger via memory scan ────


class TestCompactionOrchestratorSubgoalMemoryScan:
    def test_compact_if_needed_discovers_closed_subgoal(self) -> None:
        """compact_if_needed scans subgoal memory for un-compacted CLOSED
        subgoals and fires SUBGOAL_CLOSED trigger."""
        mem = SubgoalMemory()
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="Implement user auth",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CLOSED,
        )
        mem.put(sg)

        cfg = CompactionConfig(
            context_pressure_threshold=1.0,   # won't fire
            turn_count_threshold=100,          # won't fire
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(
            llm_complete=_dummy_llm, config=cfg, subgoal_memory=mem,
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)

        assert result.triggered is True
        assert result.trigger == CompactionTrigger.SUBGOAL_CLOSED
        assert "sg-1" in orch._compacted_subgoal_ids

    def test_uses_subgoal_prompts(self) -> None:
        """SUBGOAL_CLOSED trigger uses SUBGOAL_COMPLETION prompts with the
        subgoal goal."""
        mem = SubgoalMemory()
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="Write unit tests for parser",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CLOSED,
        )
        mem.put(sg)

        captured_prompt: list[str] = []

        def capturing_llm(text: str) -> str:
            captured_prompt.append(text)
            return "Compact subgoal summary."

        cfg = CompactionConfig(
            turn_count_threshold=100,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(
            llm_complete=capturing_llm, config=cfg, subgoal_memory=mem,
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)

        assert result.triggered is True
        assert result.trigger == CompactionTrigger.SUBGOAL_CLOSED
        # Verify the LLM was called with subgoal-specific prompts containing the goal
        prompt_text = captured_prompt[0]
        assert "Write unit tests for parser" in prompt_text
        assert "subgoal" in prompt_text.lower() or "task summarizer" in prompt_text.lower()

    def test_already_compacted_subgoal_ignored(self) -> None:
        """A CLOSED subgoal already in _compacted_subgoal_ids is skipped."""
        mem = SubgoalMemory()
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="Test goal",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CLOSED,
        )
        mem.put(sg)

        cfg = CompactionConfig(
            turn_count_threshold=100,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(
            llm_complete=_dummy_llm, config=cfg, subgoal_memory=mem,
        )
        orch._compacted_subgoal_ids.add("sg-1")

        hist = _make_history(8)
        result = orch.compact_if_needed(hist)

        # No trigger should fire — the only available subgoal is already compacted
        assert result.triggered is False

    def test_non_closed_subgoal_not_triggered(self) -> None:
        """Subgoals in ACTIVE/SATISFIED state are ignored."""
        mem = SubgoalMemory()
        mem.put(Subgoal(
            subgoal_id="sg-active", goal="Active",
            context={}, metadata={}, state=SubgoalLifecycleState.ACTIVE,
        ))
        mem.put(Subgoal(
            subgoal_id="sg-satisfied", goal="Satisfied",
            context={}, metadata={}, state=SubgoalLifecycleState.SATISFIED,
        ))

        cfg = CompactionConfig(
            turn_count_threshold=100,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(
            llm_complete=_dummy_llm, config=cfg, subgoal_memory=mem,
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)

        assert result.triggered is False

    def test_subgoal_trigger_respects_min_tokens(self) -> None:
        """SUBGOAL_CLOSED trigger still honours min_tokens_for_compaction."""
        mem = SubgoalMemory()
        mem.put(Subgoal(
            subgoal_id="sg-1", goal="Test",
            context={}, metadata={}, state=SubgoalLifecycleState.CLOSED,
        ))
        cfg = CompactionConfig(
            turn_count_threshold=100,
            min_tokens_for_compaction=1_000_000,  # impossibly high
        )
        orch = CompactionOrchestrator(
            llm_complete=_dummy_llm, config=cfg, subgoal_memory=mem,
        )
        hist = _make_history(3)
        result = orch.compact_if_needed(hist)

        # Trigger fires but compaction is skipped due to token floor
        assert result.triggered is False


# ── Summary prompts smoke test ────────────────────────────────────────────


class TestSummaryPrompts:
    def test_conversation_summary_user_formats_history(self) -> None:
        text = CONVERSATION_SUMMARY_USER.format(history="test history content")
        assert "test history content" in text
        assert "What has been accomplished" in text

    def test_conversation_summary_system_not_empty(self) -> None:
        assert len(CONVERSATION_SUMMARY_SYSTEM) > 20


# ── CompactionOrchestrator – idempotency ─────────────────────────────────


class TestCompactionOrchestratorIdempotency:
    def test_compacting_already_compacted_history(self) -> None:
        """If history was already compacted (only 1 summary + recent),
        running compact_if_needed again should be a no-op since there
        aren't enough turns left to trigger."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
        )
        orch = CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)
        hist = _make_history(8)
        # First compaction
        result1 = orch.compact_if_needed(hist)
        assert result1.triggered is True
        # Second compaction — not enough turns left
        result2 = orch.compact_if_needed(hist)
        assert result2.triggered is False


# ── Phase 3 — Structured State Extraction ─────────────────────────────────


def _json_llm(text: str) -> str:
    """Dummy LLM that returns valid structured JSON."""
    return (
        '{\n'
        '  "goal": "Build the thing",\n'
        '  "current_focus": "Writing tests",\n'
        '  "completed": ["Setup", "Core logic"],\n'
        '  "blocked": [],\n'
        '  "next_steps": ["Write docs"],\n'
        '  "important_decisions": ["Use JSON format"],\n'
        '  "open_questions": ["Deployment strategy?"],\n'
        '  "files_created": ["src/main.py"],\n'
        '  "files_modified": ["README.md"],\n'
        '  "errors_encountered": []\n'
        '}'
    )


def _fenced_json_llm(text: str) -> str:
    """Dummy LLM returning JSON inside markdown fences."""
    return "```json\n" + _json_llm("") + "\n```"


def _invalid_json_llm(text: str) -> str:
    """Dummy LLM returning non-JSON text."""
    return "Here is a plain text summary of the conversation."


class TestParseStructuredState:
    """Tests for the ``_parse_structured_state`` helper."""

    def test_parse_raw_json(self) -> None:
        data = _json_llm("")
        result = _parse_structured_state(data)
        assert result is not None
        assert isinstance(result, StructuredState)
        assert result.goal == "Build the thing"
        assert result.current_focus == "Writing tests"
        assert result.completed == ["Setup", "Core logic"]
        assert result.blocked == []
        assert result.next_steps == ["Write docs"]

    def test_parse_fenced_json(self) -> None:
        data = _fenced_json_llm("")
        result = _parse_structured_state(data)
        assert result is not None
        assert result.goal == "Build the thing"

    def test_parse_fenced_without_lang(self) -> None:
        data = "```\n" + _json_llm("") + "\n```"
        result = _parse_structured_state(data)
        assert result is not None
        assert result.goal == "Build the thing"

    def test_parse_plain_text_returns_none(self) -> None:
        result = _parse_structured_state("This is just a paragraph.")
        assert result is None

    def test_parse_invalid_json_returns_none(self) -> None:
        result = _parse_structured_state("{bad json}")
        assert result is None

    def test_parse_json_array_returns_none(self) -> None:
        """A JSON array is valid JSON but not a dict → from_dict expects dict."""
        result = _parse_structured_state('["item1", "item2"]')
        assert result is None

    def test_parse_empty_string_returns_none(self) -> None:
        result = _parse_structured_state("")
        assert result is None


class TestStructuredState:
    """Tests for the ``StructuredState`` dataclass."""

    def test_from_dict_full(self) -> None:
        data = {
            "goal": "Test goal",
            "current_focus": "Testing",
            "completed": ["A", "B"],
            "blocked": ["C"],
            "next_steps": ["D"],
            "important_decisions": ["Use pytest"],
            "open_questions": ["Why?"],
            "files_created": ["test.py"],
            "files_modified": ["src.py"],
            "errors_encountered": ["Bug"],
        }
        state = StructuredState.from_dict(data)
        assert state.goal == "Test goal"
        assert state.completed == ["A", "B"]
        assert state.errors_encountered == ["Bug"]

    def test_from_dict_empty(self) -> None:
        state = StructuredState.from_dict({})
        assert state.goal == ""
        assert state.current_focus == ""
        assert state.completed == []
        assert state.blocked == []
        assert state.next_steps == []
        assert state.important_decisions == []

    def test_from_dict_partial(self) -> None:
        state = StructuredState.from_dict({"goal": "Only goal", "completed": ["X"]})
        assert state.goal == "Only goal"
        assert state.current_focus == ""
        assert state.completed == ["X"]
        assert state.blocked == []

    def test_from_dict_coerces_single_value_to_list(self) -> None:
        """If a list field is a single string, it gets wrapped in a list."""
        state = StructuredState.from_dict({"completed": "Single item"})
        assert state.completed == ["Single item"]

    def test_from_dict_ignores_none_items(self) -> None:
        state = StructuredState.from_dict({"completed": ["A", None, "B"]})
        assert state.completed == ["A", "B"]

    def test_from_dict_ignores_unknown_keys(self) -> None:
        state = StructuredState.from_dict({"goal": "G", "unknown_key": "val"})
        assert state.goal == "G"

    def test_format_for_injection_all_fields(self) -> None:
        state = StructuredState(
            goal="Goal",
            current_focus="Focus",
            completed=["Done1"],
            blocked=["Block1"],
            next_steps=["Next1"],
            important_decisions=["Dec1"],
            open_questions=["Q1"],
            files_created=["f1.py"],
            files_modified=["f2.py"],
            errors_encountered=["Err1"],
        )
        output = state.format_for_injection()
        assert "[CURRENT STATE]" in output
        assert "Goal: Goal" in output
        assert "Focus: Focus" in output
        assert "Done1" in output
        assert "Block1" in output
        assert "Next1" in output
        assert "Dec1" in output
        assert "Q1" in output
        assert "f1.py" in output
        assert "f2.py" in output
        assert "Err1" in output

    def test_format_for_injection_empty(self) -> None:
        state = StructuredState()
        output = state.format_for_injection()
        assert output == "[CURRENT STATE]"

    def test_format_for_injection_partial(self) -> None:
        state = StructuredState(goal="Only goal")
        output = state.format_for_injection()
        assert "[CURRENT STATE]" in output
        assert "Goal: Only goal" in output
        assert "Focus:" not in output


class TestCompactionOrchestratorStructured:
    """Phase 3 — orchestrator behaviour with ``summary_style='structured'``."""

    def test_compact_with_structured_style(self) -> None:
        """Uses structured prompts and returns a ``CompactionResult`` with
        ``structured_state`` populated."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(llm_complete=_json_llm, config=cfg)
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.structured_state is not None
        assert result.structured_state.goal == "Build the thing"

    def test_structured_style_injects_current_state_entry(self) -> None:
        """The conversation history gets a [CURRENT STATE] system message
        when structured extraction succeeds."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(llm_complete=_json_llm, config=cfg)
        hist = _make_history(8)
        orch.compact_if_needed(hist)
        # Should have [CURRENT STATE], summary, + 2 recent turns (4 entries)
        assert any(
            "[CURRENT STATE]" in msg.get("content", "")
            for msg in hist
        )
        assert any(
            "Compacted summary" in msg.get("content", "")
            for msg in hist
        )

    def test_structured_style_fallback_to_prose(self) -> None:
        """When the LLM returns non-JSON, falls back to prose summary and
        ``structured_state`` is None."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(
            llm_complete=_invalid_json_llm, config=cfg
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.structured_state is None
        # History should have 1 summary + recent turns (no [CURRENT STATE])
        assert not any(
            "[CURRENT STATE]" in msg.get("content", "")
            for msg in hist
        )
        assert any(
            "Compacted summary" in msg.get("content", "")
            for msg in hist
        )

    def test_subgoal_closed_uses_prose_not_structured(self) -> None:
        """Subgoal-closed trigger always uses prose, even when
        ``summary_style='structured'``."""
        mem = SubgoalMemory()
        sg = Subgoal(
            subgoal_id="sg-1",
            goal="Test subgoal",
            context={},
            metadata={},
            state=SubgoalLifecycleState.CLOSED,
        )
        mem.put(sg)

        cfg = CompactionConfig(
            turn_count_threshold=100,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(
            llm_complete=_dummy_llm, config=cfg, subgoal_memory=mem,
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.trigger == CompactionTrigger.SUBGOAL_CLOSED
        # Subgoal-closed never uses structured
        assert result.structured_state is None
        assert result.summary == "Compact summary of earlier conversation."
        # No [CURRENT STATE] in history
        assert not any(
            "[CURRENT STATE]" in msg.get("content", "")
            for msg in hist
        )

    def test_structured_with_fenced_json(self) -> None:
        """The LLM may wrap JSON in markdown fences; the orchestrator
        should still parse it."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(
            llm_complete=_fenced_json_llm, config=cfg
        )
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)
        assert result.triggered is True
        assert result.structured_state is not None
        assert result.structured_state.goal == "Build the thing"

    def test_structured_turns_after_includes_state_entry(self) -> None:
        """``turns_after`` should account for the extra [CURRENT STATE]
        entry (counts message entries, not turn pairs)."""
        cfg = CompactionConfig(
            turn_count_threshold=3,
            keep_recent_turns=2,
            min_tokens_for_compaction=10,
            summary_style="structured",
        )
        orch = CompactionOrchestrator(llm_complete=_json_llm, config=cfg)
        hist = _make_history(8)
        result = orch.compact_if_needed(hist)
        # 8 turns = 16 messages. keep_recent_turns=2 → 4 recent messages.
        # After: state_entry (1) + summary_entry (1) + 4 recent = 6 entries
        assert result.turns_after == 6
