"""
Tests for Merge Strategies.
============================

Covers:
- execute_merge with concat, select_best, custom strategies
- summarize_llm placeholder
- Empty / single-result edge cases
- MergeError for unknown strategy
- Custom strategy registration
"""

from __future__ import annotations

import pytest

from src.agent.decomposition.merge import (
    MergeError,
    execute_merge,
    get_merge_strategies,
    register_merge_strategy,
)
from src.agent.types.decomposition import MergeResult


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _result(output: str) -> dict:
    return {"output": output}


# ══════════════════════════════════════════════════════════════════════════════
# concat
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeConcat:
    def test_single_result(self) -> None:
        result = execute_merge("concat", {"a": _result("hello")})
        assert isinstance(result, MergeResult)
        assert result.strategy == "concat"
        assert "hello" in result.output

    def test_multiple_results(self) -> None:
        result = execute_merge(
            "concat",
            {"a": _result("first"), "b": _result("second")},
        )
        assert "first" in result.output
        assert "second" in result.output

    def test_empty_results(self) -> None:
        result = execute_merge("concat", {})
        assert result.output == ""

    def test_fallback_to_result_key(self) -> None:
        """When 'output' key is missing, fall back to 'result' then str()."""
        result = execute_merge("concat", {"a": {"result": "fallback"}})
        assert "fallback" in result.output

    def test_child_summaries(self) -> None:
        result = execute_merge("concat", {"a": _result("short")})
        assert "a" in result.child_summaries

    def test_long_output_truncated_in_summary(self) -> None:
        long_text = "word " * 100
        result = execute_merge("concat", {"a": _result(long_text)})
        summary = result.child_summaries["a"]
        assert summary.endswith("...")


# ══════════════════════════════════════════════════════════════════════════════
# select_best
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeSelectBest:
    def test_selects_longest_output(self) -> None:
        result = execute_merge(
            "select_best",
            {"a": _result("short"), "b": _result("a longer output value")},
        )
        assert result.selected == "b"
        assert result.output == "a longer output value"

    def test_empty_results(self) -> None:
        result = execute_merge("select_best", {})
        assert result.output == ""
        assert result.selected is None

    def test_single_result_is_selected(self) -> None:
        result = execute_merge("select_best", {"a": _result("only one")})
        assert result.selected == "a"

    def test_ties_pick_first(self) -> None:
        """When two results have the same length, max() picks first key."""
        result = execute_merge(
            "select_best",
            {"a": _result("same"), "b": _result("same")},
        )
        # Both have length 4, dict iteration order gives 'a' first
        assert result.selected == "a"


# ══════════════════════════════════════════════════════════════════════════════
# summarize_llm
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeSummarizeLlm:
    def test_returns_placeholder(self) -> None:
        result = execute_merge(
            "summarize_llm",
            {"a": _result("test")},
            parent_task="do things",
        )
        assert result.strategy == "summarize_llm"
        assert result.satisfaction_gap is not None
        assert "LLM merge not executed" in result.satisfaction_gap

    def test_returns_formatted_output(self) -> None:
        result = execute_merge("summarize_llm", {"a": _result("hello")})
        assert "hello" in result.output
        assert "Subtask: a" in result.output


# ══════════════════════════════════════════════════════════════════════════════
# custom strategy
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeCustom:
    def test_registered_custom_strategy(self) -> None:
        def my_merge(results, parent_task=""):
            return MergeResult(
                output=f"custom({len(results)} results)",
                strategy="custom_test",
            )

        register_merge_strategy("custom_test", my_merge)
        try:
            result = execute_merge("custom_test", {"a": _result("x")})
            assert result.output == "custom(1 results)"
        finally:
            # Clean up registry
            from src.agent.decomposition.merge import _MERGE_REGISTRY

            _MERGE_REGISTRY.pop("custom_test", None)

    def test_custom_strategy_appears_in_list(self) -> None:
        def dummy(results, parent_task=""):
            return MergeResult(output="dummy", strategy="dummy")

        register_merge_strategy("dummy", dummy)
        try:
            strategies = get_merge_strategies()
            assert "dummy" in strategies
        finally:
            from src.agent.decomposition.merge import _MERGE_REGISTRY

            _MERGE_REGISTRY.pop("dummy", None)


# ══════════════════════════════════════════════════════════════════════════════
# error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeErrors:
    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(MergeError, match="Unknown merge strategy"):
            execute_merge("nonexistent", {})
