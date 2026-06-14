"""
Phase 5.2 — Agent Router Unit Tests
====================================

Tests for the deterministic pattern-matching message router.

Covers:
- Route dataclass construction and validation
- route_message routing decisions (DEST_RUNTIME, DEST_S6, DEST_S4B)
- Keyword matching and case insensitivity
- Capability-gated execution routing
- Edge cases (empty messages, unknown agents)
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from src.agent.router import (
    DEST_RUNTIME,
    DEST_S4B,
    DEST_S6,
    Route,
    route_message,
)
from src.agent.registry import (
    CAP_JOB_SUBMISSION,
    CAP_CONVERSATIONAL,
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_agent() -> AgentMetadata:
    """An agent with only conversational capability."""
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id="test-agent",
            name="Test Agent",
        ),
        capabilities=[CAP_CONVERSATIONAL],
    )


@pytest.fixture
def job_capable_agent() -> AgentMetadata:
    """An agent with job_submission capability."""
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id="job-agent",
            name="Job Agent",
        ),
        capabilities=[CAP_JOB_SUBMISSION],
    )


@pytest.fixture
def full_capability_agent() -> AgentMetadata:
    """An agent with all capabilities declared."""
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id="full-agent",
            name="Full Agent",
        ),
        capabilities=[CAP_CONVERSATIONAL, CAP_JOB_SUBMISSION],
    )


# ---------------------------------------------------------------------------
# Route — dataclass construction and validation
# ---------------------------------------------------------------------------


class TestRouteConstruction:
    """Route is a frozen dataclass with post-init validation."""

    def test_valid_destinations(self) -> None:
        for dest in (DEST_RUNTIME, DEST_S6, DEST_S4B):
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
            r.destination = DEST_S4B  # type: ignore[misc]


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
    """Workflow keywords route to DEST_S6 irrespective of capabilities."""

    @pytest.mark.parametrize(
        "msg",
        [
            "run workflow",
            "start workflow",
            "workflow",
            "trigger workflow",
            "execute workflow",
            "please run workflow X",
            "RUN WORKFLOW",
            "Run Workflow",
        ],
    )
    def test_workflow_keywords(
        self, msg: str, default_agent: AgentMetadata
    ) -> None:
        route = route_message(msg, default_agent)
        assert route.destination == DEST_S6
        assert route.confidence == 0.8
        assert route.payload.get("trigger") == "workflow_request"

    def test_workflow_keyword_embedded(
        self, default_agent: AgentMetadata
    ) -> None:
        """Keyword can appear anywhere in the message."""
        route = route_message("I need to start workflow daily-report", default_agent)
        assert route.destination == DEST_S6

    def test_s6_carries_agent_id(self, default_agent: AgentMetadata) -> None:
        route = route_message("run workflow", default_agent)
        assert route.agent_id == "test-agent"
        assert route.payload.get("message") == "run workflow"


class TestRouteMessageS4B:
    """Execution keywords route to DEST_S4B only when capability is present."""

    @pytest.mark.parametrize(
        "msg",
        [
            "execute task",
            "run deployment",
            "do something",
        ],
    )
    def test_execution_keyword_with_capability(
        self, msg: str, job_capable_agent: AgentMetadata
    ) -> None:
        route = route_message(msg, job_capable_agent)
        assert route.destination == DEST_S4B
        assert route.confidence == 0.7
        assert route.payload.get("action") == "direct_execution"

    def test_execution_keyword_no_capability(
        self, default_agent: AgentMetadata
    ) -> None:
        """Without CAP_JOB_SUBMISSION, execution keywords → Runtime."""
        route = route_message("execute task", default_agent)
        assert route.destination == DEST_RUNTIME
        assert route.confidence == 1.0

    def test_full_capability_agent_uses_execution(
        self, full_capability_agent: AgentMetadata
    ) -> None:
        """An agent with multiple caps still routes to S4B when appropriate."""
        route = route_message("run backup", full_capability_agent)
        assert route.destination == DEST_S4B

    def test_workflow_keyword_takes_precedence(
        self, job_capable_agent: AgentMetadata
    ) -> None:
        """Workflow keywords are checked first and take priority."""
        route = route_message("run workflow", job_capable_agent)
        assert route.destination == DEST_S6  # not S4B

    def test_s4b_carries_agent_id(
        self, job_capable_agent: AgentMetadata
    ) -> None:
        route = route_message("run task", job_capable_agent)
        assert route.agent_id == "job-agent"
        assert route.payload.get("message") == "run task"


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
            capabilities=[CAP_CONVERSATIONAL],
            inputs=["text"],
            outputs=["text"],
            constraints=AgentConstraints(max_tokens=500),
        )
        route = route_message("hello", agent)
        assert route.destination == DEST_RUNTIME

    def test_case_insensitivity(self, job_capable_agent: AgentMetadata) -> None:
        """All routing checks are case-insensitive."""
        route = route_message("EXECUTE DEPLOY", job_capable_agent)
        assert route.destination == DEST_S4B

    def test_partial_word_match_avoided(
        self, job_capable_agent: AgentMetadata
    ) -> None:
        """Partial words don't trigger execution routing (keywords have trailing space)."""
        route = route_message("running_script", job_capable_agent)
        # "running_script" doesn't contain "run " (with space) so no match
        assert route.destination == DEST_RUNTIME

    def test_execution_keyword_spaces(
        self, job_capable_agent: AgentMetadata
    ) -> None:
        """'run ' with trailing space triggers execution route."""
        route = route_message("run something", job_capable_agent)
        assert route.destination == DEST_S4B
