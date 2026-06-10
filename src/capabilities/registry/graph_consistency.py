"""
Phase 3.21.4 — Capability Graph Consistency
=============================================

Pure read-only checker that validates the consistency of the registered
capability graph (primitives + skills).  No I/O, no LLM calls, no side
effects — safe to run before any execution.

Six violation kinds are checked:

1. DANGLING_PRIMITIVE   — skill declares a primitive that is not registered
2. DANGLING_SKILL       — plan references a skill that is not registered
3. SCHEMA_DRIFT         — a primitive that skills were built against is gone
4. PRIVILEGE_DRIFT      — skill gained new primitives vs its approved baseline
5. CAPABILITY_CYCLE     — recursive skill→skill dependency chain detected
6. PLUGIN_UNLOAD_UNSAFE — removing a plugin would break dependent skills

All public types are frozen dataclasses.  The checker itself is stateless;
construct one per check run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.capabilities.registry.primitive_registry import PrimitiveRegistry
    from src.capabilities.registry.skill_registry import CapabilitySkillRegistry


# ---------------------------------------------------------------------------
# Violation kind constants
# ---------------------------------------------------------------------------

DANGLING_PRIMITIVE = "dangling_primitive"
"""Skill's manifest.primitives contains a name not in PrimitiveRegistry."""

DANGLING_SKILL = "dangling_skill"
"""Plan references a skill name not found in CapabilitySkillRegistry."""

SCHEMA_DRIFT = "schema_drift"
"""A primitive present in the approved baseline is no longer registered."""

PRIVILEGE_DRIFT = "privilege_drift"
"""Skill now uses primitives not present in its approved baseline."""

CAPABILITY_CYCLE = "capability_cycle"
"""A skill→skill dependency chain forms a cycle (recursive skill use)."""

PLUGIN_UNLOAD_UNSAFE = "plugin_unload_unsafe"
"""Removing a plugin would leave dependent skills with dangling primitives."""

VALID_VIOLATION_KINDS: frozenset[str] = frozenset({
    DANGLING_PRIMITIVE,
    DANGLING_SKILL,
    SCHEMA_DRIFT,
    PRIVILEGE_DRIFT,
    CAPABILITY_CYCLE,
    PLUGIN_UNLOAD_UNSAFE,
})


# ---------------------------------------------------------------------------
# ConsistencyViolation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConsistencyViolation:
    """
    A single detected consistency problem in the capability graph.

    Attributes
    ----------
    kind:
        One of the VALID_VIOLATION_KINDS constants.
    skill_name:
        The name of the skill where the violation was detected, or an
        empty string for violations not tied to a specific skill.
    detail:
        Human-readable description of the specific problem.
    """

    kind: str
    skill_name: str
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in VALID_VIOLATION_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(VALID_VIOLATION_KINDS)}, "
                f"got {self.kind!r}"
            )
        if not self.detail:
            raise ValueError("detail must be non-empty")


# ---------------------------------------------------------------------------
# GraphConsistencyReport
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphConsistencyReport:
    """
    Result of a full capability graph consistency check.

    Attributes
    ----------
    violations:
        All detected violations, sorted by (kind, skill_name).
    """

    violations: tuple[ConsistencyViolation, ...]

    @property
    def is_clean(self) -> bool:
        """True when no violations were detected."""
        return len(self.violations) == 0

    def violations_by_kind(self, kind: str) -> tuple[ConsistencyViolation, ...]:
        """Return all violations of a specific kind."""
        return tuple(v for v in self.violations if v.kind == kind)

    def __len__(self) -> int:
        return len(self.violations)


# ---------------------------------------------------------------------------
# CapabilityGraphChecker
# ---------------------------------------------------------------------------

