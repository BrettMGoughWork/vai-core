"""Integration tests for the compaction pipeline.

Exercises the full CompactionOrchestrator lifecycle:
- Prose and structured compaction modes
- Fingerprint-based staleness guard (skip when compactable hasn't changed)
- Staleness re-trigger when compactable content changes
- Subgoal-closed trigger path
- Net-reduction rollback guard
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pytest

from src.agent.memory.compaction import (
    CompactionConfig,
    CompactionOrchestrator,
    CompactionResult,
    CompactionTrigger,
    StructuredState,
)
from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.types.subgoal import Subgoal, SubgoalLifecycleState


# ── Helpers ──────────────────────────────────────────────────────────────


def _dummy_llm(text: str) -> str:
    """Dummy LLM that returns a canned summary."""
    return "Compact summary of earlier conversation."


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


# ── Prose compaction ─────────────────────────────────────────────────────


class TestProseCompactionPipeline:
    """End-to-end prose (Phase 1) compaction pipeline."""

    @pytest.fixture
    def orchestrator(self) -> CompactionOrchestrator:
        cfg = CompactionConfig(
            summary_style="prose",
            turn_count_threshold=6,
            keep_recent_turns=2,
            min_tokens_for_compaction=100,
        )
        return CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)

    def test_prose_compaction_reduces_tokens(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Compaction triggered by TURN_COUNT reduces token count."""
        history = _make_history(num_turns=12, tokens_per_turn=60)
        tokens_before = sum(len(e["content"].split()) for e in history)

        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        assert result.trigger == CompactionTrigger.TURN_COUNT
        assert result.tokens_after < result.tokens_before
        # Verify summary entry present
        summary_entries = [
            e
            for e in history
            if e.get("role") == "system"
            and "Compacted summary" in e.get("content", "")
        ]
        assert len(summary_entries) == 1
        tokens_after = sum(len(e["content"].split()) for e in history)
        assert tokens_after < tokens_before

    def test_recent_turns_preserved(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """The most recent N turn pairs survive un-compacted."""
        history = _make_history(num_turns=12, tokens_per_turn=60)
        recent_text_before = history[-4]["content"]  # 2 turns = 4 entries

        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        # Last 4 entries (2 turns: user+assistant) should still be in history
        assert any(
            recent_text_before in e.get("content", "") for e in history[-4:]
        ), "Recent turn content should be present"

    def test_fingerprint_staleness_skips_unchanged_content(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Same compactable content → second call skips compaction."""
        history = _make_history(num_turns=12, tokens_per_turn=60)

        # First call — does actual work
        first = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )
        assert first.triggered is True

        # Second call with the same (already compacted) history
        # The compactable portion hasn't changed, so staleness should fire.
        second = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )
        assert second.triggered is False, (
            "Staleness guard should skip compaction when compactable is unchanged"
        )

    def test_fingerprint_staleness_new_content_triggers(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """New compactable content → compaction fires again."""
        history = _make_history(num_turns=12, tokens_per_turn=60)

        # Compact once
        orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        # Add enough new turns that the compactable portion changes
        for i in range(6):
            history.append({"role": "user", "content": f"New msg {i}"})
            history.append({"role": "assistant", "content": f"New resp {i}"})

        # Now compactable has new content — should trigger
        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )
        assert result.triggered is True, (
            "New compactable content should trigger compaction"
        )


# ── Structured compaction ────────────────────────────────────────────────


class TestStructuredCompactionPipeline:
    """End-to-end structured (Phase 3) compaction pipeline."""

    @pytest.fixture
    def orchestrator(self) -> CompactionOrchestrator:
        cfg = CompactionConfig(
            summary_style="structured",
            turn_count_threshold=6,
            keep_recent_turns=2,
            min_tokens_for_compaction=100,
        )
        return CompactionOrchestrator(llm_complete=_dummy_llm, config=cfg)

    def test_structured_compaction_injects_state_entry(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Structured mode produces both a [CURRENT STATE] and summary entry."""
        # The dummy LLM doesn't return valid JSON, so _parse_structured_state
        # will fail and fall back to prose.  Verify it still compacts.
        history = _make_history(num_turns=12, tokens_per_turn=60)

        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        # Fallback to prose — only one system entry
        system_entries = [
            e for e in history if e.get("role") == "system"
        ]
        assert len(system_entries) >= 1
        assert result.tokens_after < result.tokens_before


class TestStructuredCompactionJson:
    """Structured compaction with valid JSON LLM response."""

    @staticmethod
    def _structured_llm(text: str) -> str:
        return (
            '{\n'
            '  "goal": "Test goal",\n'
            '  "current_focus": "Testing",\n'
            '  "completed": ["Setup", "Run"],\n'
            '  "next_steps": ["Verify"],\n'
            '  "important_decisions": ["Use pytest"]\n'
            '}'
        )

    @pytest.fixture
    def orchestrator(self) -> CompactionOrchestrator:
        cfg = CompactionConfig(
            summary_style="structured",
            turn_count_threshold=6,
            keep_recent_turns=2,
            min_tokens_for_compaction=100,
        )
        return CompactionOrchestrator(llm_complete=self._structured_llm, config=cfg)

    def test_structured_with_valid_json(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Valid JSON from LLM produces a [CURRENT STATE] + summary pair."""
        history = _make_history(num_turns=12, tokens_per_turn=60)

        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        assert result.structured_state is not None
        assert result.structured_state.goal == "Test goal"
        assert "Setup" in result.structured_state.completed

        # Should have 2 system entries: state + summary
        system_entries = [
            e for e in history if e.get("role") == "system"
        ]
        assert len(system_entries) == 2, (
            f"Expected 2 system entries (state + summary), got {len(system_entries)}"
        )
        assert any("CURRENT STATE" in e.get("content", "") for e in system_entries)
        assert any("Compacted summary" in e.get("content", "") for e in system_entries)


# ── Subgoal-closed trigger ───────────────────────────────────────────────


class TestSubgoalClosedTrigger:
    """Integration of subgoal-closed → compaction flow."""

    @pytest.fixture
    def subgoal_memory(self) -> SubgoalMemory:
        mem = SubgoalMemory()
        mem.put(
            Subgoal(
                subgoal_id="sg-1",
                goal="Implement login",
                context={},
                metadata={},
                state=SubgoalLifecycleState.CLOSED,
            )
        )
        return mem

    @pytest.fixture
    def orchestrator(
        self, subgoal_memory: SubgoalMemory
    ) -> CompactionOrchestrator:
        cfg = CompactionConfig(
            summary_style="prose",
            turn_count_threshold=20,  # high — prevents TURN_COUNT trigger
            keep_recent_turns=2,
            min_tokens_for_compaction=100,
        )
        return CompactionOrchestrator(
            llm_complete=_dummy_llm,
            config=cfg,
            subgoal_memory=subgoal_memory,
        )

    def test_subgoal_closed_triggers_compaction(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """SUBGOAL_CLOSED trigger fires and compacts via subgoal prompt."""
        history = _make_history(num_turns=12, tokens_per_turn=60)

        # on_subgoal_closed marks the subgoal for compaction
        pre = orchestrator.on_subgoal_closed(
            subgoal_id="sg-1",
            goal="Implement login",
            context="some context",
        )
        assert pre.triggered is True  # queued

        # compact_if_needed should discover the CLOSED subgoal
        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        assert result.trigger == CompactionTrigger.SUBGOAL_CLOSED
        assert result.tokens_after < result.tokens_before

    def test_subgoal_already_compacted_skips(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Compacting a subgoal a second time is a no-op."""
        history = _make_history(num_turns=12, tokens_per_turn=60)

        # First pass
        orchestrator.on_subgoal_closed(
            subgoal_id="sg-1",
            goal="Implement login",
            context="some context",
        )
        orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        # Second pass — subgoal already tracked
        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )
        assert result.triggered is False, (
            "Already-compacted subgoal should not re-trigger"
        )


# ── Rollback guard ───────────────────────────────────────────────────────


class TestCompactionRollback:
    """Net-reduction rollback behaves correctly."""

    @pytest.fixture
    def orchestrator(self) -> CompactionOrchestrator:
        cfg = CompactionConfig(
            summary_style="prose",
            turn_count_threshold=6,
            keep_recent_turns=2,
            min_tokens_for_compaction=100,
        )
        # Use a "verbose" LLM that outputs a sufficiently long string
        # to trigger the rollback guard.
        return CompactionOrchestrator(
            llm_complete=self._verbose_llm, config=cfg
        )

    @staticmethod
    def _verbose_llm(text: str) -> str:
        """Returns a summary that's intentionally longer than the compactable content."""
        return "word " * 5000  # ~5000 tokens — guarantees no net reduction

    def test_rollback_restores_original_on_no_reduction(
        self, orchestrator: CompactionOrchestrator
    ) -> None:
        """Compaction that doesn't reduce tokens is rolled back."""
        history = _make_history(num_turns=12, tokens_per_turn=60)
        original_text = history[-4]["content"]  # from recent turns

        result = orchestrator.compact_if_needed(
            conversation_history=history, max_tokens=4096
        )

        assert result.triggered is True
        assert result.rolled_back is True, (
            "Compaction should be rolled back when no net reduction"
        )
        # Verify the original recent content is restored
        assert history[-4]["content"] == original_text
        # tokens_after should equal tokens_before after rollback
        assert result.tokens_after == result.tokens_before
