from __future__ import annotations
from typing import Any

from .transport import LLMTransport
from .llm_factory import factory

from src.strategy.state.config import LLMConfig

def create_llm_transport(llm_config: LLMConfig) -> LLMTransport:
    """
    Create an LLMTransport using the unified config.yaml structure.

    Expected llm_config structure:

    llm:
      provider: deepseek
      model: deepseek-chat
      temperature: 0
      max_tokens: 2000
    """
    client = factory.create(
        provider_name=llm_config.provider,
        model=llm_config.model, # still passed for providers that accept it
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens,
    )

    return LLMTransport(
        client=client,
        model=llm_config.model,
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens,
    )