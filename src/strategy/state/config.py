from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

from src.strategy.types.capabilities import SkillCategory
from src.strategy.types.capabilities import SideEffect


@dataclass
class LLMConfig:
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096


@dataclass
class LoopPolicyConfig:
    max_steps: int = 5
    max_wall_time: Optional[float] = None
    max_errors: int = 1
    max_fatals: int = 1
    per_step_timeout: Optional[float] = None


@dataclass
class AgentConfig:
    model: str
    allowed_tools: List[str]
    allowed_categories: List[SkillCategory]
    allowed_side_effects: List[SideEffect]
    max_steps: int = 4
    loop_policy: LoopPolicyConfig = field(default_factory=LoopPolicyConfig)

    @classmethod
    def from_yaml(cls, data: Dict[str, Any]) -> "AgentConfig":
        """
        Create AgentConfig from a YAML dictionary.
        Loads loop_policy if present in data.
        """
        loop_policy_data = data.pop("loop_policy", None)
        loop_policy = LoopPolicyConfig(**loop_policy_data) if loop_policy_data else LoopPolicyConfig()
        
        return cls(
            **data,
            loop_policy=loop_policy,
        )


@dataclass
class ProviderConfig:
    """Configuration for a single search provider (PHASE 3.13.1).

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
    """Legacy flat search provider configuration (pre‑3.13.1).

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
    """Top-level search configuration (PHASE 3.13.1).

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
    """Configuration for embedding providers (PHASE 3.19.1).

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


@dataclass
class CoreConfig:
    llm: LLMConfig
    agent: AgentConfig
    search: SearchConfig | None = None
    embedding: EmbeddingConfig | None = None
