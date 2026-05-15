from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class LLMConfig:
    model: str
    temperature: float = 0.0
    max_tokens: int = 4096
    request_timeout: float = 30.0 # seconds
    retries: int = 2


@dataclass
class TimeoutConfig:
    step_timeout: float = 20.0 # per LLM/tool step
    loop_timeout: float = 120.0 # entire loop
    tool_timeout: float = 15.0 # per tool execution


@dataclass
class LimitConfig:
    max_steps: int = 12
    max_errors: int = 3
    max_history_tokens: int = 8000


@dataclass
class SkillPathConfig:
    standard: str = "src/skills/standard"
    custom: str = "src/skills/custom" # gitignored, injected at deploy
    plugins: Optional[str] = None # future plugin system


@dataclass
class FetchConfig:
    default_mode: str = "auto"
    allowed_domains: List[str] = field(default_factory=list)
    blocked_domains: List[str] = field(default_factory=list)
    max_response_size: int = 2_000_000 # bytes
    browser_enabled: bool = True
    stealth_enabled: bool = False # opt‑in only


@dataclass
class WorkerConfig:
    concurrency: int = 4
    heavy_pool_size: int = 1
    heartbeat_interval: float = 5.0
    job_timeout: float = 90.0


@dataclass
class CoreConfig:
    llm: LLMConfig
    timeouts: TimeoutConfig = TimeoutConfig()
    limits: LimitConfig = LimitConfig()
    skill_paths: SkillPathConfig = SkillPathConfig()
    fetch: FetchConfig = FetchConfig()
    workers: WorkerConfig = WorkerConfig()

    @staticmethod
    def load_from_env() -> "CoreConfig":
        # TODO: Step 1.1 — implement env‑based loading
        return CoreConfig(
            llm=LLMConfig(model="gpt-4o-mini")
        )