"""
Phase 5.8 — Agent Selection Strategy Unit Tests
=================================================

Tests for AgentSelectionStrategy — the deterministic agent-to-step
matching logic for workflow steps that declare an ``agent_profile``.

Covers:
- s9.5: Explicit agent_profile → correct agent selected
- s9.6: No agent_profile → runtime (default) agent used
- s9.7: Agent not found → configurable fallback / error
"""

from __future__ import annotations

import pytest

from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentNotFoundError,
    AgentRegistry,
)
from src.agent.selection import AgentSelectionStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent(
    agent_id: str,
    persona: str = "",
    *,
    name: str = "",
) -> AgentMetadata:
    return AgentMetadata(
        identity=AgentIdentity(
            agent_id=agent_id,
            name=name or agent_id,
        ),
        persona=persona,
        constraints=AgentConstraints(),
    )


def _make_registry(*agents: AgentMetadata) -> AgentRegistry:
    reg = AgentRegistry()
    for a in agents:
        reg.register_agent(a)
    return reg


# ===================================================================
# s9.5 — Explicit agent_profile → correct agent selected
# ===================================================================


class TestExplicitProfile:
    """When a step config provides an explicit ``agent_profile`` string,
    the strategy should match an agent whose ``persona`` field contains
    that substring (case-insensitive)."""

    def test_profile_matches_persona_substring(self):
        """agent_profile "analyst" should match "analyst-agent" whose
        persona contains "analyst"."""
        registry = _make_registry(
            _agent("analyst-agent", persona="You are an analyst agent"),
            _agent("research-agent", persona="You are a research agent"),
            _agent("default-agent", persona="General purpose assistant"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({"agent_profile": "analyst"})
        assert agent_id == "analyst-agent"

    def test_profile_match_is_case_insensitive(self):
        """agent_profile "ANALYST" should still match "analyst-agent"."""
        registry = _make_registry(
            _agent("analyst-agent", persona="You are an Analyst agent"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({"agent_profile": "ANALYST"})
        assert agent_id == "analyst-agent"

    def test_profile_matches_first_registered_when_multiple_match(self):
        """When multiple agents match the profile, the first registered
        agent should be returned."""
        registry = _make_registry(
            _agent("analyst-v1", persona="I am an analyst agent"),
            _agent("analyst-v2", persona="I am an analyst agent as well"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({"agent_profile": "analyst"})
        assert agent_id == "analyst-v1"

    def test_explicit_agent_id_takes_precedence_over_profile(self):
        """When step config has both ``agent_id`` and ``agent_profile``,
        the explicit ``agent_id`` wins."""
        registry = _make_registry(
            _agent("analyst-agent", persona="You are an analyst"),
            _agent("research-agent", persona="You are a researcher"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({
            "agent_id": "research-agent",
            "agent_profile": "analyst",
        })
        assert agent_id == "research-agent"

    def test_select_metadata_returns_full_metadata(self):
        """``select_metadata()`` should return the full AgentMetadata
        for the selected agent."""
        registry = _make_registry(
            _agent("analyst-agent", persona="You are an analyst"),
        )
        strategy = AgentSelectionStrategy(registry)

        meta = strategy.select_metadata({"agent_profile": "analyst"})
        assert meta.identity.agent_id == "analyst-agent"
        assert "analyst" in meta.persona


# ===================================================================
# s9.6 — No agent_profile → runtime agent used
# ===================================================================


class TestNoProfile:
    """When a step config provides no ``agent_profile`` and no explicit
    ``agent_id``, the strategy should return the configured default agent."""

    def test_no_profile_uses_default_agent(self):
        registry = _make_registry(
            _agent("default-agent", persona="General purpose assistant"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({})
        assert agent_id == "default-agent"

    def test_default_can_be_overridden_in_constructor(self):
        registry = _make_registry(
            _agent("custom-default", persona="Custom default agent"),
        )
        strategy = AgentSelectionStrategy(registry, default_agent_id="custom-default")

        agent_id = strategy.select({})
        assert agent_id == "custom-default"

    def test_step_config_with_irrelevant_keys_returns_default(self):
        """Extra keys in step_config that are not agent_id/agent_profile
        should be ignored, and the default agent returned."""
        registry = _make_registry(
            _agent("default-agent", persona="General purpose"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({
            "step_type": "llm_call",
            "prompt": "Hello",
        })
        assert agent_id == "default-agent"


# ===================================================================
# s9.7 — Agent not found → configurable fallback / fail
# ===================================================================


class TestAgentNotFound:
    """When the resolved agent (whether explicit, profile-match, or
    default) is not registered, the strategy should raise."""

    def test_explicit_agent_not_registered_falls_to_default(self):
        """When step config specifies an agent_id that is not in the
        registry, the strategy falls through to the default agent."""
        registry = _make_registry(
            _agent("default-agent", persona="General purpose"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({"agent_id": "unknown-agent"})
        assert agent_id == "default-agent"

    def test_profile_match_no_agents_returns_default(self):
        """When no agent matches the profile, the default agent should
        be returned (not a failure)."""
        registry = _make_registry(
            _agent("default-agent", persona="General purpose"),
        )
        strategy = AgentSelectionStrategy(registry)

        agent_id = strategy.select({"agent_profile": "nonexistent-profile"})
        assert agent_id == "default-agent"

    def test_default_agent_not_registered_raises(self):
        """When the configured default agent is not in the registry,
        AgentNotFoundError should be raised."""
        registry = _make_registry()  # Empty registry — no default agent
        strategy = AgentSelectionStrategy(registry)

        with pytest.raises(AgentNotFoundError, match="default-agent"):
            strategy.select({})

    def test_custom_default_not_registered_raises(self):
        """When a custom default_agent_id is provided but not registered,
        AgentNotFoundError should be raised."""
        registry = _make_registry()  # Empty registry
        strategy = AgentSelectionStrategy(registry, default_agent_id="missing-default")

        with pytest.raises(AgentNotFoundError, match="missing-default"):
            strategy.select({})
