"""Tests for supervisor defer_to tool exposure and call interception.

D1.13: ``_build_defer_to_tool()`` tool schema
D1.14: Deferral tool call interception in ``run_agent_step()``
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.agent.adapters.memory_agent_state_store import MemoryAgentStateStore
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.agent.interfaces.agent_state_store import AgentStateStore
from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
)
from src.agent.supervisor import Supervisor


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_identity(
    agent_id: str = "test-agent",
    name: str = "Test Agent",
) -> AgentIdentity:
    return AgentIdentity(
        agent_id=agent_id,
        name=name,
        description="A test agent",
        version="1.0.0",
    )


def _make_metadata(
    agent_id: str = "test-agent",
    name: str = "Test Agent",
    defer_to: list[str] | None = None,
) -> AgentMetadata:
    return AgentMetadata(
        identity=_make_identity(agent_id=agent_id, name=name),
        skills=["*"],
        inputs=["text"],
        outputs=["text", "action_intents"],
        constraints=AgentConstraints(max_tokens=4096, timeout_ms=30000),
        defer_to=defer_to or [],
    )


def _make_registry_with_agents(
    pairs: list[tuple[str, str, list[str] | None]],
) -> AgentRegistry:
    """Register multiple agents.

    Each tuple: (agent_id, name, defer_to_list).
    """
    registry = AgentRegistry()
    for aid, name, defer_to in pairs:
        registry.register_agent(_make_metadata(agent_id=aid, name=name, defer_to=defer_to))
    return registry


def _make_supervisor(
    registry: AgentRegistry | None = None,
    store: AgentStateStore | None = None,
    **kwargs: Any,
) -> Supervisor:
    return Supervisor(
        registry=registry or _make_registry_with_agents([("test-agent", "Test Agent", None)]),
        store=store or MemoryAgentStateStore(),
        auto_persist=True,
        **kwargs,
    )


def _make_running_state(agent_id: str = "test-agent") -> AgentState:
    """Create a minimal RUNNING AgentState."""
    return AgentState(
        agent_id=agent_id,
        lifecycle_state=LifecycleState.RUNNING,
        timestamps={"created_at": "2024-01-01T00:00:00+00:00"},
        correlation_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        supervisor_metadata={
            "backend": "simulation",
            "max_iterations": 5,
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# D1.13 — _build_defer_to_tool
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildDeferToTool:
    """Schema generation for the synthetic defer_to LLM tool."""

    def test_returns_openai_function_tool(self):
        result = Supervisor._build_defer_to_tool(["billing", "support"])
        assert result["type"] == "function"
        assert result["function"]["name"] == "defer_to"

    def test_target_enum_constrains_to_allowed_agents(self):
        result = Supervisor._build_defer_to_tool(["billing", "support", "tech"])
        target_prop = result["function"]["parameters"]["properties"]["target"]
        assert target_prop["enum"] == ["billing", "support", "tech"]
        assert target_prop["type"] == "string"

    def test_enum_is_sorted(self):
        result = Supervisor._build_defer_to_tool(["c", "a", "b"])
        target_prop = result["function"]["parameters"]["properties"]["target"]
        assert target_prop["enum"] == ["a", "b", "c"]

    def test_prompt_is_required(self):
        result = Supervisor._build_defer_to_tool(["agent1"])
        required = result["function"]["parameters"]["required"]
        assert "target" in required
        assert "prompt" in required

    def test_prompt_parameter_is_string(self):
        result = Supervisor._build_defer_to_tool(["agent1"])
        prompt_prop = result["function"]["parameters"]["properties"]["prompt"]
        assert prompt_prop["type"] == "string"
        assert "description" in prompt_prop

    def test_single_target(self):
        result = Supervisor._build_defer_to_tool(["only-agent"])
        target_prop = result["function"]["parameters"]["properties"]["target"]
        assert target_prop["enum"] == ["only-agent"]

    def test_empty_targets_produces_empty_enum(self):
        result = Supervisor._build_defer_to_tool([])
        target_prop = result["function"]["parameters"]["properties"]["target"]
        assert target_prop["enum"] == []

    def test_description_is_present(self):
        result = Supervisor._build_defer_to_tool(["a"])
        assert len(result["function"]["description"]) > 20

    def test_parameters_is_object_type(self):
        result = Supervisor._build_defer_to_tool(["a"])
        assert result["function"]["parameters"]["type"] == "object"


# ══════════════════════════════════════════════════════════════════════════════
# D1.14 — Deferral tool call interception logic
# ══════════════════════════════════════════════════════════════════════════════


class TestDeferToToolCallDetection:
    """Tests the defer_to detection/filtering logic used in run_agent_step()."""

    @staticmethod
    def _detect_defer_to_calls(tool_calls: list) -> list:
        """Replicate the defer_to detection logic from supervisor lines 585-589."""
        return [
            tc for tc in tool_calls
            if isinstance(tc, dict) and tc.get("name", "") == "defer_to"
            or hasattr(tc, "name") and getattr(tc, "name", "") == "defer_to"
        ]

    @staticmethod
    def _filter_defer_to_calls(tool_calls: list) -> list:
        """Replicate the defer_to filtering logic from supervisor lines 607-617."""
        return [
            tc for tc in tool_calls
            if (
                isinstance(tc, dict)
                and tc.get("name", "") != "defer_to"
            )
            or (
                hasattr(tc, "name")
                and getattr(tc, "name", "") != "defer_to"
            )
        ]

    def test_detects_dict_style_defer_to_call(self):
        tool_calls = [
            {"name": "defer_to", "arguments": {"target": "billing", "prompt": "help"}},
        ]
        result = self._detect_defer_to_calls(tool_calls)
        assert len(result) == 1
        assert result[0]["name"] == "defer_to"

    def test_detects_defer_to_among_mixed_calls(self):
        tool_calls = [
            {"name": "gmail_search", "arguments": {"query": "hello"}},
            {"name": "defer_to", "arguments": {"target": "billing", "prompt": "help"}},
            {"name": "gmail_send", "arguments": {}},
        ]
        result = self._detect_defer_to_calls(tool_calls)
        assert len(result) == 1
        assert result[0]["name"] == "defer_to"

    def test_ignores_non_defer_to_calls(self):
        tool_calls = [
            {"name": "gmail_search", "arguments": {}},
            {"name": "gmail_send", "arguments": {}},
        ]
        result = self._detect_defer_to_calls(tool_calls)
        assert len(result) == 0

    def test_handles_empty_tool_calls(self):
        result = self._detect_defer_to_calls([])
        assert len(result) == 0

    def test_multiple_defer_to_calls_detected(self):
        tool_calls = [
            {"name": "defer_to", "arguments": {"target": "a", "prompt": "X"}},
            {"name": "defer_to", "arguments": {"target": "b", "prompt": "Y"}},
        ]
        result = self._detect_defer_to_calls(tool_calls)
        assert len(result) == 2

    def test_filter_removes_defer_to_calls(self):
        tool_calls = [
            {"name": "gmail_search", "arguments": {}},
            {"name": "defer_to", "arguments": {"target": "billing", "prompt": "help"}},
            {"name": "gmail_send", "arguments": {}},
        ]
        filtered = self._filter_defer_to_calls(tool_calls)
        assert len(filtered) == 2
        assert all(tc["name"] != "defer_to" for tc in filtered)

    def test_filter_all_defer_to_calls(self):
        tool_calls = [
            {"name": "defer_to", "arguments": {"target": "a", "prompt": "X"}},
            {"name": "defer_to", "arguments": {"target": "b", "prompt": "Y"}},
        ]
        filtered = self._filter_defer_to_calls(tool_calls)
        assert len(filtered) == 0

    def test_json_string_arguments(self):
        """Arguments may arrive as a JSON string rather than a dict."""
        tool_calls = [
            {
                "name": "defer_to",
                "arguments": json.dumps({"target": "billing", "prompt": "help"}),
            },
        ]
        # Detection works with string args
        result = self._detect_defer_to_calls(tool_calls)
        assert len(result) == 1

        # Parsing the JSON string
        args = result[0]["arguments"]
        if isinstance(args, str):
            args = json.loads(args)
        assert args["target"] == "billing"
        assert args["prompt"] == "help"
