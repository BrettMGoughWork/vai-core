"""Tests for S3Adapter (Phase 3.8.5)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.capabilities.contracts import (
    DiscoveredSkill,
    SkillCallRequest,
    SkillDiscoveryQuery,
    SkillDiscoveryResult,
    SkillResult,
)
from src.stratum2.s3_adapter import (
    S2DiscoveredSkill,
    S2DiscoveryQuery,
    S2DiscoveryResult,
    S2SkillCallRequest,
    S2SkillResult,
    S3Adapter,
)


# ── helpers ────────────────────────────────────────────────────────────


def _mock_runner(execute_return=None, discover_return=None):
    """Create a mock SkillRunner with controllable return values."""
    runner = MagicMock()
    if execute_return is not None:
        runner.execute.return_value = execute_return
    if discover_return is not None:
        runner.discover.return_value = discover_return
    return runner


# ── discover_skills() ──────────────────────────────────────────────────


class TestDiscoverSkills:

    def test_basic_discovery_returns_s2_result(self):
        """discover_skills() returns S2DiscoveryResult with correct structure."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="read file", limit=3),
            skills=[
                DiscoveredSkill(name="file.read", description="Read a file", score=0.9),
                DiscoveredSkill(name="file.write", description="Write a file", score=0.7),
            ],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        query = S2DiscoveryQuery(query="read file", limit=3)
        result = adapter.discover_skills(query)

        assert isinstance(result, S2DiscoveryResult)
        assert len(result.skills) == 2
        assert result.query.query == "read file"
        assert result.query.limit == 3

    def test_ordering_preserved(self):
        """Skills are returned in the same descending-score order."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="math", limit=5),
            skills=[
                DiscoveredSkill(name="math.add", description="Add numbers", score=0.95),
                DiscoveredSkill(name="math.sub", description="Subtract numbers", score=0.8),
                DiscoveredSkill(name="math.mul", description="Multiply numbers", score=0.6),
            ],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(S2DiscoveryQuery(query="math", limit=5))
        scores = [sk.score for sk in result.skills]
        assert scores == [0.95, 0.8, 0.6]
        names = [sk.name for sk in result.skills]
        assert names == ["math.add", "math.sub", "math.mul"]

    def test_limit_respected(self):
        """Result does not exceed the query limit."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="tool", limit=2),
            skills=[
                DiscoveredSkill(name="a", description="...", score=1.0),
                DiscoveredSkill(name="b", description="...", score=0.5),
            ],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(S2DiscoveryQuery(query="tool", limit=2))
        assert len(result.skills) == 2

    def test_empty_skills_when_no_matches(self):
        """Returns empty list when S3 returns no skills."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="nonexistent", limit=5),
            skills=[],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        result = adapter.discover_skills(
            S2DiscoveryQuery(query="nonexistent", limit=5),
        )
        assert result.skills == []

    def test_calls_runner_with_s3_query(self):
        """Adapter converts S2 query to S3 and passes to runner."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="test", limit=3),
            skills=[],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        adapter.discover_skills(S2DiscoveryQuery(query="test", limit=3))

        runner.discover.assert_called_once()
        call_arg = runner.discover.call_args[0][0]
        assert isinstance(call_arg, SkillDiscoveryQuery)
        assert call_arg.query == "test"
        assert call_arg.limit == 3


# ── call_skill() ───────────────────────────────────────────────────────


