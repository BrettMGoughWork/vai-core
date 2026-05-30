from __future__ import annotations
from dataclasses import dataclass

# -----------------------------
# LLM CONFIG
# -----------------------------
@dataclass
class LLMConfig:
    provider: str
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096

# -----------------------------
# LOOP POLICY CONFIG
# -----------------------------
@dataclass
class LoopPolicyConfig:
    max_steps: int
    per_step_timeout: int
    max_wall_time: int

# -----------------------------
# AGENT CONFIG
# -----------------------------
@dataclass
class AgentConfig:
    loop_policy: LoopPolicyConfig

# -----------------------------
# ROOT CONFIG
# -----------------------------
@dataclass
class CoreConfig:
    llm: LLMConfig
    agent: AgentConfig
