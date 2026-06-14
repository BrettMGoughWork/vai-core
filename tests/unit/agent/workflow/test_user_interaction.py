"""
Phase 5.9 — UserInteractionManager Unit Tests
===============================================

Tests for InteractionRequest/Response dataclasses and the
UserInteractionManager — schema validation, timeout enforcement,
pending tracking, and resume integration.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.agent.workflow.engine import StepOutcome, WorkflowExecutionState, WorkflowStatus
from src.agent.workflow.user_interaction import (
    InteractionRequest,
    InteractionResponse,
    UserInteractionManager,
    _make_request_id,
    _serialise,
    _validate_against_schema,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """A WorkflowEngine with all methods stubbed."""
    engine = MagicMock()
    engine.resume_with_input.return_value = (
        MagicMock(spec=WorkflowExecutionState),
        StepOutcome(type="continue"),
    )
    engine.fail_step.return_value = (
        MagicMock(spec=WorkflowExecutionState),
        StepOutcome(type="failed", error="cancelled"),
    )
    return engine


@pytest.fixture
def manager(mock_engine):
    return UserInteractionManager(mock_engine)


@pytest.fixture
def dummy_state():
    return WorkflowExecutionState(
        execution_id="exec-1",
        workflow_id="test-wf",
        status=WorkflowStatus.WAITING_FOR_INPUT,
        current_step_id="ask_user",
        context={},
        step_results={},
    )


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestInteractionRequest:
    def test_default_created_at(self):
        before = time.time()
        req = InteractionRequest(
            request_id="r1", instance_id="i1", step_id="s1",
            prompt="Enter name:", input_schema={},
        )
        after = time.time()
        assert before <= req.created_at <= after
        assert req.expires_at is None

    def test_expires_at_with_timeout(self):
        req = InteractionRequest(
            request_id="r1", instance_id="i1", step_id="s1",
            prompt="Enter name:", input_schema={},
            timeout_seconds=30.0,
        )
        assert req.expires_at is not None
        assert req.expires_at == pytest.approx(req.created_at + 30.0, rel=0.1)


class TestInteractionResponse:
    def test_default_received_at(self):
        before = time.time()
        resp = InteractionResponse(request_id="r1", data={"text": "hello"})
        after = time.time()
        assert before <= resp.received_at <= after


# ---------------------------------------------------------------------------
# UserInteractionManager tests
# ---------------------------------------------------------------------------


class TestRequestInput:
    def test_creates_and_stores_request(self, manager):
        req = manager.request_input(
            instance_id="wf-1",
            step_id="ask_name",
            prompt="What is your name?",
            schema={"type": "object", "properties": {"text": {"type": "string"}}},
        )
        assert req.request_id == _make_request_id("wf-1", "ask_name")
        assert req.instance_id == "wf-1"
        assert req.step_id == "ask_name"
        assert req.prompt == "What is your name?"
        # Should be retrievable
        assert manager.get_request(req.request_id) is req

    def test_request_with_timeout(self, manager):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask_age",
            prompt="Age?", schema={}, timeout_seconds=60.0,
        )
        assert req.timeout_seconds == 60.0
        assert req.expires_at is not None
        assert req.expires_at > time.time()

    def test_multiple_requests(self, manager):
        r1 = manager.request_input("wf-1", "s1", "Q1", {})
        r2 = manager.request_input("wf-1", "s2", "Q2", {})
        r3 = manager.request_input("wf-2", "s1", "Q3", {})
        pending = manager.get_pending()
        assert len(pending) == 3
        assert {r.request_id for r in pending} == {r1.request_id, r2.request_id, r3.request_id}


class TestSubmitResponse:
    def test_valid_submission(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask_name",
            prompt="Name?",
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"text": "Alice"}, dummy_state,
        )
        assert valid is True
        assert error is None
        assert result is not None
        mock_engine.resume_with_input.assert_called_once()

    def test_invalid_type_rejected(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask_age",
            prompt="Age?",
            schema={
                "type": "object",
                "properties": {"age": {"type": "number"}},
                "required": ["age"],
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"age": "not-a-number"}, dummy_state,
        )
        assert valid is False
        assert error is not None
        assert "expected number" in error.lower()
        mock_engine.resume_with_input.assert_not_called()

    def test_missing_required_field_rejected(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask_name",
            prompt="Name?",
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"text": "Alice"}, dummy_state,
        )
        assert valid is False
        assert "missing required" in error.lower()
        mock_engine.resume_with_input.assert_not_called()

    def test_extra_field_rejected(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask_name",
            prompt="Name?",
            schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"name": "Alice", "extra": "unexpected"}, dummy_state,
        )
        assert valid is False
        assert "unexpected" in error.lower()
        mock_engine.resume_with_input.assert_not_called()

    def test_unknown_request_id(self, manager, mock_engine, dummy_state):
        valid, error, result = manager.submit_response(
            "nonexistent", {"text": "hello"}, dummy_state,
        )
        assert valid is False
        assert "unknown" in error.lower()
        mock_engine.resume_with_input.assert_not_called()

    def test_submission_removes_from_pending(self, manager, mock_engine, dummy_state):
        req = manager.request_input("wf-1", "s1", "Q", {"type": "object", "properties": {}})
        assert manager.get_request(req.request_id) is not None
        manager.submit_response(req.request_id, {}, dummy_state)
        assert manager.get_request(req.request_id) is None


class TestEnums:
    def test_enum_validation_passes(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="choose",
            prompt="Pick one:",
            schema={
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": ["a", "b", "c"]},
                },
                "required": ["choice"],
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"choice": "b"}, dummy_state,
        )
        assert valid is True
        mock_engine.resume_with_input.assert_called_once()

    def test_enum_validation_fails(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="choose",
            prompt="Pick one:",
            schema={
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": ["a", "b", "c"]},
                },
                "required": ["choice"],
            },
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"choice": "z"}, dummy_state,
        )
        assert valid is False
        assert "must be one of" in error.lower()
        mock_engine.resume_with_input.assert_not_called()


class TestTimeout:
    def test_expired_request_rejected(self, manager, mock_engine, dummy_state):
        req = manager.request_input(
            instance_id="wf-1", step_id="ask",
            prompt="Quick!",
            schema={"type": "object", "properties": {"x": {"type": "string"}}},
            timeout_seconds=-1.0,  # expired immediately
        )
        valid, error, result = manager.submit_response(
            req.request_id, {"x": "hello"}, dummy_state,
        )
        assert valid is False
        assert "expired" in error.lower()
        mock_engine.resume_with_input.assert_not_called()

    def test_get_pending_excludes_expired(self, manager):
        manager.request_input(
            instance_id="wf-1", step_id="quick",
            prompt="Quick!",
            schema={},
            timeout_seconds=-1.0,
        )
        manager.request_input(
            instance_id="wf-1", step_id="normal",
            prompt="Normal",
            schema={},
            timeout_seconds=3600.0,
        )
        pending = manager.get_pending()
        assert len(pending) == 1
        assert pending[0].step_id == "normal"


class TestCancel:
    def test_cancel_removes_pending_and_fails_step(self, manager, mock_engine, dummy_state):
        req = manager.request_input("wf-1", "s1", "Q", {})
        assert manager.get_request(req.request_id) is not None
        result = manager.cancel_request(req.request_id, dummy_state)
        assert result is True
        assert manager.get_request(req.request_id) is None
        mock_engine.fail_step.assert_called_once()

    def test_cancel_unknown_id(self, manager, dummy_state):
        result = manager.cancel_request("nonexistent", dummy_state)
        assert result is False


class TestGetPending:
    def test_empty_when_no_requests(self, manager):
        assert manager.get_pending() == []

    def test_returns_all_active(self, manager):
        manager.request_input("wf-1", "s1", "Q1", {})
        manager.request_input("wf-2", "s1", "Q2", {})
        assert len(manager.get_pending()) == 2

    def test_len_method(self, manager):
        assert len(manager) == 0
        manager.request_input("wf-1", "s1", "Q", {})
        assert len(manager) == 1


# ---------------------------------------------------------------------------
# Schema validation unit tests
# ---------------------------------------------------------------------------


class TestValidateAgainstSchema:
    def test_none_schema_passes(self):
        assert _validate_against_schema({"x": 1}, {}) is None

    def test_required_field_present(self):
        assert _validate_against_schema(
            {"name": "Alice"},
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ) is None

    def test_required_field_missing(self):
        err = _validate_against_schema(
            {"age": 30},
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        assert err is not None
        assert "name" in err

    def test_type_mismatch(self):
        err = _validate_against_schema(
            {"age": "thirty"},
            {"type": "object", "properties": {"age": {"type": "number"}}, "required": ["age"]},
        )
        assert err is not None
        assert "expected number" in err.lower()

    def test_extra_field(self):
        err = _validate_against_schema(
            {"name": "Alice", "extra": True},
            {"type": "object", "properties": {"name": {"type": "string"}}},
        )
        assert err is not None
        assert "unexpected" in err.lower()

    def test_enum_valid(self):
        assert _validate_against_schema(
            {"color": "red"},
            {
                "type": "object",
                "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
                "required": ["color"],
            },
        ) is None

    def test_enum_invalid(self):
        err = _validate_against_schema(
            {"color": "green"},
            {
                "type": "object",
                "properties": {"color": {"type": "string", "enum": ["red", "blue"]}},
                "required": ["color"],
            },
        )
        assert err is not None
        assert "must be one of" in err.lower()

    def test_boolean_type(self):
        assert _validate_against_schema(
            {"agree": True},
            {"type": "object", "properties": {"agree": {"type": "boolean"}}, "required": ["agree"]},
        ) is None

    def test_boolean_type_mismatch(self):
        err = _validate_against_schema(
            {"agree": "yes"},
            {"type": "object", "properties": {"agree": {"type": "boolean"}}, "required": ["agree"]},
        )
        assert err is not None

    def test_array_type(self):
        assert _validate_against_schema(
            {"items": [1, 2, 3]},
            {
                "type": "object",
                "properties": {"items": {"type": "array", "items": {"type": "number"}}},
            },
        ) is None

    def test_nullable_field(self):
        assert _validate_against_schema(
            {"nickname": None},
            {
                "type": "object",
                "properties": {"nickname": {"type": "string", "nullable": True}},
            },
        ) is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestMakeRequestId:
    def test_deterministic(self):
        id1 = _make_request_id("instance-1", "step-ask")
        id2 = _make_request_id("instance-1", "step-ask")
        assert id1 == id2

    def test_differs_for_different_instances(self):
        id1 = _make_request_id("instance-1", "step-ask")
        id2 = _make_request_id("instance-2", "step-ask")
        assert id1 != id2


class TestSerialise:
    def test_text_field(self):
        assert _serialise({"text": "hello"}) == "hello"

    def test_message_field(self):
        assert _serialise({"message": "hi"}) == "hi"

    def test_multiple_fields_returns_json(self):
        result = _serialise({"name": "Alice", "age": 30})
        assert '"Alice"' in result
        assert '"name"' in result
