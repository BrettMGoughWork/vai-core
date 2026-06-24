"""Unit tests for council prompt builders."""

from src.agent.council.prompts import (
    build_analysis_prompt,
    build_arbitration_prompt,
    build_counter_prompt,
)


class TestAnalysisPrompt:
    """build_analysis_prompt produces the member's independent analysis prompt."""

    def test_includes_problem(self) -> None:
        """Prompt contains the problem statement."""
        prompt = build_analysis_prompt("Should we refactor?", "critic")
        assert "Should we refactor?" in prompt

    def test_includes_member_id(self) -> None:
        """Prompt includes the member's agent ID."""
        prompt = build_analysis_prompt("problem", "strategist")
        assert "strategist" in prompt


class TestCounterPrompt:
    """build_counter_prompt produces the counter-analysis prompt."""

    def test_excludes_own_analysis(self) -> None:
        """Member does NOT see their own analysis in counter phase."""
        prompt = build_counter_prompt(
            "problem",
            "m1",
            {"m1": "My analysis", "m2": "Other analysis"},
        )
        assert "My analysis" not in prompt
        assert "Other analysis" in prompt

    def test_empty_others(self) -> None:
        """No other analyses → prompt still produces output."""
        prompt = build_counter_prompt("problem", "m1", {})
        assert "Other Members' Analyses" in prompt


class TestArbitrationPrompt:
    """build_arbitration_prompt produces the arbitrator's prompt."""

    def test_includes_all_analyses(self) -> None:
        """Arbitrator sees all analyses and counters."""
        prompt = build_arbitration_prompt(
            "problem",
            {"m1": "Analysis 1", "m2": "Analysis 2"},
            {"m1": "Counter 1", "m2": "Counter 2"},
        )
        assert "Analysis 1" in prompt
        assert "Analysis 2" in prompt
        assert "Counter 1" in prompt
        assert "Counter 2" in prompt
        assert "Decision:" in prompt
        assert "Confidence:" in prompt
