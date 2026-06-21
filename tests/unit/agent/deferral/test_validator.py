"""Tests for deferral graph validator (acyclicity check)."""

import pytest

from src.agent.deferral.validator import (
    DeferralCycleError,
    DeferralGraphError,
    validate_deferral_graph,
)
from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentRegistry,
)


def _make_meta(agent_id: str, name: str = "", defer_to=None) -> AgentMetadata:
    return AgentMetadata(
        identity=AgentIdentity(agent_id=agent_id, name=name or agent_id),
        defer_to=list(defer_to or []),
    )


class TestValidateDeferralGraph:
    """Registration-time acyclicity validation."""

    def test_empty_graph_passes(self):
        """No agents or no defer_to entries — always valid."""
        registry = AgentRegistry()
        validate_deferral_graph(registry)  # no agents

        registry.register_agent(_make_meta("a"))
        validate_deferral_graph(registry)  # one agent, no defer

    def test_simple_linear_chain_passes(self):
        """A -> B -> C — acyclic."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        registry.register_agent(_make_meta("b", defer_to=["c"]))
        registry.register_agent(_make_meta("c"))
        validate_deferral_graph(registry)

    def test_tree_passes(self):
        """A -> [B, C], B -> D, C -> E — acyclic."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b", "c"]))
        registry.register_agent(_make_meta("b", defer_to=["d"]))
        registry.register_agent(_make_meta("c", defer_to=["e"]))
        registry.register_agent(_make_meta("d"))
        registry.register_agent(_make_meta("e"))
        validate_deferral_graph(registry)

    def test_self_deferral_detected(self):
        """An agent deferring to itself is a trivial cycle."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["a"]))
        with pytest.raises(DeferralCycleError, match="self-deferral"):
            validate_deferral_graph(registry)

    def test_direct_cycle_detected(self):
        """A -> B -> A — direct cycle."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        registry.register_agent(_make_meta("b", defer_to=["a"]))
        with pytest.raises(DeferralCycleError) as exc:
            validate_deferral_graph(registry)
        assert "a" in str(exc.value)
        assert "b" in str(exc.value)

    def test_indirect_cycle_detected(self):
        """A -> B -> C -> A — indirect 3-cycle."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        registry.register_agent(_make_meta("b", defer_to=["c"]))
        registry.register_agent(_make_meta("c", defer_to=["a"]))
        with pytest.raises(DeferralCycleError) as exc:
            validate_deferral_graph(registry)
        msg = str(exc.value)
        assert "a" in msg and "b" in msg and "c" in msg

    def test_longer_cycle_detected(self):
        """A -> B -> C -> D -> B — cycle not starting at root."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        registry.register_agent(_make_meta("b", defer_to=["c"]))
        registry.register_agent(_make_meta("c", defer_to=["d"]))
        registry.register_agent(_make_meta("d", defer_to=["b"]))
        with pytest.raises(DeferralCycleError):
            validate_deferral_graph(registry)

    def test_unknown_agent_detected(self):
        """Deferring to an unregistered agent is a graph error."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        with pytest.raises(DeferralGraphError, match="not registered"):
            validate_deferral_graph(registry)

    def test_disconnected_components_pass(self):
        """A -> B, C -> D — independent acyclic chains."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b"]))
        registry.register_agent(_make_meta("b"))
        registry.register_agent(_make_meta("c", defer_to=["d"]))
        registry.register_agent(_make_meta("d"))
        validate_deferral_graph(registry)

    def test_empty_defer_to_list(self):
        """Explicit empty defer_to list is valid."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=[]))
        registry.register_agent(_make_meta("b", defer_to=[]))
        validate_deferral_graph(registry)

    def test_diamond_passes(self):
        """A -> [B, C], B -> D, C -> D — diamond, acyclic."""
        registry = AgentRegistry()
        registry.register_agent(_make_meta("a", defer_to=["b", "c"]))
        registry.register_agent(_make_meta("b", defer_to=["d"]))
        registry.register_agent(_make_meta("c", defer_to=["d"]))
        registry.register_agent(_make_meta("d"))
        validate_deferral_graph(registry)
