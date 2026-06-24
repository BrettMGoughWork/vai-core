"""Unit tests for the CouncilOrchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.council.orchestrator import (
    CouncilOrchestrator,
    _ERROR_PLACEHOLDER,
)
from src.domain.council import CouncilDefinition, CouncilOutcome


@pytest.fixture
def council_def() -> CouncilDefinition:
    return CouncilDefinition(
        council_id="test-council",
        name="Test Council",
        arbitrator_agent_id="arbitrator",
        member_agent_ids=("m1", "m2"),
    )


@pytest.fixture
def mock_supervisor() -> MagicMock:
    sup = MagicMock()
    # Simulate successful deferral by default
    sup.defer_to_agent.return_value.supervisor_metadata = {
        "deferral_result": {
            "success": True,
            "response": "Analysis from member X",
        }
    }
    return sup


@pytest.fixture
def mock_calling_state() -> MagicMock:
    return MagicMock()


class TestCouncilOrchestrator:
    """CouncilOrchestrator runs the 5-phase deliberation cycle."""

    def test_full_council_simulation(
        self,
        council_def: CouncilDefinition,
        mock_supervisor: MagicMock,
        mock_calling_state: MagicMock,
    ) -> None:
        """End-to-end council with mocked Supervisor returns CouncilOutcome."""
        orch = CouncilOrchestrator(mock_supervisor)
        outcome = orch.deliberate(council_def, "Should we deploy?", mock_calling_state)

        assert isinstance(outcome, CouncilOutcome)
        assert outcome.council_id == "test-council"
        assert "m1" in outcome.member_analyses
        assert "m2" in outcome.member_analyses
        assert "m1" in outcome.member_counters
        assert "m2" in outcome.member_counters

    def test_calls_defer_to_agent_for_each_phase(
        self,
        council_def: CouncilDefinition,
        mock_supervisor: MagicMock,
        mock_calling_state: MagicMock,
    ) -> None:
        """defer_to_agent is called once per member per phase + arbitrator."""
        orch = CouncilOrchestrator(mock_supervisor)
        orch.deliberate(council_def, "problem", mock_calling_state)

        # 2 members × (analysis + counter) + 1 arbitrator = 5 calls
        assert mock_supervisor.defer_to_agent.call_count == 5

    def test_member_failure_graceful(
        self,
        council_def: CouncilDefinition,
        mock_calling_state: MagicMock,
    ) -> None:
        """If a member fails, council continues and arbitrator is informed."""
        mock_sup = MagicMock()
        def _side_effect(state, target_agent_id, prompt, **kwargs):
            result = MagicMock()
            if target_agent_id == "m1":
                result.supervisor_metadata = {
                    "deferral_result": {"success": True, "response": "m1 analysis"}
                }
            else:
                # m2 fails
                result.supervisor_metadata = {
                    "deferral_result": {"success": False, "response": ""}
                }
            return result
        mock_sup.defer_to_agent.side_effect = _side_effect

        orch = CouncilOrchestrator(mock_sup)
        outcome = orch.deliberate(council_def, "problem", mock_calling_state)

        assert outcome.council_id == "test-council"
        assert "m1" in outcome.member_analyses
        placeholder = _ERROR_PLACEHOLDER.format(member_id="m2")
        assert outcome.member_analyses.get("m2") == placeholder

    def test_arbitrator_decision_parsed(
        self,
        council_def: CouncilDefinition,
        mock_calling_state: MagicMock,
    ) -> None:
        """Arbitrator's structured output is parsed into CouncilOutcome."""
        mock_sup = MagicMock()
        arb_response = (
            "Decision: Deploy after fixing security issue\n"
            "Rationale: The risk is manageable with mitigations\n"
            "Confidence: HIGH\n"
            "Dissent Notes: m2 raised valid concerns about latency\n"
        )

        call_count = [0]
        def _side_effect(state, target_agent_id, prompt, **kwargs):
            result = MagicMock()
            if target_agent_id == "arbitrator":
                result.supervisor_metadata = {
                    "deferral_result": {"success": True, "response": arb_response}
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {"success": True, "response": "analysis"}
                }
            call_count[0] += 1
            return result
        mock_sup.defer_to_agent.side_effect = _side_effect

        orch = CouncilOrchestrator(mock_sup)
        outcome = orch.deliberate(council_def, "problem", mock_calling_state)

        assert "Deploy after fixing security issue" in outcome.decision
        assert outcome.confidence == 0.9
        assert outcome.dissent_notes is not None
        assert "latency" in outcome.dissent_notes

    def test_confidence_mapping(
        self,
        mock_supervisor: MagicMock,
        mock_calling_state: MagicMock,
    ) -> None:
        """Confidence strings are mapped to numeric values."""
        # Override only the arbitration response
        def _side_effect(state, target_agent_id, prompt, **kwargs):
            result = MagicMock()
            if target_agent_id == "arbitrator":
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": "Decision: x\nConfidence: MEDIUM\n",
                    }
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {"success": True, "response": "analysis"}
                }
            return result
        mock_supervisor.defer_to_agent.side_effect = _side_effect

        cdef = CouncilDefinition(
            council_id="c",
            name="c",
            arbitrator_agent_id="arbitrator",
            member_agent_ids=("m1",),
        )
        orch = CouncilOrchestrator(mock_supervisor)
        outcome = orch.deliberate(cdef, "problem", mock_calling_state)
        assert outcome.confidence == 0.6

    def test_parse_decision_fallback(
        self,
        mock_supervisor: MagicMock,
        mock_calling_state: MagicMock,
    ) -> None:
        """If arbitrator gives unstructured response, fallback uses full text."""
        def _side_effect(state, target_agent_id, prompt, **kwargs):
            result = MagicMock()
            if target_agent_id == "arbitrator":
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": "Just do it. I think it's fine.",
                    }
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {"success": True, "response": "analysis"}
                }
            return result
        mock_supervisor.defer_to_agent.side_effect = _side_effect

        cdef = CouncilDefinition(
            council_id="c",
            name="c",
            arbitrator_agent_id="arbitrator",
            member_agent_ids=("m1",),
        )
        orch = CouncilOrchestrator(mock_supervisor)
        outcome = orch.deliberate(cdef, "problem", mock_calling_state)
        assert "Just do it" in outcome.decision
        assert outcome.confidence == 0.0