class CapabilityGraphChecker:
    """
    Pure read-only inspector for the registered capability graph.

    Takes a PrimitiveRegistry and a CapabilitySkillRegistry and
    exposes individual check methods plus a ``run_all()`` aggregator.

    All methods are side-effect-free and safe to call at any time.
    """

    def __init__(
        self,
        primitive_registry: "PrimitiveRegistry",
        skill_registry: "CapabilitySkillRegistry",
    ) -> None:
        self._primitives = primitive_registry
        self._skills = skill_registry

    # ------------------------------------------------------------------
    # Check 1: Dangling primitives
    # ------------------------------------------------------------------

    def check_dangling_primitives(self) -> list[ConsistencyViolation]:
        """
        Find skills whose manifest.primitives reference unregistered primitives.

        Returns one violation per (skill, missing-primitive) pair.
        """
        violations: list[ConsistencyViolation] = []
        for skill in self._skills.list():
            skill_name = skill.manifest.name
            for prim_name in skill.manifest.primitives:
                if self._primitives.get(prim_name) is None:
                    violations.append(
                        ConsistencyViolation(
                            kind=DANGLING_PRIMITIVE,
                            skill_name=skill_name,
                            detail=(
                                f"skill '{skill_name}' references primitive "
                                f"'{prim_name}' which is not registered"
                            ),
                        )
                    )
        return violations

    # ------------------------------------------------------------------
    # Check 2: Dangling skills
    # ------------------------------------------------------------------

    def check_dangling_skills(
        self, referenced_skill_names: set[str]
    ) -> list[ConsistencyViolation]:
        """
        Verify that every skill name referenced by the planner is registered.

        Parameters
        ----------
        referenced_skill_names:
            Set of skill names the planner intends to use (e.g. from a plan
            or from the planner's capability list).

        Returns one violation per missing skill name.
        """
        violations: list[ConsistencyViolation] = []
        for name in sorted(referenced_skill_names):
            if self._skills.get(name) is None:
                violations.append(
                    ConsistencyViolation(
                        kind=DANGLING_SKILL,
                        skill_name=name,
                        detail=(
                            f"skill '{name}' is referenced by the plan but "
                            f"is not registered in the skill registry"
                        ),
                    )
                )
        return violations

    # ------------------------------------------------------------------
    # Check 3: Schema drift
    # ------------------------------------------------------------------

    def check_schema_drift(
        self, baseline_primitive_names: set[str]
    ) -> list[ConsistencyViolation]:
        """
        Detect primitives that were present when skills were built but are
        now missing from the registry (renamed, removed, or replaced).

        Parameters
        ----------
        baseline_primitive_names:
            Set of primitive names that were registered when the skill set
            was last validated (e.g. loaded from a registry snapshot).

        Returns one violation per baseline primitive that is no longer
        registered.
        """
        violations: list[ConsistencyViolation] = []
        for prim_name in sorted(baseline_primitive_names):
            if self._primitives.get(prim_name) is None:
                violations.append(
                    ConsistencyViolation(
                        kind=SCHEMA_DRIFT,
                        skill_name="",
                        detail=(
                            f"primitive '{prim_name}' was in the approved "
                            f"baseline but is no longer registered — "
                            f"dependent skills may be broken"
                        ),
                    )
                )
        return violations

    # ------------------------------------------------------------------
    # Check 4: Privilege drift
    # ------------------------------------------------------------------

    def check_privilege_drift(
        self, baseline: dict[str, set[str]]
    ) -> list[ConsistencyViolation]:
        """
        Detect skills that have gained new primitive dependencies since
        their last approved baseline snapshot.

        Parameters
        ----------
        baseline:
            Mapping of skill_name → approved set of primitive names.
            Skills not in the baseline are skipped.

        Returns one violation per (skill, new-primitive) pair where the
        primitive was not in the approved baseline.
        """
        violations: list[ConsistencyViolation] = []
        for skill_name, approved_primitives in sorted(baseline.items()):
            skill = self._skills.get(skill_name)
            if skill is None:
                continue
            current_primitives = set(skill.manifest.primitives)
            new_primitives = current_primitives - approved_primitives
            for prim_name in sorted(new_primitives):
                violations.append(
                    ConsistencyViolation(
                        kind=PRIVILEGE_DRIFT,
                        skill_name=skill_name,
                        detail=(
                            f"skill '{skill_name}' now uses primitive "
                            f"'{prim_name}' which was not in the "
                            f"approved baseline"
                        ),
                    )
                )
        return violations

    # ------------------------------------------------------------------
    # Check 5: Capability cycles
    # ------------------------------------------------------------------

    def check_capability_cycles(self) -> list[ConsistencyViolation]:
        """
        Detect recursive skill→skill dependency chains.

        A skill A is considered to depend on skill B if any of A's step
        ``call`` values matches B's registered name.  This models future
        skill composition where one skill can invoke another.

        In the current primitive-only model, step calls reference
        primitives (not skills), so this check returns clean unless a
        step call value happens to match a registered skill name.

        Returns one violation per cycle detected (reporting the full
        cycle path in the detail string).
        """
        # Build skill→[depended-on-skill-names] graph
        skill_names: set[str] = {s.manifest.name for s in self._skills.list()}
        deps: dict[str, list[str]] = {}
        for skill in self._skills.list():
            skill_name = skill.manifest.name
            skill_deps: list[str] = []
            for step in skill.manifest.steps:
                call = step.get("call", "")
                if call in skill_names and call != skill_name:
                    skill_deps.append(call)
            # Also check manifest.primitives for skill-named entries
            for prim_name in skill.manifest.primitives:
                if prim_name in skill_names and prim_name != skill_name:
                    skill_deps.append(prim_name)
            deps[skill_name] = list(dict.fromkeys(skill_deps))  # dedup, preserve order

        # DFS cycle detection
        violations: list[ConsistencyViolation] = []
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def _dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            for neighbour in deps.get(node, []):
                if neighbour not in visited:
                    _dfs(neighbour, path + [neighbour])
                elif neighbour in rec_stack:
                    # Found a cycle — report the loop portion
                    cycle_start = path.index(neighbour) if neighbour in path else 0
                    cycle_path = path[cycle_start:] + [neighbour]
                    violations.append(
                        ConsistencyViolation(
                            kind=CAPABILITY_CYCLE,
                            skill_name=node,
                            detail=(
                                f"capability cycle detected: "
                                + " → ".join(cycle_path)
                            ),
                        )
                    )
            rec_stack.discard(node)

        for name in sorted(skill_names):
            if name not in visited:
                _dfs(name, [name])

        return violations

    # ------------------------------------------------------------------
    # Check 6: Plugin unload safety
    # ------------------------------------------------------------------

    def check_plugin_unload_safety(
        self, plugin_name: str
    ) -> list[ConsistencyViolation]:
        """
        Identify skills that would break if the given plugin were removed.

        A skill is affected if any of its manifest.primitives is provided
        by the given plugin (i.e. the primitive's ``plugin_name`` attribute
        matches).

        Parameters
        ----------
        plugin_name:
            The plugin whose removal is being evaluated.

        Returns one violation per affected (skill, primitive) pair.
        """
        # Find all primitives from this plugin
        plugin_primitives: set[str] = set()
        for prim in self._primitives.list():
            if getattr(prim, "plugin_name", None) == plugin_name:
                # PrimitiveBase subclasses store their name in metadata
                prim_name = getattr(prim, "name", None)
                if prim_name:
                    plugin_primitives.add(prim_name)

        if not plugin_primitives:
            return []

        violations: list[ConsistencyViolation] = []
        for skill in self._skills.list():
            skill_name = skill.manifest.name
            for prim_name in skill.manifest.primitives:
                if prim_name in plugin_primitives:
                    violations.append(
                        ConsistencyViolation(
                            kind=PLUGIN_UNLOAD_UNSAFE,
                            skill_name=skill_name,
                            detail=(
                                f"removing plugin '{plugin_name}' would "
                                f"unregister primitive '{prim_name}' "
                                f"which skill '{skill_name}' depends on"
                            ),
                        )
                    )
        return violations

    # ------------------------------------------------------------------
    # run_all
    # ------------------------------------------------------------------

    def run_all(
        self,
        referenced_skill_names: set[str] | None = None,
        baseline_primitive_names: set[str] | None = None,
        baseline_privileges: dict[str, set[str]] | None = None,
        plugin_name: str | None = None,
    ) -> GraphConsistencyReport:
        """
        Run all applicable checks and return a consolidated report.

        Parameters
        ----------
        referenced_skill_names:
            If provided, also runs ``check_dangling_skills()``.
        baseline_primitive_names:
            If provided, also runs ``check_schema_drift()``.
        baseline_privileges:
            If provided, also runs ``check_privilege_drift()``.
        plugin_name:
            If provided, also runs ``check_plugin_unload_safety()``.

        Returns
        -------
        GraphConsistencyReport
            All violations found, sorted by (kind, skill_name).
        """
        all_violations: list[ConsistencyViolation] = []
        all_violations.extend(self.check_dangling_primitives())
        all_violations.extend(self.check_capability_cycles())

        if referenced_skill_names is not None:
            all_violations.extend(
                self.check_dangling_skills(referenced_skill_names)
            )
        if baseline_primitive_names is not None:
            all_violations.extend(
                self.check_schema_drift(baseline_primitive_names)
            )
        if baseline_privileges is not None:
            all_violations.extend(
                self.check_privilege_drift(baseline_privileges)
            )
        if plugin_name is not None:
            all_violations.extend(
                self.check_plugin_unload_safety(plugin_name)
            )

        sorted_violations = tuple(
            sorted(all_violations, key=lambda v: (v.kind, v.skill_name))
        )
        return GraphConsistencyReport(violations=sorted_violations)
