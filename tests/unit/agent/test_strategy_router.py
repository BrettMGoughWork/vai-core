"""Tests for R.5 — StrategyRouter."""

from __future__ import annotations

from typing import Any

import pytest

from src.agent.strategy_router import RouterOutcome, StrategyRouter
from src.runtime.interfaces import PromptResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_call_runtime() -> callable:
    """Return a callable that simulates a successful runtime response."""
    def _fake(request: Any, *, backend: str = "conversational") -> Any:
        return PromptResponse(
            output={"message": f"Hello from {backend}!"},
            tool_calls=[],
        )
    return _fake


@pytest.fixture
def failing_call_runtime() -> callable:
    """Return a callable that simulates an S1Error (LLM unavailable)."""
    def _fake(request: Any, *, backend: str = "conversational") -> Any:
        if backend == "mock":
            return PromptResponse(
                output={"message": "Mock fallback response."},
                tool_calls=[],
            )
        from src.runtime.interfaces import S1Error
        return S1Error(type="llm_transport_unavailable", message="LLM transport unavailable")
    return _fake


@pytest.fixture
def double_failing_call_runtime() -> callable:
    """Return a callable that fails both conversational and mock."""
    def _fake(request: Any, *, backend: str = "conversational") -> Any:
        from src.runtime.interfaces import S1Error
        return S1Error(type="llm_transport_unavailable", message=f"{backend} also unavailable")
    return _fake


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyRouter:
    """StrategyRouter route dispatch."""

    def test_route_llm_success(self, mock_call_runtime: callable) -> None:
        router = StrategyRouter(call_runtime=mock_call_runtime)
        outcome = RouterOutcome(
            type="llm_call",
            payload={"prompt": {"message": "hi"}, "backend": "conversational"},
        )
        result = router.route(outcome)
        assert result["error"] is None
        assert result["output"]["message"] == "Hello from conversational!"

    def test_route_llm_with_mock_fallback(self, failing_call_runtime: callable) -> None:
        router = StrategyRouter(call_runtime=failing_call_runtime)
        outcome = RouterOutcome(
            type="llm_call",
            payload={"prompt": {"message": "hi"}, "backend": "conversational"},
        )
        result = router.route(outcome)
        assert result["error"] is None
        assert result["runtime_fallback"] is True
        assert result["output"]["message"] == "Mock fallback response."
        assert "unavailable" in result["runtime_error"]

    def test_route_llm_both_fail(self, double_failing_call_runtime: callable) -> None:
        router = StrategyRouter(call_runtime=double_failing_call_runtime)
        outcome = RouterOutcome(
            type="llm_call",
            payload={"prompt": {"message": "hi"}, "backend": "conversational"},
        )
        result = router.route(outcome)
        assert result["error"] is not None
        assert result.get("runtime_error") is True

    def test_route_unknown_type(self, mock_call_runtime: callable) -> None:
        router = StrategyRouter(call_runtime=mock_call_runtime)
        outcome = RouterOutcome(type="unknown_type", payload={})
        with pytest.raises(ValueError, match="Unknown route type"):
            router.route(outcome)

    def test_route_planner_raises_not_implemented(self) -> None:
        router = StrategyRouter()
        outcome = RouterOutcome(type="planner_call", payload={"goal": "test"})
        with pytest.raises(NotImplementedError):
            router.route(outcome)

    def test_route_tool_raises_not_implemented(self) -> None:
        router = StrategyRouter()
        outcome = RouterOutcome(type="tool_call", payload={"skill_name": "test"})
        with pytest.raises(NotImplementedError):
            router.route(outcome)

    def test_default_call_runtime_provided(self) -> None:
        """Default StrategyRouter should have a callable for _call_runtime."""
        router = StrategyRouter()
        assert callable(router._call_runtime)


class TestRouterOutcome:
    """RouterOutcome dataclass."""

    def test_defaults(self) -> None:
        outcome = RouterOutcome()
        assert outcome.type == ""
        assert outcome.payload == {}
        assert outcome.step_id == ""

    def test_frozen(self) -> None:
        outcome = RouterOutcome(type="llm_call")
        with pytest.raises(AttributeError):
            outcome.type = "tool_call"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = RouterOutcome(type="llm_call", payload={"key": "val"})
        b = RouterOutcome(type="llm_call", payload={"key": "val"})
        assert a == b


class TestStrategyRouterWithEdgeCases:
    """Edge cases for StrategyRouter."""

    def test_empty_payload(self, mock_call_runtime: callable) -> None:
        router = StrategyRouter(call_runtime=mock_call_runtime)
        outcome = RouterOutcome(type="llm_call", payload={})
        result = router.route(outcome)
        assert result["error"] is None

    def test_missing_message_in_output(self) -> None:
        """When output has no 'message' key, default to 'I'm not sure...'."""
        def _fake(request: Any, *, backend: str = "conversational") -> Any:
            return PromptResponse(output={}, tool_calls=[])

        router = StrategyRouter(call_runtime=_fake)
        outcome = RouterOutcome(
            type="llm_call",
            payload={"prompt": {"message": "hi"}, "backend": "conversational"},
        )
        result = router.route(outcome)
        assert result["error"] is None
        # output is empty dict — caller handles fallback text

    def test_planner_configured_raises_on_missing_s4(self) -> None:
        """Even with planner configured, missing submit_s4_job raises."""
        router = StrategyRouter(
            planner=lambda **kw: type("Plan", (), {"steps": [], "plan_id": "p1"})(),
            capability_discoverer=lambda: [],
        )
        outcome = RouterOutcome(type="planner_call", payload={"goal": "test"})
        with pytest.raises(NotImplementedError, match="submit_s4_job"):
            router.route(outcome)
