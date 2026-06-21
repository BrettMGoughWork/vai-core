"""Tests for the deferral resolver."""

import pytest

from src.agent.deferral.resolver import (
    DeferralResolver,
    DelegateNotAllowedError,
    DelegateSelfReferentialError,
    resolve_delegate,
)
from src.agent.registry import (
    AgentConstraints,
    AgentIdentity,
    AgentMetadata,
    AgentNotFoundError,
    AgentRegistry,
)


def _make_meta(agent_id: str, name: str = "", defer_to=None) -> AgentMetadata:
    return AgentMetadata(
        identity=AgentIdentity(agent_id=agent_id, name=name or agent_id),
        defer_to=list(defer_to or []),
    )


class TestDeferralResolver:
    """Runtime target validation."""

    def test_resolve_valid_target(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["target"]))
        registry.register_agent(_make_meta("target"))
        resolver = DeferralResolver(registry)
        result = resolver.resolve("caller", "target")
        assert result.identity.agent_id == "target"

    def test_resolve_self_deferral(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("agent"))
        resolver = DeferralResolver(registry)
        with pytest.raises(DelegateSelfReferentialError, match="itself"):
            resolver.resolve("agent", "agent")

    def test_resolve_unknown_target(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["ghost"]))
        resolver = DeferralResolver(registry)
        with pytest.raises(AgentNotFoundError):
            resolver.resolve("caller", "ghost")

    def test_resolve_unknown_caller(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("target"))
        resolver = DeferralResolver(registry)
        with pytest.raises(AgentNotFoundError):
            resolver.resolve("ghost", "target")

    def test_resolve_not_in_defer_to_list(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["a"]))
        registry.register_agent(_make_meta("b"))
        resolver = DeferralResolver(registry)
        with pytest.raises(DelegateNotAllowedError, match="not allowed"):
            resolver.resolve("caller", "b")

    def test_resolve_multiple_allowed_targets(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["a", "b", "c"]))
        registry.register_agent(_make_meta("b"))
        resolver = DeferralResolver(registry)
        result = resolver.resolve("caller", "b")
        assert result.identity.agent_id == "b"

    def test_convenience_function(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["target"]))
        registry.register_agent(_make_meta("target"))
        result = resolve_delegate(registry, "caller", "target")
        assert result.identity.agent_id == "target"


class TestDelegateNotAllowedErrorMessage:
    def test_lists_allowed_targets(self):
        registry = AgentRegistry()
        registry.register_agent(_make_meta("caller", defer_to=["billing", "tech"]))
        registry.register_agent(_make_meta("unrelated"))
        resolver = DeferralResolver(registry)
        with pytest.raises(DelegateNotAllowedError) as exc:
            resolver.resolve("caller", "unrelated")
        assert "billing" in str(exc.value)
        assert "tech" in str(exc.value)
