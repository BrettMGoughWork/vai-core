"""
Capabilities Stratum — Integration Interfaces
==============================================

Canonical re-exports of the Capabilities stratum's contracts.

The Capabilities stratum owns:
- Skill invocation types (SkillCallRequest, SkillResult)
- SkillRunner (the pure orchestration interface for skills)
"""

from __future__ import annotations

# ── Skill Contract ────────────────────────────────────────────────────────

from src.capabilities.contracts import (
    SkillCallRequest as SkillCallRequest,
    SkillResult as SkillResult,
)

from src.capabilities.runtime.skill_runner import (
    SkillRunner as SkillRunner,
)

__all__ = [
    "SkillCallRequest",
    "SkillResult",
    "SkillRunner",
]
