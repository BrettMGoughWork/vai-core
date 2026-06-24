"""
CompactionOrchestrator — LLM-based conversation summarisation.

Replaces older conversation-history turns with a single compact summary
when configured triggers fire (context pressure, turn count, subgoal
completed).  Follows the same trigger-point pattern as EvictionOrchestrator.
"""

from __future__ import annotations

import hashlib
import json
import copy
from typing import Dict, List, Optional, Set

from src.agent.memory.compaction.compaction_types import (
    CompactionConfig,
    CompactionResult,
    CompactionTrigger,
    StructuredState,
)
from src.agent.memory.compaction.summary_prompts import (
    CONVERSATION_SUMMARY_SYSTEM,
    CONVERSATION_SUMMARY_USER,
    STATE_EXTRACTION_SYSTEM,
    STATE_EXTRACTION_USER,
    SUBGOAL_COMPLETION_SYSTEM,
    SUBGOAL_COMPLETION_USER,
)
from src.agent.memory.subgoal_memory import SubgoalMemory
from src.agent.memory.types.subgoal import SubgoalLifecycleState
from src.runtime.llm.token_counter import (
    TokenCounter,
    count_tokens_in_messages,
    get_context_limit,
)


def _parse_structured_state(raw_response: str) -> Optional[StructuredState]:
    """Try to parse a ``StructuredState`` from the LLM response.

    Handles responses wrapped in ```json … ``` fences as well as raw JSON.
    Returns ``None`` when parsing fails so the caller falls back to prose.
    """
    text = raw_response.strip()

    # Strip optional markdown fences
    if text.startswith("```"):
        for fence in ("```json\n", "```json\n", "```\n", "```"):  # noqa: E501
            if text.startswith(fence):
                text = text.removeprefix(fence).removesuffix("```").strip()
                break

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    try:
        return StructuredState.from_dict(data)
    except (ValueError, TypeError):
        return None


