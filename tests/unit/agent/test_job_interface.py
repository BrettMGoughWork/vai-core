"""
Phase 5.4 — Agent → Platform Job Interface Unit Tests
======================================================

Tests for ``JobDispatchResult`` and ``dispatch_route()`` (replaces the old
``dispatch_action_intents()`` / ``CognitiveLoopResult`` pipeline).

These tests verify:
- ``JobDispatchResult`` structure and defaults
- ``dispatch_route()`` happy path (S4B dispatch)
- ``dispatch_route()`` no-op for Runtime / S6 destinations
- error handling (no submitter, submitter raises)
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.agent.job_interface import JobDispatchResult, dispatch_route
from src.agent.router import DEST_RUNTIME, DEST_S4B, DEST_S6, Route


# ══════════════════════════════════════════════════════════════════════════════
# JobDispatchResult validation
# ══════════════════════════════════════════════════════════════════════════════


class TestJobDispatchResult:
    """JobDispatchResult is a frozen dataclass with sensible defaults."""

    def test_defaults(self):
        """Fully default-constructed result."""
        result = JobDispatchResult()
        assert result.dispatched_jobs == {}
        assert result.errors == []

    def test_happy_path(self):
        """Result with all fields populated."""
        result = JobDispatchResult(
            dispatched_jobs={"job-1": "s4b"},
            errors=[("s4b", "something went wrong")],
        )
        assert len(result.dispatched_jobs) == 1
        assert result.dispatched_jobs["job-1"] == "s4b"
        assert len(result.errors) == 1
        assert result.errors[0][0] == "s4b"

    def test_is_frozen(self):
        """Cannot mutate fields after construction."""
        result = JobDispatchResult()
        with pytest.raises(AttributeError):
            result.dispatched_jobs = {}  # type: ignore[misc]


# ══════════════════════════════════════════════════════════════════════════════
# dispatch_route — Happy paths
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchRouteHappyPath:
    """dispatch_route() dispatches S4B routes correctly."""

    def test_s4b_with_submitter_dispatches_job(self):
        """S4B route with a submitter → job submitted → in dispatched_jobs."""
        route = Route(
            destination=DEST_S4B,
            payload={"action": "direct_execution", "message": "run this"},
            agent_id="test-agent",
            confidence=0.7,
        )
        submitter = mock.Mock(return_value="job-123")
        result = dispatch_route(route, submit_job_callable=submitter)

        assert len(result.dispatched_jobs) == 1
        assert "job-123" in result.dispatched_jobs
        assert result.dispatched_jobs["job-123"] == DEST_S4B
        assert result.errors == []
        submitter.assert_called_once_with(route.payload)

    def test_runtime_route_is_noop(self):
        """DEST_RUNTIME → no dispatch, no errors."""
        route = Route(
            destination=DEST_RUNTIME,
            payload={"message": "hello"},
            agent_id="test-agent",
        )
        result = dispatch_route(route, submit_job_callable=mock.Mock())

        assert result.dispatched_jobs == {}
        assert result.errors == []

    def test_s6_route_is_noop(self):
        """DEST_S6 → no dispatch, no errors."""
        route = Route(
            destination=DEST_S6,
            payload={"message": "start workflow", "trigger": "workflow_request"},
            agent_id="test-agent",
            confidence=0.8,
        )
        result = dispatch_route(route, submit_job_callable=mock.Mock())

        assert result.dispatched_jobs == {}
        assert result.errors == []


# ══════════════════════════════════════════════════════════════════════════════
# dispatch_route — Error & edge-case paths
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatchRouteErrors:
    """dispatch_route() handles errors gracefully."""

    def test_s4b_without_submitter_errors(self):
        """S4B route without a submitter → error recorded."""
        route = Route(
            destination=DEST_S4B,
            payload={"message": "run this"},
            agent_id="test-agent",
            confidence=0.7,
        )
        result = dispatch_route(route, submit_job_callable=None)

        assert result.dispatched_jobs == {}
        assert len(result.errors) == 1
        assert result.errors[0][0] == "s4b"
        assert "No submit_job_callable provided" in result.errors[0][1]

    def test_submitter_raises_error(self):
        """Submitter exception → error recorded."""
        route = Route(
            destination=DEST_S4B,
            payload={"message": "run this"},
            agent_id="test-agent",
            confidence=0.7,
        )

        def _failing_submitter(_: dict) -> str:
            raise RuntimeError("Queue full")

        result = dispatch_route(route, submit_job_callable=_failing_submitter)

        assert result.dispatched_jobs == {}
        assert len(result.errors) == 1
        assert result.errors[0][0] == DEST_S4B
        assert "Queue full" in result.errors[0][1]
