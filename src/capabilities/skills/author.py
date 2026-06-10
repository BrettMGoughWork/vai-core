"""
Agent-authored skill pipeline (Phase 3.16.1 / 3.16.3).

Provides ``SkillAuthor`` — the entry point for LLM-authored skills.
Accepts raw ``.skill.md`` text content, parses it, validates it
through the safety gate, and registers it in the capability registry.

Usage::

    from src.capabilities.skills.author import SkillAuthor

    author = SkillAuthor(
        primitive_registry=prim_reg,
        skill_registry=skill_reg,
        safety_validator=safety,
    )
    skill = author.author_skill(raw_markdown_text, plugin_name="agent")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.capabilities.skills.manifest import SkillManifest
from src.capabilities.skills.skill import CapabilitySkill

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry
    from src.capabilities.registry.skill_safety import SkillSafetyValidator


class SkillAuthor:
    """Pipeline for agent-authored skill creation and registration.

    Accepts raw ``.skill.md`` text, parses, validates, registers,
    and optionally captures a registry snapshot.
    """

    def __init__(
        self,
        primitive_registry: PrimitiveRegistry,
        skill_registry: CapabilitySkillRegistry,
        safety_validator: SkillSafetyValidator,
    ) -> None:
        self._primitive_registry = primitive_registry
        self._skill_registry = skill_registry
        self._safety_validator = safety_validator

    def author_skill(
        self,
        raw_text: str,
        *,
        plugin_name: str = "agent",
        plugin_version: str = "0.1.0",
        skip_sandbox: bool = False,
        quarantine: bool = True,
    ) -> CapabilitySkill:
        """Parse, validate, sandbox, and register an agent-authored skill.

        This is the complete pipeline:

        1. Parse ``raw_text`` into a ``SkillManifest``.
        2. Build a ``CapabilitySkill`` with resolved primitives.
        3. Run through ``SkillSafetyValidator`` (structural + semantic).
        4. Execute in ``SkillSandbox`` with mock primitives (3.17.3).
        5a. If ``quarantine=True`` (default): place in quarantine for
            human governance approval.
        5b. If ``quarantine=False``: register directly in the active
            registry (auto-embeds if embedder is configured).
        6. Optionally capture a registry snapshot for hot-reload.

        Args:
            raw_text: Full text content of a ``.skill.md`` file.
            plugin_name: Origin label for this skill (default ``"agent"``).
            plugin_version: Version string for provenance tracking.
            skip_sandbox: If ``True``, skip the behavioural sandbox check
                          (useful for trusted hand-authored skills).
            quarantine: If ``True`` (default), route to quarantine instead
                        of direct registration.  Agent-authored skills
                        should always be quarantined.

        Returns:
            The fully built ``CapabilitySkill`` (may be quarantined).

        Raises:
            ValueError: If parsing, validation, safety, or sandbox checks fail.
        """
        # ── 1. Parse ───────────────────────────────────────────────────
        from src.capabilities.skills.skill_parser import parse_skill_text

        parsed = parse_skill_text(raw_text, self._primitive_registry)

        # ── 2. Build Manifest ──────────────────────────────────────────
        manifest_data: dict[str, Any] = {
            "name": parsed["name"],
            "description": parsed["description"],
            "primitives": [p.name for p in parsed["primitives"]],
            "inputs": parsed["inputs"],
            "plugin_name": plugin_name,
            "plugin_version": plugin_version,
        }

        # Use parsed steps if present, otherwise derive from outputs.
        parsed_steps = parsed.get("steps")
        if parsed_steps is not None:
            manifest_data["steps"] = parsed_steps
        else:
            manifest_data["steps"] = _extract_steps_from_outputs(
                parsed.get("outputs", {})
            )

        # Merge outputs if present
        outputs = parsed.get("outputs", {})
        if isinstance(outputs, dict) and outputs:
            manifest_data["outputs"] = outputs

        manifest = SkillManifest.from_dict(manifest_data)

        # ── 3. Build CapabilitySkill ───────────────────────────────────
        skill = CapabilitySkill.from_manifest(manifest, self._primitive_registry)

        # ── 4. Safety validation ───────────────────────────────────────
        result = self._safety_validator.validate(skill)
        if not result.passed:
            raise ValueError(
                f"Skill '{skill.manifest.name}' failed safety validation: "
                + "; ".join(result.errors)
            )

        # ── 5. Behavioural sandbox (3.17.3) ─────────────────────────────
        if not skip_sandbox:
            from src.capabilities.skills.sandbox import SkillSandbox

            sandbox = SkillSandbox(self._primitive_registry)
            test_inputs = SkillSandbox.generate_mock_inputs(skill.input_schema)
            sandbox_report = sandbox.run(skill, test_inputs)
            if not sandbox_report.passed:
                warning_detail = "; ".join(sandbox_report.warnings)
                raise ValueError(
                    f"Skill '{skill.manifest.name}' failed sandbox: {warning_detail}"
                )

        # ── 6. Register or quarantine ────────────────────────────────────
        if quarantine:
            from datetime import datetime, timezone

            from src.capabilities.registry.quarantine import ProvenanceRecord

            safety_errors = result.errors if not result.passed else []
            provenance = ProvenanceRecord(
                author=plugin_name,
                created_at=datetime.now(timezone.utc),
                plugin_name=plugin_name,
                plugin_version=plugin_version,
                sandbox_passed=not skip_sandbox,  # False if skipped
                safety_errors=safety_errors,
            )
            self._skill_registry.quarantine_skill(
                skill, provenance, reason="agent-authored"
            )
        else:
            self._skill_registry.register(skill)

        # ── 7. Snapshot (if available) ─────────────────────────────────
        self._capture_snapshot()

        return skill

    def _capture_snapshot(self) -> None:
        """Capture a registry snapshot if the SnapshotManager singleton exists."""
        try:
            from src.capabilities.registry.snapshot import SnapshotManager
        except ImportError:
            return

        if not hasattr(SnapshotManager, "get_instance"):
            return
        manager = SnapshotManager.get_instance()
        if manager is not None:
            manager.capture()


def _extract_steps_from_outputs(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract a minimal ``steps`` list from parsed outputs if none provided.

    When parsing via ``parse_skill_text``, the raw manifest might not
    include an explicit ``steps`` key.  In that case we produce a
    single return-step that surfaces the configured outputs.
    """
    if not outputs:
        return []
    return [{"return": outputs}]
