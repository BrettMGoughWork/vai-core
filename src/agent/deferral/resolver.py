"""
Deferral resolver — resolve a delegate agent from its ``agent_id``.

Validates that the delegate exists in the registry and is not the
same as the caller.  Also checks that the caller is *allowed* to
defer to the target (i.e. the target is in the caller's ``defer_to``
list).

This is a pure step — no side effects, no state mutation.
"""

from __future__ import annotations

from src.agent.registry import AgentMetadata, AgentRegistry, AgentNotFoundError


class DeferralResolverError(Exception):
    """Base error for deferral resolution."""


class DelegateNotAllowedError(DeferralResolverError):
    """Raised when the caller is not allowed to defer to the target."""


class DelegateSelfReferentialError(DeferralResolverError):
    """Raised when an agent attempts to defer to itself."""


class DeferralResolver:
    """Resolves and validates deferral targets at runtime."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        caller_id: str,
        target_id: str,
    ) -> AgentMetadata:
        """Resolve *target_id* as a valid deferral target for *caller_id*.

        Parameters
        ----------
        caller_id:
            The agent that wants to defer.
        target_id:
            The agent to hand off work to.

        Returns
        -------
        AgentMetadata:
            Metadata for the resolved delegate agent.

        Raises
        ------
        DelegateSelfReferentialError:
            If *caller_id* == *target_id*.
        AgentNotFoundError:
            If *target_id* is not registered.
        DelegateNotAllowedError:
            If *target_id* is not in *caller_id*'s ``defer_to`` list.
        """
        if caller_id == target_id:
            raise DelegateSelfReferentialError(
                f"Agent {caller_id!r} cannot defer to itself"
            )

        caller_meta = self._registry.get_agent(caller_id)
        delegate_meta = self._registry.get_agent(target_id)

        if target_id not in caller_meta.defer_to:
            raise DelegateNotAllowedError(
                f"Agent {caller_id!r} is not allowed to defer to "
                f"{target_id!r}.  Allowed targets: {caller_meta.defer_to}"
            )

        return delegate_meta


def resolve_delegate(
    registry: AgentRegistry,
    caller_id: str,
    target_id: str,
) -> AgentMetadata:
    """Convenience function — see ``DeferralResolver.resolve()``."""
    return DeferralResolver(registry).resolve(caller_id, target_id)
