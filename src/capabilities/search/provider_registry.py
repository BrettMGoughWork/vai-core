"""Provider registry for S3 search providers (PHASE 3.13.1).

The registry loads provider configurations from ``SearchConfig``
and creates provider instances on demand.  Each provider is
initialised lazily — API keys are resolved from the environment
at construction time.

Provider identity and configuration are NEVER exposed to the LLM.
"""

from __future__ import annotations

from typing import Type

from src.capabilities.search.providers._base import SearchProvider
from src.capabilities.search.providers.duckduckgo import DuckDuckGoProvider
from src.capabilities.search.providers.tavily import TavilyProvider
from src.strategy.state.config import SearchConfig, ProviderConfig


class RegistryError(Exception):
    """Raised when the provider registry encounters a configuration error."""


class ProviderRegistry:
    """Registry for S3 search providers.

    Maps canonical provider names to provider classes and their
    configuration.  Instances are created on demand via ``get_provider()``.
    """

    # Built-in provider class registry
    _BUILTIN_PROVIDERS: dict[str, Type] = {
        "duckduckgo": DuckDuckGoProvider,
        "tavily": TavilyProvider,
    }

    def __init__(self, config: SearchConfig) -> None:
        self._config = config
        self._custom_providers: dict[str, Type] = {}
        self._instances: dict[str, SearchProvider] = {}

        self._validate()

    # ── validation ────────────────────────────────────────────────────

    def _validate(self) -> None:
        """Validate the registry configuration on construction.

        Only validates the default provider — individual provider
        class checks are deferred to ``get_provider()`` to allow
        ``register_provider()`` to be called after construction.
        """
        default = self._config.default_provider

        if not default:
            raise RegistryError(
                "search.default_provider is not set in config"
            )

        if default not in self._config.providers:
            raise RegistryError(
                f"Default provider '{default}' has no configuration "
                f"in search.providers"
            )

    # ── registration ──────────────────────────────────────────────────

    def register_provider(self, name: str, provider_cls: Type) -> None:
        """Register a custom provider class.

        Args:
            name: Canonical provider name (must match a key in
                  ``search.providers`` config).
            provider_cls: A class implementing the ``SearchProvider`` protocol.
        """
        self._custom_providers[name] = provider_cls

    # ── lookup ────────────────────────────────────────────────────────

    def get_provider(self, name: str) -> SearchProvider:
        """Get (or create) a provider instance by canonical name.

        Args:
            name: Canonical provider name (e.g. 'tavily', 'duckduckgo').

        Returns:
            An initialised ``SearchProvider`` instance.

        Raises:
            RegistryError: If the provider is not configured, not registered,
                           or fails initialisation.
        """
        if name in self._instances:
            return self._instances[name]

        provider_cfg = self._config.providers.get(name)
        if provider_cfg is None:
            raise RegistryError(
                f"Provider '{name}' is not configured in search.providers. "
                f"Available: {self._list_configured()}"
            )

        provider_cls = self._BUILTIN_PROVIDERS.get(name) or self._custom_providers.get(name)
        if provider_cls is None:
            raise RegistryError(
                f"Provider '{name}' is not registered. "
                f"Available: {self._list_available()}"
            )

        try:
            instance = provider_cls(provider_cfg)
        except Exception as exc:
            raise RegistryError(
                f"Failed to initialise provider '{name}': {exc}"
            ) from exc

        self._instances[name] = instance
        return instance

    def get_default_provider(self) -> SearchProvider:
        """Get the default provider instance.

        Returns:
            The initialised default ``SearchProvider`` instance.

        Raises:
            RegistryError: If the default provider cannot be initialised.
        """
        return self.get_provider(self._config.default_provider)

    # ── introspection ─────────────────────────────────────────────────

    def _list_configured(self) -> list[str]:
        """List provider names that have configuration entries."""
        return sorted(self._config.providers.keys())

    def _list_available(self) -> list[str]:
        """List all registered provider names (built-in + custom)."""
        return sorted(set(self._BUILTIN_PROVIDERS) | set(self._custom_providers))
