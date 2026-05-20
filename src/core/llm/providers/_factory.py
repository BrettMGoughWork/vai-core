# src/core/llm/providers/factory.py
from __future__ import annotations

from collections import defaultdict
from typing import Type, Any


class ProviderFactory:
    def __init__(self):
        self._registry: dict[str, Type] = {}

    def register(self, name: str, base_class):
        """Decorator to register a provider class."""
        def decorator(cls):
            if name in self._registry:
                raise ValueError(f"Provider '{name}' is already registered.")
            self._registry[name] = cls
            return cls
        return decorator

    def get(self, name: str):
        """Get a registered provider class by name."""
        if name not in self._registry:
            raise KeyError(f"No provider registered for '{name}'")
        return self._registry[name]

    def list_providers(self) -> list[str]:
        return list(self._registry.keys())

    def create(self, provider_name: str, **kwargs):
        """Create a provider instance, filtering kwargs to only what the class accepts."""
        cls = self.get(provider_name)

        # Get the __init__ signature to avoid passing unknown arguments
        import inspect
        sig = inspect.signature(cls.__init__)
        valid_params = set(sig.parameters.keys()) - {'self'}

        # Filter kwargs to only valid parameters
        clean_kwargs = {k: v for k, v in kwargs.items() if k in valid_params}

        return cls(**clean_kwargs)


# Global singleton
factory = ProviderFactory()