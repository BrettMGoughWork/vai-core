"""Phase 5.8 — Agent Selection Strategy

Provides deterministic agent-to-step matching for workflow steps that
declare an ``agent_profile`` in their config.  The strategy implements a
simple fallback chain:

1. **Explicit ``agent_id``** — if the step config contains a literal
   ``agent_id``, use that agent directly.
2. **Profile match** — if the step config contains an ``agent_profile``
   string, match agents whose ``persona`` field contains that string
   (case-insensitive substring match).  When multiple agents match, the
   first registered match wins.
3. **Fallback** — return the ``default-agent_id`` (configurable).

Usage::

    strategy = AgentSelectionStrategy(registry)
    agent_id = strategy.select(step_config)
    # Returns "analyst-agent", "default-agent", etc.
"""

from __future__ import annotations

from typing import Optional

from src.agent.registry import AgentRegistry, AgentNotFoundError


DEFAULT_AGENT_ID = "default-agent"
"""Fallback agent ID used when no profile match is found."""


class AgentSelectionStrategy:
    """Deterministic agent selection based on workflow step config.

    The strategy is read-only with respect to the registry — it never
    mutates registry state.

    Parameters
    ----------
    registry:
        The ``AgentRegistry`` to query for available agents.
    default_agent_id:
        Agent ID to return when no profile matches (default: ``"default-agent"``).
    """

    def __init__(
        self,
        registry: AgentRegistry,
        default_agent_id: str = DEFAULT_AGENT_ID,
    ) -> None:
        self._registry = registry
        self._default_agent_id = default_agent_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, step_config: dict) -> str:
        """Select an agent ID for *step_config*.

        Resolution order:
        1. ``step_config["agent_id"]`` — explicit agent ID
        2. ``step_config["agent_profile"]`` — persona substring match
        3. ``self._default_agent_id`` — configured fallback

        Args:
            step_config: The ``config`` dict from a ``WorkflowStep``.

        Returns:
            A registered agent ID string.

        Raises:
            AgentNotFoundError: If the resolved agent_id is not registered.
        """
        # 1. Explicit agent_id
        explicit = step_config.get("agent_id")
        if explicit and self._registry.has_agent(explicit):
            return explicit

        # 2. Profile-based match
        profile = step_config.get("agent_profile")
        if profile:
            match = self._match_by_persona(profile)
            if match is not None:
                return match

        # 3. Fallback to configured default
        if not self._registry.has_agent(self._default_agent_id):
            raise AgentNotFoundError(
                f"default agent {self._default_agent_id!r} is not registered"
            )
        return self._default_agent_id

    def select_metadata(self, step_config: dict):
        """Convenience: return the full ``AgentMetadata`` for the selected agent.

        Equivalent to::

            agent_id = strategy.select(step_config)
            metadata = registry.get_agent(agent_id)
        """
        agent_id = self.select(step_config)
        return self._registry.get_agent(agent_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _match_by_persona(self, profile: str) -> Optional[str]:
        """Find the first agent whose *persona* contains *profile*.

        Comparison is case-insensitive.  Returns ``None`` when no agent
        matches.
        """
        profile_lower = profile.lower()
        for metadata in self._registry.list_agents():
            if profile_lower in metadata.persona.lower():
                return metadata.identity.agent_id
        return None
