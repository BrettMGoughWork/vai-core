"""
Phase 2.8.1 — Semantic Validator
================================

Pure, deterministic function that evaluates whether a segment's output is
meaningfully aligned with four validation targets:

1. **Step description** — does the output satisfy what the step asked for?
2. **Plan intent** — does the output align with the high‑level plan direction?
3. **Subgoal goal** — does the output move toward the subgoal target state?
4. **Memory context** — does the output contradict known facts?

All checks are **heuristic‑only** (keyword matching, structural inspection).
No LLM calls, no side effects, no mutations of inputs.

Mismatch types are emitted in deterministic order:
``step_mismatch``, ``plan_mismatch``, ``subgoal_mismatch``, ``memory_mismatch``.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.core.memory.plan_memory_types import PlanMemoryRecord
from src.core.memory.segment_memory_types import SegmentMemoryRecord
from src.core.memory.subgoal_memory_types import SubgoalMemoryRecord
from src.core.planning.agent_loop.agent_loop_types import MemorySnapshot
from src.core.planning.drift.semantic_signal_types import SemanticMismatch
from src.core.planning.models.plan import Plan
from src.core.types.plan_segment import PlanSegment
from src.core.types.subgoal import Subgoal


_MEMORY_SUCCESS_KEYWORDS = frozenset({
    "success", "succeeded", "completed", "ok", "passed", "resolved",
})

# Words that suggest the intent expects a positive/successful outcome
_POSITIVE_INTENT_KEYWORDS = frozenset({
    "create", "return", "produce", "generate", "fetch", "get",
    "retrieve", "build", "construct", "compute", "calculate",
    "resolve", "solve", "complete", "finish", "execute",
})

# Words in output that suggest a negative/error outcome
_NEGATIVE_OUTPUT_KEYWORDS = frozenset({
    "error", "fail", "failed", "failure", "not_found",
    "missing", "invalid", "denied", "rejected", "aborted",
    "timeout", "exception", "empty", "null", "none",
})

# Keys in a dict output that suggest a negative outcome
_NEGATIVE_OUTPUT_KEYS = frozenset({
    "error", "errors", "exception", "fail", "failure",
    "status_code", "detail",
})

# Words in memory facts that suggest a prior success
_MEMORY_SUCCESS_KEYWORDS = frozenset({
    "success", "succeeded", "completed", "ok", "passed", "resolved",
})


def _is_negative_output(output: Any) -> bool:
    """Heuristic: does the output signal a failure or error?"""
    if isinstance(output, dict):
        # Check for explicit success: false
        if output.get("success") is False:
            return True
        if output.get("ok") is False:
            return True
        # Check for error keys
        if any(k in output for k in _NEGATIVE_OUTPUT_KEYS):
            return True
        # Check string values for negative keywords
        for val in output.values():
            if isinstance(val, str):
                lower = val.lower()
                if any(kw in lower for kw in _NEGATIVE_OUTPUT_KEYWORDS):
                    return True
    if isinstance(output, str):
        lower = output.lower()
        if any(kw in lower for kw in _NEGATIVE_OUTPUT_KEYWORDS):
            return True
    return False


def _intent_expects_positive(text: str) -> bool:
    """Heuristic: does the intent text imply a successful outcome?"""
    lower = text.lower()
    return any(kw in lower for kw in _POSITIVE_INTENT_KEYWORDS)


def _keyword_contradiction(text_a: str, text_b: str) -> List[str]:
    """Return keywords in text_a that contradict direction in text_b."""
    contradictions: List[str] = []
    lower_a = text_a.lower()
    lower_b = text_b.lower()
    for kw in _NEGATIVE_OUTPUT_KEYWORDS:
        if kw in lower_a and kw not in lower_b:
            contradictions.append(kw)
    return contradictions


def _output_has_expected_fields(
    output: Any, expected_keys: List[str]
) -> bool:
    """Check if a dict output contains all expected keys."""
    if not isinstance(output, dict):
        return False
    return all(k in output for k in expected_keys)


def _output_fields_empty(output: Any, keys: List[str]) -> List[str]:
    """Return which expected keys have empty/falsy values."""
    if not isinstance(output, dict):
        return keys
    return [
        k for k in keys
        if k in output and not output[k]
    ]


def _extract_expected_keys_from_description(description: str) -> List[str]:
    """
    Extract field names likely expected in output from a step description.
    Looks for quoted strings or camelCase/snake_case identifiers that
    appear near verbs like "return", "emit", "include", "with".
    """
    import re
    # Match quoted strings (field names often quoted in descriptions)
    quoted = re.findall(r'"([a-zA-Z_][a-zA-Z0-9_]*)"', description)
    if quoted:
        return quoted
    # Match backtick-quoted
    backtick = re.findall(r'`([a-zA-Z_][a-zA-Z0-9_]*)`', description)
    if backtick:
        return backtick
    return []


def _extract_facts_from_memory(memory: MemorySnapshot) -> List[str]:
    """Extract human‑readable factual claims from memory records."""
    facts: List[str] = []
    for subgoal in memory.subgoals:
        if subgoal.goal:
            facts.append(f"subgoal {subgoal.subgoal_id}: {subgoal.goal}")
    for plan in memory.plans:
        if plan.intent:
            facts.append(f"plan {plan.plan_id}: {plan.intent}")
    for segment in memory.segments:
        if segment.state:
            facts.append(f"segment {segment.segment_id}: state={segment.state}")
    return facts


# ── mismatch detectors ──────────────────────────────────────────────────────


def _check_step_mismatch(
    step: PlanSegment,
    segment: SegmentMemoryRecord,
) -> SemanticMismatch | None:
    """
    Heuristic: does ``segment.last_output`` contradict the step descriptions?

    Emits ``step_mismatch`` when:
    - The output is a dict with ``success: false`` but step implies success.
    - The output is empty/None but step implies data should be returned.
    - Expected fields (extracted from step text) are missing or empty.
    """
    output = segment.last_output
    step_text = " ".join(step.steps) if step.steps else ""

    if not step_text:
        return None

    reasons: List[str] = []

    # Check: output empty/None vs step expects data
    if output is None or output == {} or output == []:
        if _intent_expects_positive(step_text):
            reasons.append("Output is empty/None but step description expects data")

    # Check: negative output vs positive step expectation
    if isinstance(output, dict) and _is_negative_output(output):
        if _intent_expects_positive(step_text):
            reasons.append(
                f"Output signals failure ({list(k for k in output if k in _NEGATIVE_OUTPUT_KEYS)}) "
                f"but step description expects positive outcome"
            )

    # Check: missing expected fields
    expected_keys = _extract_expected_keys_from_description(step_text)
    if expected_keys and isinstance(output, dict):
        missing = [k for k in expected_keys if k not in output]
        if missing:
            reasons.append(f"Expected fields missing from output: {missing}")

    # Check: required fields empty
    if expected_keys and isinstance(output, dict):
        empty = _output_fields_empty(output, expected_keys)
        if empty:
            reasons.append(f"Expected fields have empty/None values: {empty}")

    if not reasons:
        return None

    return SemanticMismatch(
        type="step_mismatch",
        confidence=0.7,
        details={
            "step": step_text[:200],
            "reasons": reasons,
        },
    )


def _check_plan_mismatch(
    plan: Plan,
    segment: SegmentMemoryRecord,
) -> SemanticMismatch | None:
    """
    Heuristic: does ``segment.last_output`` contradict ``plan.intent``?

    Emits ``plan_mismatch`` when output signals failure but plan intent
    is positive, or when output keywords contradict plan intent keywords.
    """
    output = segment.last_output
    intent = plan.intent

    if not intent:
        return None

    reasons: List[str] = []

    if _is_negative_output(output) and _intent_expects_positive(intent):
        reasons.append(
            f"Output signals failure but plan intent expects positive outcome: '{intent[:100]}'"
        )

    # Check for keyword contradictions in output dict
    if isinstance(output, dict):
        contradictions = _keyword_contradiction(str(output), intent)
        if contradictions:
            reasons.append(
                f"Output contradicts plan intent keywords: {contradictions}"
            )

    # Empty output vs positive intent
    if (output is None or output == {}) and _intent_expects_positive(intent):
        reasons.append("Output is empty but plan intent expects data")

    if not reasons:
        return None

    return SemanticMismatch(
        type="plan_mismatch",
        confidence=0.8,
        details={
            "intent": intent[:200],
            "reasons": reasons,
        },
    )


def _check_subgoal_mismatch(
    subgoal: Subgoal,
    segment: SegmentMemoryRecord,
) -> SemanticMismatch | None:
    """
    Heuristic: does ``segment.last_output`` contradict ``subgoal.goal``?

    Emits ``subgoal_mismatch`` when output signals regression relative to
    the goal, or output is empty when goal implies progress should be made.
    """
    output = segment.last_output
    goal = subgoal.goal

    if not goal:
        return None

    reasons: List[str] = []

    if _is_negative_output(output) and _intent_expects_positive(goal):
        reasons.append(
            f"Output signals failure but subgoal expects progress toward: '{goal[:100]}'"
        )

    # Empty output vs goal expectation
    if (output is None or output == {}) and _intent_expects_positive(goal):
        reasons.append("Output is empty but subgoal expects progress")

    if isinstance(output, dict) and output.get("success") is False:
        if _intent_expects_positive(goal):
            reasons.append(
                f"Output has success=false but subgoal goal expects positive outcome"
            )

    if not reasons:
        return None

    return SemanticMismatch(
        type="subgoal_mismatch",
        confidence=0.9,
        details={
            "goal": goal[:200],
            "reasons": reasons,
        },
    )


def _check_memory_mismatch(
    memory: MemorySnapshot,
    segment: SegmentMemoryRecord,
) -> SemanticMismatch | None:
    """
    Heuristic: does ``segment.last_output`` contradict known facts in memory?

    Checks if output claims something that contradicts facts stored in
    subgoal, plan, or segment records.
    """
    output = segment.last_output
    facts = _extract_facts_from_memory(memory)

    if not facts:
        return None

    reasons: List[str] = []

    # Check: output claims error/not_found but memory shows entity exists
    if isinstance(output, dict):
        output_str = str(output).lower()
        if "not_found" in output_str or "not found" in output_str:
            # Check if memory has facts about the entity
            for fact in facts:
                # Simple check: if output mentions something doesn't exist
                # but memory fact mentions it, that's a contradiction
                pass  # Too specific for heuristic; skip

    # Check: output has success=false but memory shows prior success
    if isinstance(output, dict) and output.get("success") is False:
        for fact in facts:
            lower_fact = fact.lower()
            if any(kw in lower_fact for kw in _MEMORY_SUCCESS_KEYWORDS):
                reasons.append(
                    f"Output claims failure but memory contains prior success: '{fact[:100]}'"
                )
                break

    # Check: output empty but memory has rich context
    if (output is None or output == {}) and len(facts) > 2:
        reasons.append(
            f"Output is empty but memory contains {len(facts)} contextual facts"
        )

    if not reasons:
        return None

    return SemanticMismatch(
        type="memory_mismatch",
        confidence=0.6,
        details={
            "facts_count": len(facts),
            "reasons": reasons,
        },
    )


# ── public API ──────────────────────────────────────────────────────────────


def validate_semantics(
    step: PlanSegment,
    segment: SegmentMemoryRecord,
    plan: Plan,
    subgoal: Subgoal,
    memory: MemorySnapshot,
) -> List[SemanticMismatch]:
    """
    Validate segment output against four semantic targets.

    Args:
        step:
            The ``PlanSegment`` containing the step descriptions that
            produced this segment.
        segment:
            The ``SegmentMemoryRecord`` whose ``last_output`` is evaluated.
        plan:
            The high‑level ``Plan`` with intent and direction.
        subgoal:
            The ``Subgoal`` whose goal state the output should approach.
        memory:
            A ``MemorySnapshot`` containing all known facts, constraints,
            and prior outputs.

    Returns:
        A deterministic, ordered list of ``SemanticMismatch`` objects.
        Order: ``step_mismatch``, ``plan_mismatch``, ``subgoal_mismatch``,
        ``memory_mismatch``.

    None of the inputs are mutated.
    """
    mismatches: List[SemanticMismatch] = []

    # Detectors called in deterministic order
    for detector, args in (
        (_check_step_mismatch, (step, segment)),
        (_check_plan_mismatch, (plan, segment)),
        (_check_subgoal_mismatch, (subgoal, segment)),
        (_check_memory_mismatch, (memory, segment)),
    ):
        result = detector(*args)
        if result is not None:
            mismatches.append(result)

    return mismatches
