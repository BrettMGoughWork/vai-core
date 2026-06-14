"""
Tests for Phase 5.1 — Agent Registry & Identity.

Covers AgentIdentity, AgentConstraints, AgentMetadata, and the
AgentRegistry (registration + discovery).  The registry is static,
deterministic, and read‑only at runtime.
"""

from __future__ import annotations

import pytest

from src.agent.registry import (
    AGENT_REGISTRY_VERSION,
    CAP_ANALYSIS,
    CAP_CONVERSATIONAL,
    CAP_PLANNING,
    CAP_ROUTING,
    CAP_TOOL_USE,
    PROVENANCE_BUILTIN,
    PROVENANCE_SYSTEM,
    PROVENANCE_USER_DEFINED,
    SANDBOX_NONE,
    SANDBOX_PROCESS,
    VALID_CAPABILITIES,
    AgentConstraints,
    AgentHandle,
    AgentIdentity,
    AgentMetadata,
    AgentNotFoundError,
    AgentRegistry,
    AgentRegistryError,
    DuplicateAgentError,
)


# ===========================================================================
# AgentIdentity
# ===========================================================================


class TestAgentIdentity:
    def test_minimal_construction(self) -> None:
        ident = AgentIdentity(agent_id="assistant-v1", name="Assistant")
        assert ident.agent_id == "assistant-v1"
        assert ident.name == "Assistant"
        assert ident.description == ""
        assert ident.version == "1.0.0"
        assert ident.provenance == PROVENANCE_BUILTIN

    def test_full_construction(self) -> None:
        ident = AgentIdentity(
            agent_id="planner-v2",
            name="Planner",
            description="Generates multi-step plans",
            version="2.1.0",
            provenance=PROVENANCE_SYSTEM,
        )
        assert ident.agent_id == "planner-v2"
        assert ident.version == "2.1.0"
        assert ident.provenance == PROVENANCE_SYSTEM

    def test_empty_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="agent_id must be non-empty"):
            AgentIdentity(agent_id="", name="x")

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name must be non-empty"):
            AgentIdentity(agent_id="x", name="")

    def test_empty_version_raises(self) -> None:
        with pytest.raises(ValueError, match="version must be non-empty"):
            AgentIdentity(agent_id="x", name="x", version="")

    def test_invalid_provenance_raises(self) -> None:
        with pytest.raises(ValueError, match="provenance must be one of"):
            AgentIdentity(
                agent_id="x", name="x", provenance="cloud"
            )

    def test_invalid_semver_raises(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            AgentIdentity(agent_id="x", name="x", version="abc")

    def test_partial_semver_raises(self) -> None:
        with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
            AgentIdentity(agent_id="x", name="x", version="1.0")

    def test_is_frozen(self) -> None:
        ident = AgentIdentity(agent_id="x", name="x")
        with pytest.raises(Exception):
            ident.agent_id = "y"  # type: ignore[misc]


# ===========================================================================
# AgentConstraints
# ===========================================================================


class TestAgentConstraints:
    def test_defaults(self) -> None:
        c = AgentConstraints()
        assert c.max_tokens == 0
        assert c.timeout_ms == 0
        assert c.sandbox == SANDBOX_NONE

    def test_custom_values(self) -> None:
        c = AgentConstraints(max_tokens=4096, timeout_ms=30000, sandbox=SANDBOX_PROCESS)
        assert c.max_tokens == 4096
        assert c.timeout_ms == 30000
        assert c.sandbox == SANDBOX_PROCESS

    def test_zero_is_valid(self) -> None:
        c = AgentConstraints(max_tokens=0, timeout_ms=0)
        assert c.max_tokens == 0

    def test_negative_max_tokens_raises(self) -> None:
        with pytest.raises(ValueError, match="max_tokens"):
            AgentConstraints(max_tokens=-1)

    def test_negative_timeout_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout_ms"):
            AgentConstraints(timeout_ms=-100)

    def test_invalid_sandbox_raises(self) -> None:
        with pytest.raises(ValueError, match="sandbox must be one of"):
            AgentConstraints(sandbox="vm")

    def test_is_frozen(self) -> None:
        c = AgentConstraints()
        with pytest.raises(Exception):
            c.max_tokens = 999  # type: ignore[misc]


# ===========================================================================
# AgentMetadata
# ===========================================================================


class TestAgentMetadata:
    def test_minimal_construction(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(identity=ident)
        assert meta.identity.agent_id == "a1"
        assert meta.capabilities == []
        assert meta.inputs == []
        assert meta.outputs == []

    def test_with_capabilities(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(
            identity=ident,
            capabilities=[CAP_CONVERSATIONAL, CAP_TOOL_USE],
            inputs=["text"],
            outputs=["text", "actions"],
        )
        assert CAP_CONVERSATIONAL in meta.capabilities
        assert "text" in meta.inputs

    def test_unknown_capability_raises(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        with pytest.raises(ValueError, match="unknown capability"):
            AgentMetadata(identity=ident, capabilities=["telepathy"])

    def test_non_list_capabilities_raises(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        with pytest.raises(ValueError, match="capabilities must be a list"):
            AgentMetadata(identity=ident, capabilities="conversational")  # type: ignore[arg-type]

    def test_with_constraints(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        constraints = AgentConstraints(max_tokens=2048)
        meta = AgentMetadata(identity=ident, constraints=constraints)
        assert meta.constraints.max_tokens == 2048

    def test_is_frozen(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(identity=ident)
        with pytest.raises(Exception):
            meta.capabilities = [CAP_PLANNING]  # type: ignore[misc]


# ===========================================================================
# AgentHandle
# ===========================================================================


class TestAgentHandle:
    def test_construction(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(identity=ident)
        handle = AgentHandle(agent_id="a1", metadata=meta)
        assert handle.agent_id == "a1"
        assert handle.metadata.identity.name == "Agent 1"

    def test_is_frozen(self) -> None:
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(identity=ident)
        handle = AgentHandle(agent_id="a1", metadata=meta)
        with pytest.raises(Exception):
            handle.agent_id = "a2"  # type: ignore[misc]


# ===========================================================================
# AgentRegistry
# ===========================================================================


class TestAgentRegistryRegistration:
    def test_register_agent(self) -> None:
        registry = AgentRegistry()
        ident = AgentIdentity(agent_id="a1", name="Agent 1")
        meta = AgentMetadata(identity=ident)
        handle = registry.register_agent(meta)
        assert handle.agent_id == "a1"
        assert registry.agent_count == 1

    def test_register_multiple_agents(self) -> None:
        registry = AgentRegistry()
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        )
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a2", name="B"))
        )
        assert registry.agent_count == 2

    def test_duplicate_agent_id_raises(self) -> None:
        registry = AgentRegistry()
        meta = AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        registry.register_agent(meta)
        with pytest.raises(DuplicateAgentError, match="already registered"):
            registry.register_agent(
                AgentMetadata(AgentIdentity(agent_id="a1", name="Different"))
            )

    def test_duplicate_identical_metadata_is_idempotent(self) -> None:
        registry = AgentRegistry()
        meta = AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        h1 = registry.register_agent(meta)
        h2 = registry.register_agent(meta)
        assert h1.agent_id == h2.agent_id
        assert registry.agent_count == 1

    def test_register_non_agent_metadata_raises(self) -> None:
        registry = AgentRegistry()
        with pytest.raises(TypeError, match="AgentMetadata"):
            registry.register_agent("not-metadata")  # type: ignore[arg-type]


class TestAgentRegistryDiscovery:
    def test_get_agent(self) -> None:
        registry = AgentRegistry()
        meta = AgentMetadata(AgentIdentity(agent_id="a1", name="Agent 1"))
        registry.register_agent(meta)
        assert registry.get_agent("a1").identity.name == "Agent 1"

    def test_get_agent_not_found_raises(self) -> None:
        registry = AgentRegistry()
        with pytest.raises(AgentNotFoundError, match="not found"):
            registry.get_agent("nonexistent")

    def test_find_agents_by_capability(self) -> None:
        registry = AgentRegistry()
        registry.register_agent(
            AgentMetadata(
                AgentIdentity(agent_id="a1", name="A"),
                capabilities=[CAP_CONVERSATIONAL],
            )
        )
        registry.register_agent(
            AgentMetadata(
                AgentIdentity(agent_id="a2", name="B"),
                capabilities=[CAP_PLANNING],
            )
        )
        registry.register_agent(
            AgentMetadata(
                AgentIdentity(agent_id="a3", name="C"),
                capabilities=[CAP_CONVERSATIONAL, CAP_ROUTING],
            )
        )
        results = registry.find_agents_by_capability(CAP_CONVERSATIONAL)
        assert len(results) == 2
        assert {r.identity.agent_id for r in results} == {"a1", "a3"}

    def test_find_agents_by_unknown_capability(self) -> None:
        registry = AgentRegistry()
        assert registry.find_agents_by_capability("telepathy") == []

    def test_list_agents(self) -> None:
        registry = AgentRegistry()
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        )
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a2", name="B"))
        )
        agents = registry.list_agents()
        assert len(agents) == 2

    def test_list_agents_empty(self) -> None:
        registry = AgentRegistry()
        assert registry.list_agents() == []

    def test_has_agent(self) -> None:
        registry = AgentRegistry()
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        )
        assert registry.has_agent("a1")
        assert not registry.has_agent("unknown")

    def test_discovery_is_read_only(self) -> None:
        """Discovery methods must not mutate registry state."""
        registry = AgentRegistry()
        registry.register_agent(
            AgentMetadata(AgentIdentity(agent_id="a1", name="A"))
        )
        before = registry.agent_count
        registry.find_agents_by_capability(CAP_CONVERSATIONAL)
        registry.list_agents()
        registry.get_agent("a1")
        assert registry.agent_count == before
