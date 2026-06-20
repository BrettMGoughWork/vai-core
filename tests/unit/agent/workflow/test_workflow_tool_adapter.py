"""
Phase 5.8 — Workflow Tool Adapter Unit Tests
==============================================

Tests for WorkflowToolAdapter — converts registered WorkflowDefinitions
into LLM-callable tool definitions and resolves tool calls back to
workflow invocations.

Covers:
- s9a.5: Agent invokes workflow via tool call
- s9a.6: Workflow tool call with params → correctly populates initial state
- s9a.7: Agent calls non-existent workflow → graceful error (tool not found)
- s9a.8: Workflow tool appears/disappears based on registration state
"""

from __future__ import annotations

import pytest

from src.agent.workflow.registry import WorkflowRegistry
from src.agent.workflow.workflow_definition import (
    END_TARGET,
    WorkflowDefinition,
    WorkflowStep,
)
from src.agent.workflow.workflow_tool_adapter import (
    WORKFLOW_TOOL_PREFIX,
    WorkflowToolAdapter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str,
    step_type: str = "llm_call",
    *,
    label: str = "",
    config: dict | None = None,
    transitions: dict | None = None,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        step_type=step_type,
        label=label or f"Step {step_id}",
        config=config or {},
        transitions=transitions or {"on_success": END_TARGET},
    )


def _make_workflow(
    workflow_id: str = "test-wf",
    steps: dict[str, WorkflowStep] | None = None,
    start_step: str = "step_1",
    input_schema: dict | None = None,
) -> WorkflowDefinition:
    if steps is None:
        steps = {
            "step_1": _make_step("step_1", transitions={"on_success": END_TARGET}),
        }
    kwargs: dict = dict(
        workflow_id=workflow_id,
        name=workflow_id,
        description="Test workflow",
        steps=steps,
        start_step=start_step,
    )
    if input_schema is not None:
        kwargs["input_schema"] = input_schema
    return WorkflowDefinition(**kwargs)


def _make_registry(*defns: WorkflowDefinition) -> WorkflowRegistry:
    reg = WorkflowRegistry()
    for d in defns:
        reg.register(d)
    return reg


# ===================================================================
# s9a.5 — Agent invokes workflow via tool call
# ===================================================================


class TestInvokeViaToolCall:
    """The adapter should convert registered workflows into LLM tool
    definitions, and resolve tool calls back to runnable workflows."""

    def test_list_tools_returns_tool_definitions(self):
        """list_tools() should return a list of tool dicts with
        name, description, and input_schema."""
        wf = _make_workflow("demo-chat")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        assert len(tools) == 1
        tool = tools[0]

        assert tool["name"] == f"{WORKFLOW_TOOL_PREFIX}.demo-chat"
        assert tool["description"] == "Test workflow"
        assert "input_schema" in tool

    def test_resolve_tool_call_returns_workflow_and_params(self):
        """resolve_tool_call() should return a (WorkflowDefinition, params)
        tuple for a known workflow tool name."""
        wf = _make_workflow("demo-chat")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.demo-chat",
            {},
        )
        assert result is not None
        defn, params = result
        assert defn.workflow_id == "demo-chat"
        assert params == {}

    def test_multiple_workflows_all_appear_in_tools(self):
        """All registered workflows should appear as tools."""
        wf1 = _make_workflow("wf-one")
        wf2 = _make_workflow("wf-two")
        registry = _make_registry(wf1, wf2)
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert f"{WORKFLOW_TOOL_PREFIX}.wf-one" in tool_names
        assert f"{WORKFLOW_TOOL_PREFIX}.wf-two" in tool_names

    def test_excluded_workflows_are_omitted_from_tools(self):
        """Workflows in the exclude_ids set should not appear in tools."""
        wf1 = _make_workflow("internal-wf")
        wf2 = _make_workflow("public-wf")
        registry = _make_registry(wf1, wf2)
        adapter = WorkflowToolAdapter(registry, exclude_ids={"internal-wf"})

        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert f"{WORKFLOW_TOOL_PREFIX}.internal-wf" not in tool_names
        assert f"{WORKFLOW_TOOL_PREFIX}.public-wf" in tool_names


# ===================================================================
# s9a.6 — Workflow tool call with params
# ===================================================================


