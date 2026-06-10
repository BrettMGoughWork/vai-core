"""
Registry snapshots (Phase 3.15.3).

Produces deterministic, hash-addressed snapshots of the combined
primitive + skill registries.  Identical plugin sets always yield
identical snapshot IDs, enabling S2 to detect state changes without
byte-for-byte comparison of the registries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.skills.skill import CapabilitySkill
    from src.capabilities.primitives.base import PrimitiveBase


# ── Data types ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class RegistrySnapshot:
    """Immutable snapshot of the combined registry state.

    *snapshot_id* is the SHA-256 of the canonical JSON representation
    of both registries, sorted deterministically.  Two snapshots with
    the same ID are guaranteed to represent identical registry states.
    """

    snapshot_id: str
    skills: list[CapabilitySkill] = field(repr=False)
    primitives: list[PrimitiveBase] = field(repr=False)

    def __hash__(self) -> int:
        return hash(self.snapshot_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RegistrySnapshot):
            return NotImplemented
        return self.snapshot_id == other.snapshot_id


# ── Snapshot Manager ─────────────────────────────────────────────────


class SnapshotManager:
    """Creates, stores, and compares registry snapshots.

    A *change_callback* is invoked whenever the snapshot changes,
    giving S2 a hook to switch to a new snapshot at a safe boundary.
    The previous snapshot remains available via :meth:`current` until
    the next call to :meth:`capture`.
    """

    def __init__(
        self,
        change_callback: Callable[[RegistrySnapshot], None] | None = None,
    ) -> None:
        self._current: RegistrySnapshot | None = None
        self._previous_snapshots: dict[str, RegistrySnapshot] = {}
        self._change_callback = change_callback

    # ── capture ──────────────────────────────────────────────────

    def capture(
        self,
        skills: list[CapabilitySkill],
        primitives: list[PrimitiveBase],
    ) -> RegistrySnapshot:
        """Build a fresh snapshot from the given registry contents.

        The lists MUST be sorted deterministically by the caller (use
        ``CapabilitySkillRegistry.ordered_list()`` and a similarly
        sorted primitive list).

        Returns the new snapshot.
        """
        snapshot_id = _compute_snapshot_id(skills, primitives)
        snapshot = RegistrySnapshot(
            snapshot_id=snapshot_id,
            skills=skills,
            primitives=primitives,
        )

        previously = self._current
        self._current = snapshot
        if previously is not None:
            self._previous_snapshots[previously.snapshot_id] = previously

        # Notify if changed
        if (
            self._change_callback is not None
            and (previously is None or snapshot.snapshot_id != previously.snapshot_id)
        ):
            self._change_callback(snapshot)

        return snapshot

    # ── accessors ────────────────────────────────────────────────

    @property
    def current(self) -> RegistrySnapshot | None:
        """The most recently captured snapshot, or *None*."""
        return self._current

    def get(self, snapshot_id: str) -> RegistrySnapshot | None:
        """Retrieve a previously stored snapshot by ID, or *None*."""
        if self._current is not None and self._current.snapshot_id == snapshot_id:
            return self._current
        return self._previous_snapshots.get(snapshot_id)


# ── Internal helpers ─────────────────────────────────────────────────


def _compute_snapshot_id(
    skills: list[CapabilitySkill],
    primitives: list[PrimitiveBase],
) -> str:
    """SHA-256 of the canonical JSON representation of both lists.

    The lists must be pre-sorted by the caller.  Skill entries use a
    stable subset of fields (name, description, plugin_name,
    plugin_version, manifest_hash, steps).  Primitive entries use
    (name, description, primitive_type, plugin_name, plugin_version).
    """
    skill_entries: list[dict] = []
    for s in skills:
        m = s.manifest
        skill_entries.append({
            "name": m.name,
            "description": m.description,
            "plugin_name": m.plugin_name,
            "plugin_version": m.plugin_version,
            "manifest_hash": m.manifest_hash,
            "steps": m.steps,
        })

    primitive_entries: list[dict] = []
    for p in primitives:
        primitive_entries.append({
            "name": p.name,
            "description": p.description,
            "primitive_type": p.primitive_type,
            "plugin_name": getattr(p, "plugin_name", None),
            "plugin_version": getattr(p, "plugin_version", None),
        })

    canonical = {
        "skills": skill_entries,
        "primitives": primitive_entries,
    }
    json_bytes = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(json_bytes).hexdigest()
