"""
OpenAI embedding provider (PHASE 3.19.1).

Calls OpenAI's ``text-embedding-3-small`` (or any configured model)
via the ``openai`` package already in requirements.txt.
"""

from __future__ import annotations

import os


class OpenAIEmbeddingProvider:
    """Embedding provider backed by OpenAI's embedding API."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        api_key_env: str | None = None,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._api_key_env = api_key_env or "OPENAI_API_KEY"

    def embed(self, text: str) -> list[float]:
        """Return a semantic embedding vector for *text* from OpenAI."""
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAI embeddings. "
                "Install with: pip install openai"
            ) from exc

        api_key = os.getenv(self._api_key_env)
        if not api_key:
            raise ValueError(
                f"{self._api_key_env} environment variable is not set. "
                "Set it to use OpenAI embeddings."
            )

        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding
