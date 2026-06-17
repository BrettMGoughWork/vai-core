"""
PrimitiveBase — abstract base class for all S3 primitives (Phase 3.1.1).

Re-exports ``PrimitiveBase``, ``PrimitiveType``, and ``PrimitiveResult``
from the canonical ``src.domain.primitives`` module.

This module preserves the import path for all 80+ concrete primitives
while the canonical definitions live in the ``domain`` stratum.
"""

from src.domain.primitives import PrimitiveBase, PrimitiveResult, PrimitiveType  # noqa: F401
