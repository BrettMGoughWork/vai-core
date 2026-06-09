import yaml
from pathlib import Path
from src.core.state.config import LoopPolicyConfig, AgentConfig, CoreConfig, LLMConfig, SearchConfig
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

        # store fully typed config
        self._config = CoreConfig(
            llm=llm,
            agent=agent,
            search=search,
        )

    def get(self, section: str):
        """Get a specific config section, optionally by alias."""
        return getattr(self._config, section, None)