class TestParamsPassthrough:
    """When resolved, tool call arguments should populate the workflow
    initial context (params dict)."""

    def test_params_passed_through_to_context(self):
        """Tool call arguments should appear in the returned params dict."""
        wf = _make_workflow("demo-chat")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.demo-chat",
            {"input": "Hello, workflow!"},
        )
        assert result is not None
        defn, params = result
        assert params == {"input": "Hello, workflow!"}

    def test_empty_params_returns_empty_dict(self):
        """Calling resolve_tool_call with empty arguments should return
        an empty params dict."""
        wf = _make_workflow("demo-chat")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.demo-chat",
            {},
        )
        assert result is not None
        _, params = result
        assert params == {}

    def test_multiple_params_passed_correctly(self):
        """Multiple tool call arguments should all appear in params."""
        wf = _make_workflow("multi-param-wf")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.multi-param-wf",
            {"input": "data", "max_results": 5, "filter": "unread"},
        )
        assert result is not None
        _, params = result
        assert params == {"input": "data", "max_results": 5, "filter": "unread"}


# ===================================================================
# s9a.7 — Non-existent workflow → graceful error
# ===================================================================


class TestNonExistentWorkflow:
    """When a tool call references an unknown workflow ID, the adapter
    should return None (graceful non-match)."""

    def test_unknown_workflow_returns_none(self):
        """resolve_tool_call for an unregistered workflow should return None."""
        wf = _make_workflow("registered-wf")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.unknown-wf",
            {},
        )
        assert result is None

    def test_tool_name_without_prefix_returns_none(self):
        """A tool name without the workflow.execute. prefix should not
        be matched and should return None."""
        wf = _make_workflow("demo-chat")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            "some-other-tool",
            {},
        )
        assert result is None

    def test_empty_registry_returns_no_tools(self):
        """With no workflows registered, list_tools should return an
        empty list."""
        registry = _make_registry()  # Empty
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        assert tools == []

    def test_empty_registry_resolve_returns_none(self):
        """With no workflows registered, any resolve should return None."""
        registry = _make_registry()
        adapter = WorkflowToolAdapter(registry)

        result = adapter.resolve_tool_call(
            f"{WORKFLOW_TOOL_PREFIX}.anything",
            {},
        )
        assert result is None


# ===================================================================
# s9a.8 — Workflow tool appears/disappears based on registration
# ===================================================================


class TestRegistrationLifecycle:
    """The tool list should reflect the current registration state —
    tools appear when workflows are registered and disappear when
    omitted or excluded."""

    def test_tool_appears_after_registration(self):
        """A workflow registered in the registry should appear as a tool."""
        wf = _make_workflow("new-wf")
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert f"{WORKFLOW_TOOL_PREFIX}.new-wf" in tool_names

    def test_no_tools_before_any_registration(self):
        """With an empty registry, no tools should be listed."""
        registry = _make_registry()
        adapter = WorkflowToolAdapter(registry)

        assert adapter.list_tools() == []

    def test_excluded_tool_disappears(self):
        """A workflow excluded via exclude_ids should not appear, but
        other workflows should still be listed."""
        wf1 = _make_workflow("internal")
        wf2 = _make_workflow("external")
        registry = _make_registry(wf1, wf2)
        adapter = WorkflowToolAdapter(registry, exclude_ids={"internal"})

        tools = adapter.list_tools()
        tool_names = {t["name"] for t in tools}
        assert f"{WORKFLOW_TOOL_PREFIX}.internal" not in tool_names
        assert f"{WORKFLOW_TOOL_PREFIX}.external" in tool_names

    def test_input_schema_from_workflow_definition(self):
        """When a workflow defines an input_schema, it should be used
        as the tool's input_schema."""
        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "maxResults": {"type": "integer"},
            },
            "required": ["query"],
        }
        wf = _make_workflow("schema-wf", input_schema=schema)
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        tool = tools[0]
        assert tool["input_schema"] == schema

    def test_fallback_input_schema_when_not_defined(self):
        """When a workflow does not define an input_schema, a sensible
        default (object with string input) should be provided."""
        wf = _make_workflow("no-schema-wf", input_schema=None)
        registry = _make_registry(wf)
        adapter = WorkflowToolAdapter(registry)

        tools = adapter.list_tools()
        tool = tools[0]
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "input" in schema.get("properties", {})
