"""
Phase 5.2 — Agent Router Unit Tests
====================================

Tests for the deterministic pattern-matching message router.

Covers:
- Route dataclass construction and validation
- route_message routing decisions (DEST_RUNTIME, DEST_WORKFLOW)
- Keyword matching and case insensitivity
- Edge cases (empty messages, metadata-only checks)
"""

from __future__ import annotations

import pytest

from src.agent.router import (
    DEST_RUNTIME,
    DEST_WORKFLOW,
    Route,
    route_message,
)
from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_agent() -> AgentMetadata:
    """A basic agent with no special skills or workflows."""
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id="test-agent",
            name="Test Agent",
        ),
    )


@pytest.fixture
def workflow_capable_agent() -> AgentMetadata:
    """An agent with a declared workflow."""
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id="wf-agent",
            name="Workflow Agent",
        ),
        workflows=["data-pipeline"],
    )


# ---------------------------------------------------------------------------
# Route — dataclass construction and validation
# ---------------------------------------------------------------------------


class TestRouteConstruction:
    """Route is a frozen dataclass with post-init validation."""

    def test_valid_destinations(self) -> None:
        for dest in (DEST_RUNTIME, DEST_WORKFLOW):
            r = Route(destination=dest, agent_id="a1")
            assert r.destination == dest
            assert r.payload == {}
            assert r.agent_id == "a1"
            assert r.confidence == 1.0

    def test_with_payload(self) -> None:
        r = Route(
            destination=DEST_RUNTIME,
            payload={"message": "hello"},
            agent_id="a1",
            confidence=0.9,
        )
        assert r.payload == {"message": "hello"}
        assert r.confidence == 0.9

    def test_invalid_destination_raises(self) -> None:
        with pytest.raises(ValueError, match="destination"):
            Route(destination="mars", agent_id="a1")

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ValueError, match="payload"):
            Route(destination=DEST_RUNTIME, payload="not a dict", agent_id="a1")  # type: ignore[arg-type]

    def test_non_numeric_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Route(destination=DEST_RUNTIME, agent_id="a1", confidence="high")  # type: ignore[arg-type]

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Route(destination=DEST_RUNTIME, agent_id="a1", confidence=-0.1)

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            Route(destination=DEST_RUNTIME, agent_id="a1", confidence=1.1)

    def test_boundary_confidence_values(self) -> None:
        """0.0 and 1.0 are the inclusive boundaries."""
        r0 = Route(destination=DEST_RUNTIME, agent_id="a1", confidence=0.0)
        assert r0.confidence == 0.0
        r1 = Route(destination=DEST_RUNTIME, agent_id="a1", confidence=1.0)
        assert r1.confidence == 1.0

    def test_is_frozen(self) -> None:
        r = Route(destination=DEST_RUNTIME, agent_id="a1")
        with pytest.raises(AttributeError):
            r.destination = DEST_WORKFLOW  # type: ignore[misc]


# ---------------------------------------------------------------------------
# route_message — routing decisions
# ---------------------------------------------------------------------------


class TestRouteMessageDefaults:
    """Messages with no special keywords route to DEST_RUNTIME."""

    def test_runtime_is_default(self, default_agent: AgentMetadata) -> None:
        route = route_message("hello", default_agent)
        assert route.destination == DEST_RUNTIME
        assert route.confidence == 1.0

    def test_agent_id_carried(self, default_agent: AgentMetadata) -> None:
        route = route_message("hello", default_agent)
        assert route.agent_id == "test-agent"

    def test_payload_contains_message(self, default_agent: AgentMetadata) -> None:
        route = route_message("hello world", default_agent)
        assert route.payload.get("message") == "hello world"

    def test_empty_message(self, default_agent: AgentMetadata) -> None:
        """Empty or whitespace-only should still route to Runtime."""
        route = route_message("", default_agent)
        assert route.destination == DEST_RUNTIME

    def test_whitespace_only_message(self, default_agent: AgentMetadata) -> None:
        route = route_message("   ", default_agent)
        assert route.destination == DEST_RUNTIME

    def test_symbols_and_gibberish(self, default_agent: AgentMetadata) -> None:
        """Non-keyword messages fall through to Runtime."""
        route = route_message("@#$%^&*()", default_agent)
        assert route.destination == DEST_RUNTIME


class TestRouteMessageS6:
    """Messages starting with /workflow route to DEST_WORKFLOW."""

    @pytest.mark.parametrize(
        "msg,expected_wf_id",
        [
            ("/workflow", ""),
            ("/workflow default-agent", "default-agent"),
            ("/workflow tools-workflow", "tools-workflow"),
            ("/workflow waiting-agent hello", "waiting-agent"),
            ("/WORKFLOW default-agent", "default-agent"),
            ("/Workflow default-agent", "default-agent"),
        ],
    )
    def test_workflow_prefix(
        self, msg: str, expected_wf_id: str, default_agent: AgentMetadata
    ) -> None:
        route = route_message(msg, default_agent)
        assert route.destination == DEST_WORKFLOW
        assert route.confidence == 0.9
        assert route.payload.get("trigger") == "workflow_request"
        assert route.payload.get("workflow_id") == expected_wf_id

    def test_workflow_prefix_no_match(self, default_agent: AgentMetadata) -> None:
        """Plain 'workflow' (no leading slash) should NOT trigger workflow."""
        route = route_message("run the workflow", default_agent)
        assert route.destination == DEST_RUNTIME

    def test_s6_carries_agent_id(self, default_agent: AgentMetadata) -> None:
        route = route_message("/workflow", default_agent)
        assert route.agent_id == "test-agent"
        assert route.payload.get("message") == "/workflow"


class TestRouteMessageEdgeCases:
    """Edge cases and boundary conditions."""

    def test_context_param_is_accepted(
        self, default_agent: AgentMetadata
    ) -> None:
        """context parameter is reserved for future use; passing it should not crash."""
        route = route_message("hello", default_agent, context={"foo": "bar"})
        assert route.destination == DEST_RUNTIME

    def test_context_defaults_to_empty(
        self, default_agent: AgentMetadata
    ) -> None:
        """Omitting context is equivalent to passing an empty dict."""
        route_with = route_message("hello", default_agent, context={})
        route_without = route_message("hello", default_agent)
        assert route_with == route_without

    def test_unknown_metadata_fields_irrelevant(
        self, default_agent: AgentMetadata
    ) -> None:
        """Extra metadata doesn't affect routing."""
        agent = AgentMetadata(
            identity=AgentIdentity(
                agent_id="whatever", name="Whatever", version="2.0.0"
            ),
            skills=["web_search"],
            inputs=["text"],
            outputs=["text"],
            constraints=AgentConstraints(max_tokens=500),
        )
        route = route_message("hello", agent)
        assert route.destination == DEST_RUNTIME
