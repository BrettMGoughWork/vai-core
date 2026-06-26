"""Unit tests for the CouncilOrchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.council.orchestrator import (
    CouncilOrchestrator,
    _ERROR_PLACEHOLDER,
)
from src.domain.council import CouncilDefinition, CouncilOutcome


def _parallelize_result(
    responses: dict[str, str],
) -> tuple[MagicMock, dict[str, dict[str, str]]]:
    """Build ``(merge_mock, agent_results)`` as returned by ``parallelize()``."""
    agent_results: dict[str, dict[str, str]] = {}
    for agent_id, text in responses.items():
        agent_results[agent_id] = {
            "output": text,
            "status": "success",
            "done": True,
        }
    return MagicMock(), agent_results


def _make_mock_supervisor_with_parallelize(
    canned: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock Supervisor where ``parallelize()`` returns canned responses.

    Phase 4 (arbitrator) still uses ``defer_to_agent()`` — that is mocked
    separately below in each test that needs it.
    """
    sup = MagicMock()
    responses: dict[str, str] = canned or {
        "m1": "Analysis from member X",
        "m2": "Analysis from member X",
    }

    def _parallelize(
        items, *, parent_task="", merge_strategy="concat"
    ):
        agent_results: dict[str, dict[str, str]] = {}
        for agent_id, _prompt in items:
            text = responses.get(agent_id, "Default response")
            agent_results[agent_id] = {
                "output": text,
                "status": "success",
                "done": True,
            }
        return MagicMock(), agent_results

    sup.parallelize.side_effect = _parallelize
    return sup


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
    return _make_mock_supervisor_with_parallelize()


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
        # Wire arbitrator deferral
        mock_supervisor.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: Deploy\nConfidence: HIGH\n",
            }
        }
        orch = CouncilOrchestrator(mock_supervisor)
        outcome = orch.deliberate(council_def, "Should we deploy?", mock_calling_state)

        assert isinstance(outcome, CouncilOutcome)
        assert outcome.council_id == "test-council"
        assert "m1" in outcome.member_analyses
        assert "m2" in outcome.member_analyses
        assert "m1" in outcome.member_counters
        assert "m2" in outcome.member_counters

    def test_calls_parallelize_and_defer_to_agent(
        self,
        council_def: CouncilDefinition,
        mock_supervisor: MagicMock,
        mock_calling_state: MagicMock,
    ) -> None:
        """parallelize is called for Phase 2 and 3; defer_to_agent once for Phase 4."""
        mock_supervisor.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: x\nConfidence: LOW\n",
            }
        }
        orch = CouncilOrchestrator(mock_supervisor)
        orch.deliberate(council_def, "problem", mock_calling_state)

        # parallelize: once for analysis, once for counter-analysis
        assert mock_supervisor.parallelize.call_count == 2
        # defer_to_agent: once for arbitrator
        assert mock_supervisor.defer_to_agent.call_count == 1

    def test_member_failure_graceful(
        self,
        council_def: CouncilDefinition,
        mock_calling_state: MagicMock,
    ) -> None:
        """If a member fails, council continues and arbitrator is informed."""
        def _parallelize(items, *, parent_task="", merge_strategy="concat"):
            agent_results: dict[str, dict[str, str]] = {}
            for agent_id, _prompt in items:
                if agent_id == "m1":
                    agent_results[agent_id] = {
                        "output": "m1 analysis", "status": "success", "done": True,
                    }
                else:
                    # m2 fails — empty output
                    agent_results[agent_id] = {
                        "output": "", "status": "error", "done": True,
                    }
            return MagicMock(), agent_results

        mock_sup = MagicMock()
        mock_sup.parallelize.side_effect = _parallelize
        mock_sup.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: x\nConfidence: LOW\n",
            }
        }

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
        arb_response = (
            "Decision: Deploy after fixing security issue\n"
            "Rationale: The risk is manageable with mitigations\n"
            "Confidence: HIGH\n"
            "Dissent Notes: m2 raised valid concerns about latency\n"
        )
        mock_sup = _make_mock_supervisor_with_parallelize({
            "m1": "analysis", "m2": "analysis",
        })
        mock_sup.defer_to_agent.side_effect = None
        mock_sup.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {"success": True, "response": arb_response}
        }

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
        mock_supervisor.defer_to_agent.side_effect = None
        mock_supervisor.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: x\nConfidence: MEDIUM\n",
            }
        }

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
        mock_supervisor.defer_to_agent.side_effect = None
        mock_supervisor.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Just do it. I think it's fine.",
            }
        }

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
