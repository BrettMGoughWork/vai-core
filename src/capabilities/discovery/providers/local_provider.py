"""
Local embedding provider (PHASE 3.19.1).

Uses a local ``sentence-transformers`` model (e.g. MiniLM-L6-v2)
for offline, zero-cost embeddings.  Models are downloaded into the
gitignored ``.models/`` directory at the project root on first use.

Falls back to the mock provider if ``sentence-transformers`` is not
installed.
"""

from __future__ import annotations

import os
from pathlib import Path


def _models_dir() -> str:
    """Return the absolute path to the gitignored .models/ directory."""
    # Walk up from this file to find the project root (where .git lives)
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / ".git").exists():
            break
        current = current.parent
    models = current / ".models"
    models.mkdir(exist_ok=True)
    return str(models)


class LocalEmbeddingProvider:
    """Embedding provider backed by a local sentence-transformers model.

    Models are auto-downloaded into ``.models/`` (gitignored) on first use.
    """

    _model_instance = None

    def __init__(self, model: str = "all-MiniLM-L6-v2", dimensions: int = 384) -> None:
        self._model_name = model
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """Return a semantic embedding vector for *text* via local model."""
        if self.__class__._model_instance is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                import warnings
                warnings.warn(
                    "sentence-transformers not installed; "
                    "returning zero-vector embeddings. "
                    "Install with: pip install sentence-transformers"
                )
                return [0.0] * self._dimensions

            cache = _models_dir()
            os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", cache)
            self.__class__._model_instance = SentenceTransformer(
                self._model_name, cache_folder=cache
            )

        vector = self.__class__._model_instance.encode(text)
        return vector.tolist()
