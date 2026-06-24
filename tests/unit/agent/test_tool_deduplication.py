"""Tests for Phase 2 tool-deduplication and large-output summarisation.

Covers:
- ``_summarize_large_output`` — truncation format and threshold boundary
- Dedup — consecutive same-tool merging, different-tool separation,
  large-output detection in merged results
"""

from __future__ import annotations

import pytest

from src.agent.tool_orchestrator import (
    _summarize_large_output,
    _TOOL_OUTPUT_THRESHOLD,
)


class TestSummarizeLargeOutput:
    """Tests for ``_summarize_large_output``."""

    def test_summary_header_always_present(self) -> None:
        """_summarize_large_output always wraps content in a summary header."""
        result = _summarize_large_output("small content", "read_file")
        assert "[SUMMARISED OUTPUT: read_file" in result
        assert "small content" in result

    def test_includes_character_count(self) -> None:
        """The header includes the total character count."""
        result = _summarize_large_output("hello", "read_file")
        assert "5 chars" in result

    def test_first_and_last_chunks_for_large_output(self) -> None:
        """Large output has first/last chunks preserved."""
        chunk_size = _TOOL_OUTPUT_THRESHOLD // 10
        large = "A" * chunk_size + "B" * (chunk_size * 5) + "C" * chunk_size
        result = _summarize_large_output(large, "read_file")
        assert f"---first {chunk_size} chars---" in result
        assert f"---last {chunk_size} chars---" in result
        assert ("A" * chunk_size) in result
        assert ("C" * chunk_size) in result

    def test_no_separate_last_chunk_for_small_output(self) -> None:
        """Small output doesn't have a separate 'last chunk' section."""
        result = _summarize_large_output("small", "list_dir")
        assert "---last" not in result

    def test_empty_string(self) -> None:
        """Empty string gets header with 0 chars."""
        result = _summarize_large_output("", "list_dir")
        assert "[SUMMARISED OUTPUT: list_dir" in result
        assert "0 chars" in result

    def test_tool_name_in_header(self) -> None:
        """The tool name appears in the summary header."""
        result = _summarize_large_output("some content", "run_tests")
        assert "run_tests" in result


def _make_pe(
    name: str,
    result_str: str,
    tool_call_id: str = "call_123",
) -> dict:
    """Build a minimal ``executed_primitives`` dict."""
    return {
        "tool_call_id": tool_call_id,
        "name": name,
        "result_str": result_str,
    }


class TestToolResultDedup:
    """Tests for the dedup + large-output logic in ``_run_follow_up_llm``.

    We test the algorithm in isolation by simulating what happens when
    ``executed_primitives`` are processed into ``conversation_history``.
    """

    def _run(self, executed_primitives: list[dict]) -> list[dict]:
        """Run the dedup/merge logic and return appended tool-result messages."""
        # ── Replicate lines 441-472 of tool_orchestrator.py ──
        from typing import List, Optional

        conversation_history: list[dict] = []
        prev_tool_name: Optional[str] = None
        merged_content: List[str] = []
        merged_pe: dict | None = None

        for pe in executed_primitives:
            tool_name = pe.get("name", "")
            if tool_name and tool_name == prev_tool_name and merged_content:
                merged_content.append(pe["result_str"])
                continue

            if merged_content:
                content = (
                    "\n\n---\n\n".join(merged_content)
                    if len(merged_content) > 1
                    else merged_content[0]
                )
                conversation_history.append({
                    "role": "tool",
                    "tool_call_id": merged_pe["tool_call_id"],
                    "content": (
                        _summarize_large_output(content, prev_tool_name)
                        if len(content) > _TOOL_OUTPUT_THRESHOLD
                        else content
                    ),
                })

            prev_tool_name = tool_name
            merged_content = [pe["result_str"]]
            merged_pe = pe

        if merged_content:
            content = (
                "\n\n---\n\n".join(merged_content)
                if len(merged_content) > 1
                else merged_content[0]
            )
            conversation_history.append({
                "role": "tool",
                "tool_call_id": merged_pe["tool_call_id"],
                "content": (
                    _summarize_large_output(content, prev_tool_name)
                    if len(content) > _TOOL_OUTPUT_THRESHOLD
                    else content
                ),
            })

        return conversation_history

    def test_single_tool_call(self) -> None:
        """A single tool call produces one tool-result message."""
        result = self._run([_make_pe("read_file", "file content")])
        assert len(result) == 1
        assert result[0]["content"] == "file content"

    def test_consecutive_same_tool_merged(self) -> None:
        """Consecutive calls to the same tool are merged into one message."""
        result = self._run([
            _make_pe("read_file", "content A"),
            _make_pe("read_file", "content B"),
        ])
        assert len(result) == 1
        assert "---" in result[0]["content"]  # merged separator
        assert "content A" in result[0]["content"]
        assert "content B" in result[0]["content"]

    def test_different_tools_not_merged(self) -> None:
        """Calls to different tools produce separate messages."""
        result = self._run([
            _make_pe("read_file", "file content"),
            _make_pe("list_dir", "dir listing"),
        ])
        assert len(result) == 2
        assert result[0]["content"] == "file content"
        assert result[1]["content"] == "dir listing"

    def test_same_tool_interleaved_not_merged(self) -> None:
        """Same tool with a different tool in between are NOT merged."""
        result = self._run([
            _make_pe("read_file", "content A"),
            _make_pe("list_dir", "listing"),
            _make_pe("read_file", "content B"),
        ])
        assert len(result) == 3  # each tool call is separate
        assert result[0]["content"] == "content A"
        assert result[1]["content"] == "listing"
        assert result[2]["content"] == "content B"

    def test_merged_large_content_summarised(self) -> None:
        """Merged content exceeding threshold is summarised."""
        big = "x" * (_TOOL_OUTPUT_THRESHOLD + 1)
        result = self._run([
            _make_pe("run_tests", big),
            _make_pe("run_tests", big),
        ])
        assert len(result) == 1
        assert "[SUMMARISED OUTPUT: run_tests" in result[0]["content"]

    def test_first_tool_call_id_used(self) -> None:
        """The tool_call_id of the *first* merged entry is used."""
        result = self._run([
            _make_pe("read_file", "a", tool_call_id="call_1"),
            _make_pe("read_file", "b", tool_call_id="call_2"),
        ])
        # merged_pe is set when a NEW group starts (first entry in group)
        assert result[0]["tool_call_id"] == "call_1"

    def test_consecutive_same_tool_many_entries(self) -> None:
        """Many consecutive same-tool calls are all merged together."""
        entries = [_make_pe("search", f"result_{i}") for i in range(20)]
        result = self._run(entries)
        assert len(result) == 1
        for i in range(20):
            assert f"result_{i}" in result[0]["content"]

    def test_mixed_tools_separate_groups(self) -> None:
        """Multiple groups of same-tool calls create separate merged entries."""
        result = self._run([
            _make_pe("read_file", "a"),
            _make_pe("read_file", "b"),
            _make_pe("list_dir", "c"),
            _make_pe("list_dir", "d"),
            _make_pe("search", "e"),
        ])
        assert len(result) == 3
        assert "---" in result[0]["content"]  # read_file merged
        assert "---" in result[1]["content"]  # list_dir merged
        assert "---" not in result[2]["content"]  # single search
        assert result[2]["content"] == "e"
