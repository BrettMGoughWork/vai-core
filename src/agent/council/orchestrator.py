"""
CouncilOrchestrator — multi-agent deliberation and arbitration.

Runs a full 5-phase council cycle (Convene → Analysis → Counter-Analysis
→ Arbitration → Hand-back) using the existing ``Supervisor.defer_to_agent()``
primitive.  No new lifecycle states are needed — council members go through
the standard CREATED → ACTIVATED → RUNNING → COMPLETED flow.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from src.agent.council.prompts import (
    build_analysis_prompt,
    build_counter_prompt,
    build_arbitration_prompt,
)
from src.agent.council.session import CouncilSession
from src.agent.interfaces.agent_state import AgentState
from src.agent.supervisor import Supervisor
from src.domain.council import CouncilDefinition, CouncilOutcome

logger = logging.getLogger(__name__)

_ERROR_PLACEHOLDER = "[Member {member_id} failed to respond]"


class CouncilOrchestrator:
    """Orchestrates multi-agent council deliberations.

    Parameters
    ----------
    supervisor:
        The Supervisor instance used for all defer-to-agent calls.
    """

    def __init__(self, supervisor: Supervisor) -> None:
        self._supervisor = supervisor

    # ── Public API ──────────────────────────────────────────────────────

    def deliberate(
        self,
        council_def: CouncilDefinition,
        problem: str,
        calling_agent_state: AgentState,
    ) -> CouncilOutcome:
        """Run a full council deliberation (all 5 phases).

        Parameters
        ----------
        council_def:
            The council configuration (members + arbitrator).
        problem:
            The problem statement put to the council.
        calling_agent_state:
            The agent that invoked the council (used for deferral context).

        Returns
        -------
        CouncilOutcome:
            The final decision with full audit trail.
        """
        session = CouncilSession.create(council_def, problem)

        # ── Phase 2: Individual Analysis ──────────────────────────────
        session.transition_to("analysis")
        for member_id in council_def.member_agent_ids:
            prompt = build_analysis_prompt(
                problem,
                member_id,
                max_tokens=council_def.max_analysis_tokens,
            )
            analysis = self._defer_to_member(
                calling_agent_state, member_id, prompt
            )
            session.analyses[member_id] = analysis

        # ── Phase 3: Counter-Analysis ─────────────────────────────────
        session.transition_to("counter")
        for member_id in council_def.member_agent_ids:
            others = {
                mid: text
                for mid, text in session.analyses.items()
                if mid != member_id
            }
            prompt = build_counter_prompt(
                problem,
                member_id,
                others,
                max_tokens=council_def.max_counter_tokens,
            )
            counter = self._defer_to_member(
                calling_agent_state, member_id, prompt
            )
            session.counters[member_id] = counter

        # ── Phase 4: Arbitration ──────────────────────────────────────
        session.transition_to("arbitration")
        prompt = build_arbitration_prompt(
            problem, session.analyses, session.counters
        )
        decision = self._defer_to_member(
            calling_agent_state,
            council_def.arbitrator_agent_id,
            prompt,
        )

        # ── Phase 5: Hand-back ────────────────────────────────────────
        outcome = self._parse_decision(decision, council_def, session)
        session.complete()
        return outcome

    # ── Internal helpers ────────────────────────────────────────────────

    def _defer_to_member(
        self,
        calling_state: AgentState,
        target_agent_id: str,
        prompt: str,
    ) -> str:
        """Defer to a council member and extract their response text.

        If the member fails (e.g. timeout, error), records a placeholder
        so the arbitrator knows the member did not contribute.
        """
        try:
            result_state = self._supervisor.defer_to_agent(
                state=calling_state,
                target_agent_id=target_agent_id,
                prompt=prompt,
                skip_authorization=True,
            )
            deferral_result = result_state.supervisor_metadata.get(
                "deferral_result", {}
            )
            if deferral_result.get("success"):
                return deferral_result.get("response", "")
            else:
                logger.warning(
                    "Council member %s returned unsuccessfully", target_agent_id
                )
                return _ERROR_PLACEHOLDER.format(member_id=target_agent_id)
        except Exception:
            logger.exception(
                "Council member %s raised an exception", target_agent_id
            )
            return _ERROR_PLACEHOLDER.format(member_id=target_agent_id)

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        """Truncate *text* to *max_tokens* (approximate character-level).

        A rough heuristic: 1 token ≈ 4 characters.
        """
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n\n[... truncated]"

    def _parse_decision(
        self,
        arbitrator_response: str,
        council_def: CouncilDefinition,
        session: CouncilSession,
    ) -> CouncilOutcome:
        """Parse the arbitrator's structured output into a ``CouncilOutcome``.

        Looks for ``Decision:``, ``Confidence:``, and ``Dissent Notes:``
        markers in the response.  Falls back to using the full response as
        the decision if parsing fails.
        """
        decision = self._extract_field(arbitrator_response, r"Decision:\s*(.+)")
        if not decision:
            decision = arbitrator_response.strip()

        confidence_str = self._extract_field(
            arbitrator_response, r"Confidence:\s*(.+)"
        )
        confidence = self._parse_confidence(confidence_str)

        dissent_notes = (
            self._extract_field(
                arbitrator_response, r"Dissent Notes?:\s*(.+)",
            )
            or self._extract_field(
                arbitrator_response, r"Dissent Notes?:\n((?:(?!\n\w+:).+\n?)*)",
            )
        )

        return CouncilOutcome(
            council_id=council_def.council_id,
            decision=decision,
            member_analyses=dict(session.analyses),
            member_counters=dict(session.counters),
            confidence=confidence,
            dissent_notes=dissent_notes,
        )

    @staticmethod
    def _extract_field(text: str, pattern: str) -> Optional[str]:
        """Extract the first match of *pattern* from *text*.

        Returns the first capture group content, or *None*.
        """
        m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
        return m.group(1).strip() if m else None

    @staticmethod
    def _parse_confidence(value: Optional[str]) -> float:
        """Map a confidence string to a numeric 0.0 — 1.0 score."""
        if not value:
            return 0.0
        value = value.strip().upper()
        mapping: Dict[str, float] = {
            "HIGH": 0.9,
            "MEDIUM": 0.6,
            "LOW": 0.3,
        }
        return mapping.get(value, 0.0)
