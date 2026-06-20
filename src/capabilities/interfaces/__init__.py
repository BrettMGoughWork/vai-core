"""
Capabilities Stratum — Integration Interfaces
==============================================

Canonical re-exports of the Capabilities stratum's contracts.
"""

from __future__ import annotations

from src.capabilities.contracts import (
    SkillCallRequest as SkillCallRequest,
    SkillResult as SkillResult,
)

__all__ = [
    "SkillCallRequest",
    "SkillResult",
]
