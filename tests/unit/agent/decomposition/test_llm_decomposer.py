"""Tests for LLMDecomposer.

Covers:
- decompose() returns a valid DecompositionPlan given valid LLM output
- decompose() returns None when LLM indicates task is atomic (no subtasks)
- decompose() returns None when LLM returns unparseable output
- decompose() returns None when DAG validation fails (cycles)
- decompose() filters out unavailable target agents
- decompose() defaults merge_strategy to "concat" for unknown values
- decompose() preserves original task and available_agents
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.decomposition.llm_decomposer import LLMDecomposer
from src.agent.types.decomposition import DecompositionPlan, DecompositionRequest


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _mock_router(output: dict) -> MagicMock:
    """Create a StrategyRouter mock that returns *output* on route()."""
    router = MagicMock()
    router.route.return_value = {"output": output, "error": None}
    return router


def _request(
    task: str = "Build a login system",
    agents: list[str] | None = None,
    constraints: dict | None = None,
) -> DecompositionRequest:
    return DecompositionRequest(
        parent_task=task,
        parent_context={},
        available_agents=agents or ["research", "code"],
        constraints=constraints or {},
    )


_VALID_SUBTASKS = [
    {
        "id": "subtask-1",
        "description": "Design the login UI",
        "target_agent_id": "code",
        "depends_on": [],
        "priority": 0,
        "timeout_seconds": 300,
    },
    {
        "id": "subtask-2",
        "description": "Implement login API endpoint",
        "target_agent_id": "code",
        "depends_on": ["subtask-1"],
        "priority": 0,
        "timeout_seconds": 300,
    },
]

_VALID_LLM_OUTPUT = {
    "message": (
        '{"subtasks": ['
        '{"id": "subtask-1", "description": "Design the login UI", '
        '"target_agent_id": "code", "depends_on": [], "priority": 0, '
        '"timeout_seconds": 300}, '
        '{"id": "subtask-2", "description": "Implement login API endpoint", '
        '"target_agent_id": "code", "depends_on": ["subtask-1"], '
        '"priority": 0, "timeout_seconds": 300}], '
        '"merge_strategy": "concat", "reasoning": "UI first, then API"}'
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# decompose — success cases
# ══════════════════════════════════════════════════════════════════════════════


class TestDecomposeSuccess:
    def test_returns_valid_plan(self) -> None:
        router = _mock_router(_VALID_LLM_OUTPUT)
        decomposer = LLMDecomposer(router)
        request = _request()

        plan = decomposer.decompose(request)

        assert plan is not None
        assert isinstance(plan, DecompositionPlan)
        assert plan.parent_task == "Build a login system"
        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].id == "subtask-1"
        assert plan.subtasks[1].id == "subtask-2"
        assert plan.subtasks[1].depends_on == ["subtask-1"]
        assert plan.merge_strategy == "concat"
        assert plan.metadata["source"] == "llm_decomposer"

    def test_plan_id_is_unique(self) -> None:
        router = _mock_router(_VALID_LLM_OUTPUT)
        decomposer = LLMDecomposer(router)

        plan_a = decomposer.decompose(_request())
        plan_b = decomposer.decompose(_request())

        assert plan_a is not None and plan_b is not None
        assert plan_a.plan_id != plan_b.plan_id

    def test_includes_available_agents_in_prompt(self) -> None:
        router = MagicMock()
        router.route.return_value = {"output": _VALID_LLM_OUTPUT, "error": None}
        decomposer = LLMDecomposer(router)
        request = _request(agents=["research", "code", "qa"])

        decomposer.decompose(request)

        # The prompt should include the available agents
        prompt = router.route.call_args[0][0].payload["prompt"]
        message = prompt.get("message", "")
        assert "research" in message
        assert "qa" in message

    def test_passes_constraints_to_prompt(self) -> None:
        router = MagicMock()
        router.route.return_value = {"output": _VALID_LLM_OUTPUT, "error": None}
        decomposer = LLMDecomposer(router)
        request = _request(constraints={"max_children": 5, "max_depth": 3})

        decomposer.decompose(request)

        prompt = router.route.call_args[0][0].payload["prompt"]
        message = prompt.get("message", "")
        assert "at most 5" in message or "max depth 3" in message

    def test_parses_markdown_code_fences(self) -> None:
        """LLM sometimes wraps JSON in ```json ... ``` fences."""
        raw_json = (
            '{"subtasks": [{"id": "subtask-1", "description": "Design UI",'
            '"depends_on": []}, {"id": "subtask-2", "description": "Implement API",'
            '"depends_on": ["subtask-1"]}], "merge_strategy": "concat"}'
        )
        wrapped = {"message": f"```json\n{raw_json}\n```"}
        router = _mock_router(wrapped)
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert len(plan.subtasks) == 2

    def test_handles_plain_string_output(self) -> None:
        """When output is a plain string message, parse it directly."""
        raw_json = (
            '{"subtasks": [{"id": "s1", "description": "do it",'
            '"depends_on": []}], "merge_strategy": "concat"}'
        )
        router = _mock_router({"message": raw_json})
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert len(plan.subtasks) == 1


# ══════════════════════════════════════════════════════════════════════════════
# decompose — edge cases & error handling
# ══════════════════════════════════════════════════════════════════════════════


class TestDecomposeEdgeCases:
    def test_returns_none_when_llm_indicates_atomic(self) -> None:
        """LLM returns a valid JSON but with no subtasks."""
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": [], "merge_strategy": "concat", '
                    '"reasoning": "Task is atomic."}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is None

    def test_returns_none_on_unparseable_output(self) -> None:
        router = _mock_router({"message": "I think this task is simple enough."})
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is None

    def test_returns_none_on_empty_output(self) -> None:
        router = _mock_router({"message": ""})
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is None

    def test_returns_none_when_router_returns_error(self) -> None:
        router = MagicMock()
        router.route.return_value = {"error": "LLM unavailable", "output": {}}
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is None

    def test_filters_unavailable_agent(self) -> None:
        """LLM requests 'qa' but it's not in available_agents."""
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"id": "s1", "description": "Run tests", '
                    '"target_agent_id": "qa", "depends_on": []}], '
                    '"merge_strategy": "concat"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)
        request = _request(agents=["research", "code"])

        plan = decomposer.decompose(request)
        assert plan is not None
        # qa is not available, so target_agent_id should be None
        assert plan.subtasks[0].target_agent_id is None

    def test_defaults_unknown_merge_strategy_to_concat(self) -> None:
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"id": "s1", "description": "Step 1", "depends_on": []}], '
                    '"merge_strategy": "invalid_merge"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert plan.merge_strategy == "concat"

    def test_cyclic_dag_returns_none(self) -> None:
        """LLM returns subtasks with a cycle — DAG validation fails."""
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"id": "a", "description": "A", "depends_on": ["b"]}, '
                    '{"id": "b", "description": "B", "depends_on": ["a"]}], '
                    '"merge_strategy": "concat"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is None

    def test_missing_subtask_id_falls_back_to_index(self) -> None:
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"description": "No id field", "depends_on": []}], '
                    '"merge_strategy": "concat"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert plan.subtasks[0].id == "subtask-1"

    def test_missing_description_falls_back(self) -> None:
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"id": "s1", "depends_on": []}], '
                    '"merge_strategy": "concat"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert plan.subtasks[0].description == "Subtask s1"


# ══════════════════════════════════════════════════════════════════════════════
# decompose — integration with real objects
# ══════════════════════════════════════════════════════════════════════════════


class TestDecomposeIntegration:
    def test_subtask_defaults(self) -> None:
        """Verify default values for optional fields."""
        router = _mock_router(
            {
                "message": (
                    '{"subtasks": ['
                    '{"id": "s1", "description": "Step 1", "depends_on": []}], '
                    '"merge_strategy": "concat"}'
                ),
            }
        )
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        sub = plan.subtasks[0]
        assert sub.target_agent_id is None
        assert sub.target_skill_id is None
        assert sub.arguments == {}
        assert sub.priority == 0
        assert sub.timeout_seconds == 300
        assert sub.max_retries == 2

    def test_plan_has_metadata(self) -> None:
        router = _mock_router(_VALID_LLM_OUTPUT)
        decomposer = LLMDecomposer(router)

        plan = decomposer.decompose(_request())
        assert plan is not None
        assert plan.metadata["reasoning"] == "UI first, then API"
        assert plan.metadata["source"] == "llm_decomposer"
