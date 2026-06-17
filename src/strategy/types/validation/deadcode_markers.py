"""
Re-exports ``deadcode_ignore`` and ``DeadCodeIgnore`` from the canonical
``src.domain._markers`` module.

This module preserves the import path for all ~90 consumers while the
canonical definitions live in the ``domain`` stratum.
"""

from src.domain._markers import DeadCodeIgnore, deadcode_ignore  # noqa: F401