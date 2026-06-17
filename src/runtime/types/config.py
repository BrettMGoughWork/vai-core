"""
Shared configuration dataclasses for cross-stratum use.

Types defined here are used by multiple strata (S2 strategy, S3 capabilities)
and are thus housed in the runtime (S1) stratum which is importable by all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ProviderConfig:
    """Configuration for a single search provider.

    One instance per registered provider (e.g. 'tavily', 'duckduckgo').
    API keys are resolved from environment at load time, never exposed
    to the LLM.
    """

    max_results: int = 10
    """Default maximum number of results to return per query."""

    timeout: float = 15.0
    """Per-request timeout in seconds."""

    rate_limit_rps: float | None = None
    """Optional rate limit in requests-per-second."""

    api_key_env: str | None = None
    """Name of the environment variable holding the API key.

    Set for providers that require authentication (e.g. 'TAVILY_API_KEY').
    ``None`` for providers that don't need a key (e.g. DuckDuckGo).
    """

    endpoint: str | None = None
    """Optional endpoint override for the provider's search API."""

    params: Dict[str, Any] = field(default_factory=dict)
    """Provider-specific parameters injected into every request."""

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "ProviderConfig":
        """Create ProviderConfig from a YAML dictionary."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class SearchProviderConfig:
    """Legacy flat search provider configuration.

    Kept for backward compatibility with existing tests and skills.
    New code should use ``SearchConfig`` instead.
    """

    provider: str = ""
    api_key: str | None = None
    max_results: int = 10
    timeout: float = 15.0
    enabled: bool = False
    endpoint: str | None = None
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchConfig:
    """Top-level search configuration.

    This is stored in the runtime, NEVER exposed to the LLM.
    The LLM receives only normalised search results.
    """

    default_provider: str
    """Canonical name of the default search provider."""

    enabled: bool = False
    """Whether search is enabled at runtime."""

    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    """Provider configurations keyed by canonical name."""

    @classmethod
    def from_yaml(cls, data: Dict[str, Any] | None) -> "SearchConfig | None":
        """Create SearchConfig from a YAML dictionary.

        Returns ``None`` if *data* is ``None`` or empty.
        """
        if not data:
            return None

        enabled = data.get("enabled", False)
        default_provider = data.get("default_provider", "")
        raw_providers = data.get("providers", {}) or {}

        providers: Dict[str, ProviderConfig] = {}
        for name, raw_cfg in raw_providers.items():
            providers[name] = ProviderConfig.from_yaml(raw_cfg)

        return cls(
            default_provider=default_provider,
            enabled=enabled,
            providers=providers,
        )


@dataclass
class EmbeddingConfig:
    """Configuration for embedding providers.

    Controls which embedding backend to use for skill-discovery
    fallback.  Embeddings are ONLY consulted when the LLM fails to
    name a capability.
    """

    provider: str = "mock"
    """Canonical provider name: 'openai' | 'local' | 'mock'."""

    model: str = "text-embedding-3-small"
    """Model identifier passed to the provider."""

    dimensions: int = 1536
    """Expected embedding vector dimension."""

    api_key_env: str | None = None
    """Name of the environment variable holding the API key.

    Set for providers that require authentication (e.g. ``'OPENAI_API_KEY'``).
    ``None`` for providers that don't need a key (e.g. mock, local)."""

    @classmethod
    def from_yaml(cls, data: Dict[str, Any] | None) -> "EmbeddingConfig | None":
        """Create EmbeddingConfig from a YAML dictionary.

        Returns ``None`` if *data* is ``None`` or empty.
        """
        if not data:
            return None
        return cls(
            provider=data.get("provider", "mock"),
            model=data.get("model", "text-embedding-3-small"),
            dimensions=data.get("dimensions", 1536),
            api_key_env=data.get("api_key_env"),
        )