class TestCallSkill:

    def test_successful_execution(self):
        """call_skill() returns S2SkillResult with success=True and output."""
        s3_result = SkillResult(
            request_id="req-1",
            success=True,
            output={"contents": "hello world"},
            error=None,
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        request = S2SkillCallRequest(
            skill_name="file.read",
            arguments={"path": "/tmp/test.txt"},
            request_id="req-1",
        )
        result = adapter.call_skill(request)

        assert isinstance(result, S2SkillResult)
        assert result.request_id == "req-1"
        assert result.success is True
        assert result.output == {"contents": "hello world"}
        assert result.error is None

    def test_failed_execution(self):
        """call_skill() returns S2SkillResult with success=False and error."""
        s3_result = SkillResult(
            request_id="req-2",
            success=False,
            output=None,
            error="Skill not found: bad.skill",
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        request = S2SkillCallRequest(
            skill_name="bad.skill",
            arguments={},
            request_id="req-2",
        )
        result = adapter.call_skill(request)

        assert result.request_id == "req-2"
        assert result.success is False
        assert result.output is None
        assert result.error == "Skill not found: bad.skill"

    def test_request_id_preserved(self):
        """request_id is passed through from S2 → S3 → S2 unchanged."""
        s3_result = SkillResult(
            request_id="id-abc-123",
            success=True,
            output={},
            error=None,
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        result = adapter.call_skill(
            S2SkillCallRequest(
                skill_name="test.skill",
                arguments={},
                request_id="id-abc-123",
            ),
        )
        assert result.request_id == "id-abc-123"

    def test_calls_runner_with_s3_request(self):
        """Adapter converts S2 request to S3 SkillCallRequest before executing."""
        s3_result = SkillResult(
            request_id="req-x",
            success=True,
            output={},
            error=None,
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        adapter.call_skill(
            S2SkillCallRequest(
                skill_name="json.parse",
                arguments={"data": '{"a":1}'},
                request_id="req-x",
            ),
        )

        runner.execute.assert_called_once()
        call_arg = runner.execute.call_args[0][0]
        assert isinstance(call_arg, SkillCallRequest)
        assert call_arg.skill_name == "json.parse"
        assert call_arg.arguments == {"data": '{"a":1}'}
        assert call_arg.request_id == "req-x"


# ── type translation / round-trip ──────────────────────────────────────


class TestRoundTrip:

    def test_execution_round_trip_no_field_loss(self):
        """S2 → S3 → S2 round-trip preserves all fields."""
        s3_result = SkillResult(
            request_id="round-trip-1",
            success=True,
            output={"key": "value", "nested": {"deep": True}},
            error=None,
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        request = S2SkillCallRequest(
            skill_name="my.skill",
            arguments={"a": 1, "b": "two"},
            request_id="round-trip-1",
        )
        result = adapter.call_skill(request)

        assert result.request_id == "round-trip-1"
        assert result.success is True
        assert result.output == {"key": "value", "nested": {"deep": True}}
        assert result.error is None

    def test_discovery_round_trip_no_field_loss(self):
        """S2 → S3 → S2 round-trip preserves all discovery fields."""
        s3_result = SkillDiscoveryResult(
            query=SkillDiscoveryQuery(query="round trip", limit=4),
            skills=[
                DiscoveredSkill(name="s1", description="Skill one", score=0.9),
                DiscoveredSkill(name="s2", description="Skill two", score=0.6),
                DiscoveredSkill(name="s3", description="Skill three", score=0.3),
            ],
        )
        runner = _mock_runner(discover_return=s3_result)
        adapter = S3Adapter(runner)

        query = S2DiscoveryQuery(query="round trip", limit=4)
        result = adapter.discover_skills(query)

        assert result.query.query == "round trip"
        assert result.query.limit == 4
        assert len(result.skills) == 3
        assert result.skills[0].name == "s1"
        assert result.skills[0].score == 0.9
        assert result.skills[2].name == "s3"
        assert result.skills[2].score == 0.3

    def test_no_mutation_of_input(self):
        """Adapter does not mutate the input S2 objects."""
        s3_result = SkillResult(
            request_id="immutable-test",
            success=True,
            output={"x": 1},
            error=None,
        )
        runner = _mock_runner(execute_return=s3_result)
        adapter = S3Adapter(runner)

        arguments = {"key": "original"}
        request = S2SkillCallRequest(
            skill_name="test.immutable",
            arguments=arguments,
            request_id="immutable-test",
        )
        adapter.call_skill(request)

        assert request.skill_name == "test.immutable"
        assert request.arguments == {"key": "original"}
        assert arguments == {"key": "original"}
        assert request.request_id == "immutable-test"