class CompactionOrchestrator:
    """Orchestrates conversation-history compaction.

    Checks triggers before each LLM call and, when conditions are met,
    sends older conversation turns to the LLM for summarisation, replacing
    them with a single compact summary entry.
    """

    def __init__(
        self,
        llm_complete: object,
        config: Optional[CompactionConfig] = None,
        subgoal_memory: Optional[SubgoalMemory] = None,
    ) -> None:
        """
        Args:
            llm_complete: A callable that accepts a plain-text ``(str)``
                prompt and returns a plain-text ``str`` response — typically
                ``LLMTransport.complete``.
            config: Compaction tuning parameters.
            subgoal_memory: Optional SubgoalMemory for scanning CLOSED
                subgoals that need compaction.  When set, ``compact_if_needed``
                also checks for un-compacted CLOSED subgoals and uses the
                subgoal-specific prompt template.
        """
        self._llm_complete = llm_complete
        self._config = config or CompactionConfig()
        self._token_counter = TokenCounter()
        self._subgoal_memory = subgoal_memory
        # IDs of CLOSED subgoals that have already been compacted.
        self._compacted_subgoal_ids: Set[str] = set()
        # IDs of subgoals for which on_subgoal_closed has already been
        # called — prevents duplicate notifications for the same ID.
        self._notified_subgoal_ids: Set[str] = set()
        # SHA256 fingerprint of the last compacted content — used to
        # skip the LLM call when nothing has changed (staleness guard).
        self._last_conversation_fingerprint: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_fingerprint(entries: List[Dict]) -> str:
        """SHA256 fingerprint of conversation-history entries.

        Deterministic across process restarts (no randomisation in the
        dict serialisation).  Used to skip the LLM call when the
        compactable portion hasn't changed since last compaction.
        """
        serialized = json.dumps(entries, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Public trigger points
    # ------------------------------------------------------------------

    def compact_if_needed(
        self,
        conversation_history: List[Dict],
        model: str = "",
        max_tokens: int = 4096,
        context_pressure: float = 0.0,
    ) -> CompactionResult:
        """Check triggers and compact conversation history if applicable.

        Args:
            conversation_history: The raw conversation-history list from
                ``request.memory`` (mutated in-place on compaction).
            model: Model name used for context-limit lookups.
            max_tokens: Output budget for token-pressure calculation.
            context_pressure: Pre-computed ``input_tokens / context_limit``
                from the caller (set to 0.0 if not yet computed).

        Returns:
            A CompactionResult describing what (if anything) happened.
        """
        if not self._config.enabled:
            return CompactionResult()

        if not conversation_history:
            return CompactionResult()

        # Count turns = user+assistant pairs
        user_turns = sum(
            1 for e in conversation_history if e.get("role") == "user"
        )
        total_tokens = count_tokens_in_messages(conversation_history)

        # Determine trigger ---------------------------------------------------
        trigger: Optional[CompactionTrigger] = None
        subgoal_goal: Optional[str] = None  # populated when SUBGOAL_CLOSED fires

        if (
            context_pressure > 0.0
            and context_pressure >= self._config.context_pressure_threshold
        ):
            trigger = CompactionTrigger.CONTEXT_PRESSURE

        if trigger is None and user_turns >= self._config.turn_count_threshold:
            trigger = CompactionTrigger.TURN_COUNT

        if trigger is None and self._subgoal_memory is not None:
            # Scan for un-compacted CLOSED subgoals
            for record in self._subgoal_memory.snapshot().records:
                if (
                    record.state.lower() == "closed"
                    and record.subgoal_id not in self._compacted_subgoal_ids
                ):
                    trigger = CompactionTrigger.SUBGOAL_CLOSED
                    subgoal_goal = record.goal
                    break

        if trigger is None:
            return CompactionResult()

        # Don't bother compacting very short histories
        if total_tokens < self._config.min_tokens_for_compaction:
            return CompactionResult()

        # Split into compactable + recent ------------------------------------
        keep = self._config.keep_recent_turns * 2  # each turn = user + assistant
        if keep >= len(conversation_history):
            return CompactionResult()

        compactable = conversation_history[:-keep]
        recent = conversation_history[-keep:]
        tokens_before = total_tokens

        # Fingerprint staleness check — skip LLM when compactable hasn't
        # changed since the last compaction pass.
        fp = self._compute_fingerprint(compactable)
        if fp == self._last_conversation_fingerprint:
            return CompactionResult()

        # Save original for potential net-reduction rollback
        _history_before = copy.deepcopy(conversation_history)

        # Build summary via LLM ----------------------------------------------
        history_text = _format_history_for_summary(compactable)

        use_structured = (
            self._config.summary_style == "structured"
            and trigger != CompactionTrigger.SUBGOAL_CLOSED
        )

        if trigger == CompactionTrigger.SUBGOAL_CLOSED and subgoal_goal:
            user_prompt = SUBGOAL_COMPLETION_USER.format(
                goal=subgoal_goal, history=history_text
            )
            system_prompt = SUBGOAL_COMPLETION_SYSTEM
        elif use_structured:
            user_prompt = STATE_EXTRACTION_USER.format(history=history_text)
            system_prompt = STATE_EXTRACTION_SYSTEM
        else:
            user_prompt = CONVERSATION_SUMMARY_USER.format(history=history_text)
            system_prompt = CONVERSATION_SUMMARY_SYSTEM

        try:
            raw_response = self._llm_complete(
                f"{system_prompt}\n\n{user_prompt}"
            )
        except Exception as exc:
            return CompactionResult(
                triggered=True,
                trigger=trigger,
                turns_before=len(conversation_history),
                turns_after=len(conversation_history),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                error=str(exc),
            )

        # Attempt structured state parsing when configured --------------------
        structured_state: Optional[StructuredState] = None
        if use_structured:
            structured_state = _parse_structured_state(raw_response)

        # Build compacted list ------------------------------------------------
        if structured_state:
            # Phase 3: inject [CURRENT STATE] + prose summary sidecar
            state_entry: Dict = {
                "role": "system",
                "content": structured_state.format_for_injection(),
            }
            summary_entry: Dict = {
                "role": "system",
                "content": f"[Compacted summary — {trigger.value}]\n{raw_response.strip()}",
            }
            conversation_history.clear()
            conversation_history.append(state_entry)
            conversation_history.append(summary_entry)
            conversation_history.extend(recent)
        else:
            # Phase 1: plain prose summary
            summary_entry: Dict = {
                "role": "system",
                "content": f"[Compacted summary — {trigger.value}]\n{raw_response.strip()}",
            }
            conversation_history.clear()
            conversation_history.append(summary_entry)
            conversation_history.extend(recent)

        tokens_after = count_tokens_in_messages(conversation_history)

        # Track which subgoal IDs were compacted (may be empty for non-subgoal triggers)
        compacted_ids: set[str] = set()

        # Net reduction guard — roll back if compaction didn't actually
        # save tokens (Design Constraint 1).
        if tokens_after >= tokens_before:
            conversation_history.clear()
            conversation_history.extend(_history_before)
            return CompactionResult(
                triggered=True,
                trigger=trigger,
                turns_before=len(compactable) + len(recent),
                turns_after=len(conversation_history),
                tokens_before=tokens_before,
                tokens_after=tokens_before,
                rolled_back=True,
                compacted_subgoal_ids=compacted_ids,
            )

        # Update fingerprint so subsequent calls can skip if unchanged
        self._last_conversation_fingerprint = fp

        # Mark processed subgoals as compacted
        if trigger == CompactionTrigger.SUBGOAL_CLOSED and subgoal_goal:
            for record in self._subgoal_memory.snapshot().records:
                if (
                    record.state.lower() == "closed"
                    and record.subgoal_id not in self._compacted_subgoal_ids
                ):
                    self._compacted_subgoal_ids.add(record.subgoal_id)
                    compacted_ids.add(record.subgoal_id)

        # Determine turns_after (counts entries, not turn pairs)
        turns_after = len(recent) + (2 if structured_state else 1)

        return CompactionResult(
            triggered=True,
            trigger=trigger,
            turns_before=len(compactable) + len(recent),
            turns_after=turns_after,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            summary=raw_response.strip(),
            structured_state=structured_state,
            compacted_subgoal_ids=compacted_ids,
        )

    def on_subgoal_closed(
        self,
        subgoal_id: str,
        goal: str,
        context: str,
    ) -> CompactionResult:
        """Handle a subgoal CLOSED transition.

        Queues the subgoal for compaction on the next ``compact_if_needed``
        pass.  ``compact_if_needed`` will discover it via the SubgoalMemory
        scan and compact it.

        Returns a result with ``triggered=True`` to signal that the subgoal
        has been queued (or was already known).
        """
        _ = context  # reserved for future use (execution-window hints)

        # Already notified — no-op (prevent duplicate tracking)
        if subgoal_id in self._notified_subgoal_ids:
            return CompactionResult()

        # Without subgoal_memory we can't scan for it in compact_if_needed,
        # so there's nothing to queue — just acknowledge the notification.
        if self._subgoal_memory is None:
            self._notified_subgoal_ids.add(subgoal_id)
            return CompactionResult(triggered=True, trigger=CompactionTrigger.SUBGOAL_CLOSED)

        # Record the notification so we don't process it twice
        self._notified_subgoal_ids.add(subgoal_id)
        return CompactionResult(triggered=True, trigger=CompactionTrigger.SUBGOAL_CLOSED)


# ── Internal helpers ───────────────────────────────────────────────────


def _format_history_for_summary(entries: List[Dict]) -> str:
    """Format conversation entries as flat text for the summarisation LLM."""
    lines: List[str] = []
    for entry in entries:
        role = entry.get("role", "unknown")
        content = entry.get("content", "")
        lines.append(f"[{role}]\n{content}\n")
    return "\n".join(lines)
