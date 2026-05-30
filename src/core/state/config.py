from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict

from src.primitives.runtime.categories import SkillCategory
from src.primitives.runtime.side_effects import SideEffect


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
class CoreConfig:
    llm: LLMConfig
    agent: AgentConfig
