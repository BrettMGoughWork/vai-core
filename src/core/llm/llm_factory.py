from .providers import (
    OpenAIClient, AnthropicClient, GeminiClient, MistralClient, QwenClient, DeepSeekClient
)
from .mock_llm import MockLLM

PROVIDER_CLIENTS = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "gemini": GeminiClient,
    "mistral": MistralClient,
    "qwen": QwenClient,
    "deepseek": DeepSeekClient,
    "mock": MockLLM,
}

from types import SimpleNamespace

def create(provider_name: str, model: str, **kwargs):
    """
    Factory for LLM provider clients.
    Args:
        provider_name (str): Provider key (e.g., 'openai', 'anthropic')
        model (str): Model name (passed to client)
        **kwargs: Additional config for the client
    Returns:
        ChatProvider instance
    """
    provider_name = provider_name.lower()
    client_cls = PROVIDER_CLIENTS.get(provider_name)
    if not client_cls:
        raise ValueError(f"Unknown provider: {provider_name}. Available: {list(PROVIDER_CLIENTS.keys())}")
    import inspect
    sig = inspect.signature(client_cls.__init__)
    # Remove 'self' and only keep accepted kwargs
    accepted_args = set(sig.parameters.keys()) - {"self"}
    # Always pass model if accepted
    call_kwargs = {k: v for k, v in kwargs.items() if k in accepted_args}
    if "model" in accepted_args:
        call_kwargs["model"] = model
    return client_cls(**call_kwargs)

factory = SimpleNamespace(create=create)
