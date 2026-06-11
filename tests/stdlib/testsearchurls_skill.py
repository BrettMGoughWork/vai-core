"""Tests for stdlib.search_urls skill via SkillExecutor (PHASE 3.13.3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.capabilities.primitives.stdlib.search import SearchPrimitive
from src.capabilities.primitives.types import PrimitiveResult
from src.capabilities.registry.primitive_registry import PrimitiveRegistry
from src.capabilities.skills.executor import SkillExecutor
from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill
from src.capabilities.skills.skill_parser import parse_skill_file
from src.strategy.state.config import SearchProviderConfig


@pytest.fixture
def registry() -> PrimitiveRegistry:
    """PrimitiveRegistry with stdlib.search registered."""
    reg = PrimitiveRegistry()
    reg.register("stdlib.search", SearchPrimitive())
    return reg


@pytest.fixture
def skill_md_path() -> Path:
    """Path to the search_urls.skill.md manifest file."""
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "capabilities"
        / "skills"
        / "stdlib"
        / "search_urls.skill.md"
    )


@pytest.fixture
def skill(skill_md_path: Path, registry: PrimitiveRegistry) -> CapabilitySkill:
    """CapabilitySkill built from search_urls.skill.md."""
    parsed = parse_skill_file(str(skill_md_path), registry)

    manifest = SkillManifest(
        name=parsed["name"],
        description=parsed["description"],
        primitives=parsed["primitives"],
        inputs={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "number"},
            },
            "required": ["query"],
        },
        steps=[
            {
                "call": "stdlib.search",
                "args": {
                    "query": "{{ query }}",
                    "max_results": "{{ max_results }}",
                },
            }
        ],
    )

    return CapabilitySkill(
        manifest=manifest,
        primitives={"stdlib.search": registry.get("stdlib.search")},
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "number"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "array"},
                "query": {"type": "string"},
                "elapsed_ms": {"type": "integer"},
            },
        },
    )


@pytest.fixture
def enabled_config() -> SearchProviderConfig:
    """Search config with a fake key so the primitive does not short‑circuit."""
    return SearchProviderConfig(
        provider="tavily",
        api_key="test-key",
        max_results=5,
        timeout=5.0,
        enabled=True,
    )


class TestSearchUrlsSkillParsing:
    """Tests for parsing search_urls.skill.md."""

    def test_manifest_parsed_correctly(
        self, skill_md_path: Path, registry: PrimitiveRegistry
    ) -> None:
        """The .skill.md file parses and resolves the search primitive."""
        parsed = parse_skill_file(str(skill_md_path), registry)
        assert parsed["name"] == "stdlib.search_urls"
        assert parsed["description"] == (
            "Execute a web search and return normalised results (title, url, snippet)"
        )
        assert len(parsed["primitives"]) == 1
        assert isinstance(parsed["primitives"][0], SearchPrimitive)
        assert "query" in parsed["inputs"]
        assert parsed["inputs"]["query"]["required"] is True
        assert "max_results" in parsed["inputs"]


class TestSearchUrlsSkillExecution:
    """End-to-end tests via SkillExecutor (mocked HTTP)."""

    @staticmethod
    def _fake_primitive_result(results=None, query="test"):
        """Build a successful PrimitiveResult matching the search primitive's shape."""
        return PrimitiveResult(
            status="success",
            data={
                "results": results or [],
                "query": query,
                "elapsed_ms": 42,
            },
        )

    def test_valid_query_returns_results(
        self, skill: CapabilitySkill, enabled_config: SearchProviderConfig
    ) -> None:
        """A valid query returns the primitive's result data."""
        fake_results = [
            {"title": "Result 1", "url": "https://a.com", "snippet": "First result"},
            {"title": "Result 2", "url": "https://b.com", "snippet": "Second result"},
        ]
        fake = self._fake_primitive_result(fake_results)

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ):
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "test query", "max_results": 5},
                {"search_config": enabled_config},
            )

        assert result.status == "success"
        assert len(result.results) == 1
        assert result.results[0].data["results"] == fake_results
        assert result.results[0].data["query"] == "test"

    def test_max_results_is_forwarded_to_primitive(
        self, skill: CapabilitySkill, enabled_config: SearchProviderConfig
    ) -> None:
        """max_results from skill inputs is forwarded to the search primitive."""
        fake_results = [
            {"title": "R1", "url": "https://a.com", "snippet": "S1"},
            {"title": "R2", "url": "https://b.com", "snippet": "S2"},
            {"title": "R3", "url": "https://c.com", "snippet": "S3"},
        ]
        fake = self._fake_primitive_result(fake_results[:2])

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ) as mock_exec:
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "test", "max_results": 2},
                {"search_config": enabled_config},
            )

        assert result.status == "success"
        # Verify the primitive received max_results=2
        # (template interpolation stringifies numeric values)
        call_args = mock_exec.call_args[0][0]
        assert call_args["max_results"] == "2"
        assert call_args["query"] == "test"

    def test_query_is_not_rewritten_by_skill(
        self, skill: CapabilitySkill, enabled_config: SearchProviderConfig
    ) -> None:
        """The skill passes the query through unchanged — no rewriting."""
        fake = self._fake_primitive_result()
        original_query = "exact user query with punctuation!?"

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ) as mock_exec:
            executor = SkillExecutor()
            executor.execute(
                skill,
                {"query": original_query, "max_results": 5},
                {"search_config": enabled_config},
            )

        # The primitive must receive the exact, unmodified query
        call_args = mock_exec.call_args[0][0]
        assert call_args["query"] == original_query

    def test_returns_normalized_search_results(
        self, skill: CapabilitySkill, enabled_config: SearchProviderConfig
    ) -> None:
        """The skill returns normalized results with title, url, snippet."""
        normalized = [
            {"title": "Norm Title", "url": "https://norm.example.com", "snippet": "Normalized snippet"},
        ]
        fake = self._fake_primitive_result(normalized)

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ):
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "normalize test", "max_results": 5},
                {"search_config": enabled_config},
            )

        assert result.status == "success"
        output = result.results[0].data["results"]
        assert len(output) == 1
        assert output[0]["title"] == "Norm Title"
        assert output[0]["url"] == "https://norm.example.com"
        assert output[0]["snippet"] == "Normalized snippet"

    def test_no_heuristics_applied_by_skill(
        self, skill: CapabilitySkill, enabled_config: SearchProviderConfig
    ) -> None:
        """The skill does not apply ranking, heuristics, or result rewriting."""
        # Results pass through verbatim — no sorting, filtering, or modification
        raw_results = [
            {"title": "Z Result", "url": "https://z.com", "snippet": "Last alphabetically"},
            {"title": "A Result", "url": "https://a.com", "snippet": "First alphabetically"},
        ]
        fake = self._fake_primitive_result(raw_results)

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ):
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "heuristic test", "max_results": 5},
                {"search_config": enabled_config},
            )

        assert result.status == "success"
        output = result.results[0].data["results"]
        # Order must be preserved exactly as returned by primitive
        assert output[0]["title"] == "Z Result"
        assert output[1]["title"] == "A Result"

    def test_missing_query_raises_validation_error(self, skill: CapabilitySkill) -> None:
        """Missing required 'query' input raises ValueError."""
        executor = SkillExecutor()
        with pytest.raises(ValueError, match="missing required key"):
            executor.execute(skill, {}, {})

    def test_no_results_returns_empty_list(self, skill: CapabilitySkill, enabled_config: SearchProviderConfig) -> None:
        """A query with no results returns an empty list."""
        fake = self._fake_primitive_result(results=[])

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ):
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "noresults", "max_results": 5},
                {"search_config": enabled_config},
            )

        assert result.status == "success"
        assert result.results[0].data["results"] == []

    def test_primitive_error_propagates(self, skill: CapabilitySkill, enabled_config: SearchProviderConfig) -> None:
        """When the primitive returns an error, the skill fails."""
        fake = PrimitiveResult(
            status="error",
            data={"results": [], "error": "network timeout"},
            error="network timeout",
        )

        with patch.object(
            skill.primitives["stdlib.search"], "execute", return_value=fake
        ):
            executor = SkillExecutor()
            result = executor.execute(
                skill,
                {"query": "error case", "max_results": 5},
                {"search_config": enabled_config},
            )

        assert result.status == "error"
        assert result.error == "network timeout"

    def test_disabled_search_returns_error(self, skill: CapabilitySkill) -> None:
        """When search is disabled, the skill propagates the primitive error."""
        disabled_config = SearchProviderConfig(
            provider="tavily",
            api_key="test-key",
            enabled=False,
        )

        executor = SkillExecutor()
        result = executor.execute(
            skill,
            {"query": "anything", "max_results": 5},
            {"search_config": disabled_config},
        )

        assert result.status == "error"
        assert "not configured or disabled" in (result.error or "")
