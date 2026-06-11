import yaml
from pathlib import Path
from src.strategy.state.config import (
    AgentConfig,
    CoreConfig,
    EmbeddingConfig,
    LLMConfig,
    LoopPolicyConfig,
    SearchConfig,
)
from ..llm.builder import create_llm_transport

class Config:
    def __init__(self, path="config/config.yaml"):
        path = Path(path)
        with open(path, "r") as f:
            raw = yaml.safe_load(f)

        # hydrate LLM config
        raw_llm = raw.get("llm", {})
        llm = LLMConfig(**raw_llm)

        # hydrate Agent config
        raw_agent = raw.get("agent", {})
        agent = AgentConfig.from_yaml(raw_agent)

        # hydrate Search config (PHASE 3.13.1)
        raw_search = raw.get("search")
        search = SearchConfig.from_yaml(raw_search) if raw_search else None

        # hydrate Embedding config (PHASE 3.19.1)
        raw_embedding = raw.get("embedding")
        embedding = EmbeddingConfig.from_yaml(raw_embedding) if raw_embedding else None

        # store fully typed config
        self._config = CoreConfig(
            llm=llm,
            agent=agent,
            search=search,
            embedding=embedding,
        )

    def get(self, section: str):
        """Get a specific config section, optionally by alias."""
        return getattr(self._config, section, None)
