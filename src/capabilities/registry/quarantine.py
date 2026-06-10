"""
Skill quarantine and governance (Phase 3.17.4).

Agent-authored skills are not immediately trusted.  After passing
structural, semantic, and sandbox checks they are placed into a
*quarantine* — a parallel registry that is invisible to normal
discovery.  A human (or automated governance agent) must explicitly
approve or reject the skill before it enters the active registry.

Key types:

``SkillQuarantine``
    Dataclass representing one quarantined skill with provenance.

``SkillQuarantineManager``
    Manages the quarantine list and approval/rejection workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill


@dataclass
class ProvenanceRecord:
    """Tracks who created a skill and when."""

    author: str
    """Identity of the author (agent ID, plugin name, or user)."""

    created_at: datetime
    """UTC timestamp when the skill was authored."""

    plugin_name: str = ""
    """Origin plugin label."""

    plugin_version: str = "0.0.0"
    """Origin plugin version."""

    sandbox_passed: bool = False
    """``True`` if the skill passed the behavioural sandbox."""

    safety_errors: list[str] = field(default_factory=list)
    """Safety validation errors found (empty = passed)."""

    approved_at: datetime | None = None
    """UTC timestamp of approval, if any."""

    rejected_at: datetime | None = None
    """UTC timestamp of rejection, if any."""


@dataclass
class SkillQuarantine:
    """A skill held in quarantine awaiting governance approval."""

    skill: "CapabilitySkill"
    """The quarantined skill."""

    provenance: ProvenanceRecord
    """Metadata about the skill's origin and review status."""

    quarantine_reason: str = ""
    """Why this skill was quarantined (e.g. \"agent-authored\")."""

    @property
    def is_pending(self) -> bool:
        """``True`` if the skill has not been approved or rejected."""
        return (
            self.provenance.approved_at is None
            and self.provenance.rejected_at is None
        )

    @property
    def is_approved(self) -> bool:
        """``True`` if the skill was approved."""
        return self.provenance.approved_at is not None

    @property
    def is_rejected(self) -> bool:
        """``True`` if the skill was rejected."""
        return self.provenance.rejected_at is not None


class SkillQuarantineManager:
    """Governs the lifecycle of quarantined agent-authored skills.

    Quarantined skills are stored in a dedicated ``_quarantine`` dict
    and are **never** visible to the main registry's ``get()``,
    ``find()``, or ``ordered_list()`` calls.

    Usage::

        mgr = SkillQuarantineManager()
        mgr.quarantine(skill, provenance)
        # ...
        pending = mgr.list_pending()
        mgr.approve("skill-name")
    """

    def __init__(self) -> None:
        self._quarantine: dict[str, SkillQuarantine] = {}

    # ── Quarantine ──────────────────────────────────────────────────────

    def quarantine(
        self,
        skill: "CapabilitySkill",
        provenance: ProvenanceRecord,
        *,
        reason: str = "agent-authored",
    ) -> SkillQuarantine:
        """Place *skill* into quarantine.

        Args:
            skill: The skill to quarantine.
            provenance: Origin and traceability metadata.
            reason: Human-readable reason for quarantine.

        Returns:
            The ``SkillQuarantine`` record.

        Raises:
            ValueError: If a skill with the same name is already quarantined.
        """
        name = skill.manifest.name
        if name in self._quarantine and self._quarantine[name].is_pending:
            raise ValueError(f"skill '{name}' is already in quarantine")
        record = SkillQuarantine(skill=skill, provenance=provenance, quarantine_reason=reason)
        self._quarantine[name] = record
        return record

    # ── Quarantine listing ──────────────────────────────────────────────

    def list_pending(self) -> list[SkillQuarantine]:
        """Return all quarantined skills still awaiting review."""
        return [q for q in self._quarantine.values() if q.is_pending]

    def list_all(self) -> list[SkillQuarantine]:
        """Return every quarantined skill regardless of status."""
        return list(self._quarantine.values())

    def get(self, name: str) -> SkillQuarantine | None:
        """Get a quarantined skill by name, or ``None``."""
        return self._quarantine.get(name)

    def count(self) -> int:
        """Return the number of pending quarantined skills."""
        return len(self.list_pending())

    # ── Governance ──────────────────────────────────────────────────────

    def approve(self, name: str) -> "CapabilitySkill":
        """Approve a quarantined skill, marking it ready for registration.

        Returns:
            The skill (still needs explicit ``register()`` call by caller).

        Raises:
            ValueError: If the skill is not in quarantine.
        """
        record = self._quarantine.get(name)
        if record is None:
            raise ValueError(f"skill '{name}' not in quarantine")
        if not record.is_pending:
            raise ValueError(f"skill '{name}' is not in a pending state")
        record.provenance.approved_at = datetime.now(timezone.utc)
        return record.skill

    def reject(self, name: str, *, reason: str = "rejected by governance") -> None:
        """Reject a quarantined skill.

        Raises:
            ValueError: If the skill is not in quarantine.
        """
        record = self._quarantine.get(name)
        if record is None:
            raise ValueError(f"skill '{name}' not in quarantine")
        if not record.is_pending:
            raise ValueError(f"skill '{name}' is not in a pending state")
        record.provenance.rejected_at = datetime.now(timezone.utc)
        record.quarantine_reason = reason

    def remove(self, name: str) -> None:
        """Permanently remove a quarantined skill.

        Useful for cleanup after approval (skill moved to active registry)
        or rejection (no longer needed).

        Raises:
            ValueError: If the skill is not in quarantine.
        """
        if name not in self._quarantine:
            raise ValueError(f"skill '{name}' not in quarantine")
        del self._quarantine[name]
