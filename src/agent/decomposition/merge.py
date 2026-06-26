"""
Merge Strategies — Agent Decomposition Fan-In
===============================================

Implements the four merge strategies defined in Section 9 of
ROADMAP-agent-decomposition.md:

  - ``concat``:         Concatenate results in DAG topological order.
  - ``summarize_llm``:  Pass all results through an LLM (requires agent).
  - ``select_best``:    Score each result, keep the top-ranked.
  - ``custom``:         Invoke a registered merge function by name.

The ``execute_merge()`` function is the single entry point used by the
``DecompositionOrchestrator`` and the ``ContinuationJob`` worker.
"""

from __future__ import annotations

from typing import Any, Callable

from src.agent.types.decomposition import MergeResult

# Merge strategy registry: name → callable
_MERGE_REGISTRY: dict[str, Callable[..., MergeResult]] = {}


class MergeError(Exception):
    """Raised when merge execution fails."""


def get_merge_strategies() -> list[str]:
    """Return list of registered merge strategy names."""
    return list(_MERGE_REGISTRY.keys())


def register_merge_strategy(
    name: str,
    fn: Callable[..., MergeResult],
) -> None:
    """Register a custom merge strategy by name."""
    _MERGE_REGISTRY[name] = fn


def execute_merge(
    strategy: str,
    child_results: dict[str, dict[str, Any]],
    parent_task: str = "",
    prompt_template: str | None = None,
) -> MergeResult:
    """Fan-in: combine N child results into one merged output.

    Args:
        strategy:        One of the known strategies (``concat``,
                         ``summarize_llm``, ``select_best``, ``custom``)
                         or a custom name registered in ``_MERGE_REGISTRY``.
        child_results:   Map of ``subtask_id → job_result_dict``.
        parent_task:     The parent task description (for context).
        prompt_template: Optional LLM prompt template for summarize_llm.

    Returns:
        A ``MergeResult`` with the merged output and metadata.

    Raises:
        MergeError: If the strategy is unknown or execution fails.
    """
    if strategy == "concat":
        return _merge_concat(child_results)
    elif strategy == "summarize_llm":
        return _merge_summarize_llm(child_results, parent_task, prompt_template)
    elif strategy == "select_best":
        return _merge_select_best(child_results)
    elif strategy in _MERGE_REGISTRY:
        return _MERGE_REGISTRY[strategy](child_results, parent_task)
    else:
        raise MergeError(f"Unknown merge strategy: {strategy!r}")


# ── Strategy Implementations ──────────────────────────────────────────────


def _merge_concat(
    child_results: dict[str, dict[str, Any]],
) -> MergeResult:
    """Concatenate results in stable (insertion) order."""
    parts: list[str] = []
    summaries: dict[str, str] = {}
    for subtask_id, result in child_results.items():
        output = result.get("output", result.get("result", str(result)))
        parts.append(f"## {subtask_id}\n{output}")
        summaries[subtask_id] = _summarize(output)
    combined = "\n\n".join(parts)
    return MergeResult(
        output=combined,
        strategy="concat",
        child_summaries=summaries,
    )


def _merge_summarize_llm(
    child_results: dict[str, dict[str, Any]],
    parent_task: str,
    prompt_template: str | None,
) -> MergeResult:
    """LLM-based synthesis (placeholder — requires AgentRuntime).

    .. note::
        The LLM call is not made here.  This returns a placeholder
        ``MergeResult`` with a ``satisfaction_gap`` indicating the
        caller should invoke the LLM merge via the AgentRuntime.
    """
    formatted = _format_results(child_results)
    return MergeResult(
        output=formatted,
        strategy="summarize_llm",
        satisfaction_gap="LLM merge not executed — requires AgentRuntime. "
        "Call execute_llm_merge() with the agent runtime.",
        child_summaries={k: _summarize(v.get("output", str(v))) for k, v in child_results.items()},
    )


def _merge_select_best(
    child_results: dict[str, dict[str, Any]],
) -> MergeResult:
    """Score-based selection using a simple length heuristic.

    In production, replace the scoring function with an LLM call or
    a domain-specific evaluator.
    """
    if not child_results:
        return MergeResult(output="", strategy="select_best")

    best_id = max(
        child_results.keys(),
        key=lambda sid: len(child_results[sid].get("output", "")),
    )
    best_result = child_results[best_id]
    output = best_result.get("output", str(best_result))

    return MergeResult(
        output=output,
        strategy="select_best",
        selected=best_id,
        child_summaries={
            k: _summarize(v.get("output", str(v)))
            for k, v in child_results.items()
        },
    )


# ── Internal Helpers ──────────────────────────────────────────────────────


def _summarize(text: str, max_chars: int = 120) -> str:
    """First ``max_chars`` chars of text, with ellipsis if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _format_results(child_results: dict[str, dict[str, Any]]) -> str:
    """Format child results for LLM prompt context."""
    parts: list[str] = []
    for subtask_id, result in child_results.items():
        output = result.get("output", result.get("result", str(result)))
        parts.append(
            f"Subtask: {subtask_id}\nOutput:\n{output}\n"
            f"{'─' * 40}"
        )
    return "\n\n".join(parts)
