"""
StepSpec — versioned, deterministic step contract (Phase 2.15.2).

Each step in a plan is described by a StepSpec before execution.
This is the planning-time contract that the executor consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


CURRENT_STEP_SPEC_VERSION = "1.0"


@dataclass(frozen=True)
class StepSpec:
    """Deterministic, versioned step contract.

    Describes a single step in a plan before it reaches the executor.
    This is a planning artifact — it does not carry execution state
    (that's ``StepState``).

    Fields:
        intent: Natural-language description of what this step does.
        args: Input arguments for the step (keyed by parameter name).
        target_skill: Optional skill name if the planner identified one.
            May be ``None`` if discovery will resolve it at execution time.
        expected_output: Optional schema hint for what this step produces.
            Used for output forwarding between steps.
        fallback_strategies: Optional list of fallback skill names in
            preference order. Empty means no fallback is planned.
        version: Contract version string.
    """

    intent: str
    args: Dict[str, Any] = field(default_factory=dict)

    target_skill: str | None = None
    expected_output: Dict[str, Any] | None = None
    fallback_strategies: List[str] = field(default_factory=list)

    version: str = CURRENT_STEP_SPEC_VERSION

    def __post_init__(self) -> None:
        if not self.intent:
            raise ValueError("intent must be non-empty")
        if not isinstance(self.args, dict):
            raise ValueError("args must be a dict")
        if not self.version:
            raise ValueError("version must be non-empty")

    # ── Serialization ──

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d: Dict[str, Any] = {
            "intent": self.intent,
            "version": self.version,
        }
        if self.args:
            d["args"] = self.args
        if self.target_skill is not None:
            d["target_skill"] = self.target_skill
        if self.expected_output is not None:
            d["expected_output"] = self.expected_output
        if self.fallback_strategies:
            d["fallback_strategies"] = self.fallback_strategies
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StepSpec":
        """Deserialize from a dict produced by ``to_dict()``."""
        return cls(
            intent=d["intent"],
            args=d.get("args", {}),
            target_skill=d.get("target_skill"),
            expected_output=d.get("expected_output"),
            fallback_strategies=d.get("fallback_strategies", []),
            version=d.get("version", CURRENT_STEP_SPEC_VERSION),
        )

    # ── Construction from LLM step dict ──

    @classmethod
    def from_llm_step(
        cls,
        step: Dict[str, Any],
        *,
        target_skill: str | None = None,
        expected_output: Dict[str, Any] | None = None,
    ) -> "StepSpec":
        """Construct a StepSpec from an LLM-produced step dictionary.

        The LLM step dict is expected to have:
        - ``description`` or ``intent``: step intent string
        - ``inputs`` or ``args``: step arguments
        - ``capability``: optional target skill name
        """
        intent = step.get("description") or step.get("intent", "")
        args = step.get("inputs") or step.get("args", {})
        skill = step.get("capability") or target_skill
        return cls(
            intent=intent,
            args=args,
            target_skill=skill,
            expected_output=expected_output,
        )

    # ── Properties ──

    @property
    def has_fallback(self) -> bool:
        """True if at least one fallback strategy is defined."""
        return len(self.fallback_strategies) > 0

    @property
    def has_target_skill(self) -> bool:
        """True if a specific skill was targeted by the planner."""
        return self.target_skill is not None
