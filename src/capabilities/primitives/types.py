"""
Primitive types and results (Phase 3.1.2).

Re-exports ``PrimitiveType`` and ``PrimitiveResult`` from the canonical
``src.domain.primitives`` module.

This module preserves the import path for all downstream consumers
while the canonical definitions live in the ``domain`` stratum.
"""

from src.domain.primitives import PrimitiveResult, PrimitiveType  # noqa: F401
