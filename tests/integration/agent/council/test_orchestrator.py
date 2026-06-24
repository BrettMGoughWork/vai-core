"""Integration test for the full council deliberation cycle.

Uses a mock Supervisor that returns canned responses to verify the
orchestrator's 5-phase cycle works end-to-end without touching real LLMs.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.agent.council.orchestrator import CouncilOrchestrator
from src.agent.interfaces.agent_state import AgentState, LifecycleState
from src.domain.council import CouncilDefinition, CouncilOutcome


@pytest.fixture
def council_def() -> CouncilDefinition:
    return CouncilDefinition(
        council_id="integration-test-council",
        name="Integration Test Council",
        description="Council used for integration testing",
        arbitrator_agent_id="arbitrator",
        member_agent_ids=("m1", "m2", "m3"),
        max_analysis_tokens=1000,
        max_counter_tokens=800,
        require_consensus=False,
    )


@pytest.fixture
def calling_agent_state() -> AgentState:
    return AgentState(
        agent_id="calling-agent",
        lifecycle_state=LifecycleState.COMPLETED,
        supervisor_metadata={},
    )


def _make_mock_supervisor(canned_responses: dict[str, str]) -> MagicMock:
    """Build a mock Supervisor that returns canned member responses.

    Parameters
    ----------
    canned_responses:
        Maps agent_id to the response text that agent should return.
    """
    sup = MagicMock()

    def _defer_to_agent(state, target_agent_id, prompt, **kwargs):
        result = MagicMock()
        response = canned_responses.get(target_agent_id, "Default response")
        result.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": response,
            }
        }
        return result

    sup.defer_to_agent.side_effect = _defer_to_agent
    return sup


# ── Tests ────────────────────────────────────────────────────────────────


class TestCouncilIntegration:
    """Complete council deliberation with mocked Supervisor."""

    def test_full_council_simulation(
        self,
        council_def: CouncilDefinition,
        calling_agent_state: AgentState,
    ) -> None:
        """Full 5-phase cycle produces a complete CouncilOutcome."""
        responses = {
            "m1": "Analysis from strategist: pros and cons of deployment",
            "m2": "Analysis from critic: latency concern in the API gateway",
            "m3": "Analysis from risk-assessor: moderate risk, acceptable",
            "arbitrator": (
                "Decision: Proceed with staged rollout\n"
                "Rationale: Majority supports deployment, risks are manageable\n"
                "Confidence: HIGH\n"
                "Dissent Notes: m2 flagged API latency as a concern\n"
            ),
        }
        supervisor = _make_mock_supervisor(responses)
        orch = CouncilOrchestrator(supervisor)
        outcome = orch.deliberate(
            council_def, "Should we deploy v2.5?", calling_agent_state
        )

        assert isinstance(outcome, CouncilOutcome)
        assert outcome.council_id == "integration-test-council"
        assert "m1" in outcome.member_analyses
        assert "m2" in outcome.member_analyses
        assert "m3" in outcome.member_analyses
        assert outcome.member_analyses["m1"] == responses["m1"]

        assert "m1" in outcome.member_counters
        assert outcome.decision is not None
        assert "staged rollout" in outcome.decision
        assert outcome.confidence == 0.9
        assert outcome.dissent_notes is not None
        assert "latency" in outcome.dissent_notes

    def test_member_failure_graceful(
        self,
        council_def: CouncilDefinition,
        calling_agent_state: AgentState,
    ) -> None:
        """When a member fails, council continues with placeholder."""
        sup = MagicMock()

        call_info: dict = {"count": 0}

        def _defer_to_agent(state, target_agent_id, prompt, **kwargs):
            call_info["count"] += 1
            call_info["last_target"] = target_agent_id
            result = MagicMock()
            if target_agent_id == "m2":
                result.supervisor_metadata = {
                    "deferral_result": {"success": False, "response": ""}
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": f"Response from {target_agent_id}",
                    }
                }
            return result

        sup.defer_to_agent.side_effect = _defer_to_agent
        orch = CouncilOrchestrator(sup)
        outcome = orch.deliberate(
            council_def, "Deploy now?", calling_agent_state
        )

        assert "[Member m2 failed to respond]" in outcome.member_analyses.get("m2", "")
        assert outcome.member_analyses["m1"] == "Response from m1"
        assert outcome.member_analyses["m3"] == "Response from m3"

    def test_all_members_fail(
        self,
        council_def: CouncilDefinition,
        calling_agent_state: AgentState,
    ) -> None:
        """Even if all members fail, the council still produces an outcome."""
        sup = MagicMock()

        def _defer_to_agent(state, target_agent_id, prompt, **kwargs):
            result = MagicMock()
            if target_agent_id == "arbitrator":
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": "Decision: Default to safe option\nConfidence: LOW\n",
                    }
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {"success": False, "response": ""}
                }
            return result

        sup.defer_to_agent.side_effect = _defer_to_agent
        orch = CouncilOrchestrator(sup)
        outcome = orch.deliberate(
            council_def, "Deploy now?", calling_agent_state
        )

        assert outcome.council_id == "integration-test-council"
        for mid in ("m1", "m2", "m3"):
            assert "[Member" in outcome.member_analyses.get(mid, "")
        assert outcome.confidence == 0.3

    def test_arbitrator_exception(
        self,
        council_def: CouncilDefinition,
        calling_agent_state: AgentState,
    ) -> None:
        """If arbitrator raises, _defer_to_member catches it."""
        sup = MagicMock()

        call_count: int = 0

        def _defer_to_agent(state, target_agent_id, prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if target_agent_id == "arbitrator":
                msg = "Arbitrator unavailable"
                raise RuntimeError(msg)
            result = MagicMock()
            result.supervisor_metadata = {
                "deferral_result": {"success": True, "response": "Member analysis"}
            }
            return result

        sup.defer_to_agent.side_effect = _defer_to_agent
        orch = CouncilOrchestrator(sup)
        outcome = orch.deliberate(
            council_def, "Deploy?", calling_agent_state
        )

        # arbitrator failure means the response to arbitration is the placeholder
        assert outcome.council_id == "integration-test-council"
        assert outcome.decision is not None
        assert "Arbitrator" in outcome.decision or "failed" in outcome.decision

    def test_token_limit_in_prompt(
        self,
        council_def: CouncilDefinition,
        calling_agent_state: AgentState,
    ) -> None:
        """max_analysis_tokens is passed as advisory guidance in the prompt."""
        sup = MagicMock()

        prompts_seen: list[str] = []

        def _defer_to_agent(state, target_agent_id, prompt, **kwargs):
            prompts_seen.append(prompt)
            result = MagicMock()
            if target_agent_id == "arbitrator":
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": "Decision: Accept\nConfidence: LOW\n",
                    }
                }
            else:
                result.supervisor_metadata = {
                    "deferral_result": {
                        "success": True,
                        "response": "Member analysis",
                    }
                }
            return result

        sup.defer_to_agent.side_effect = _defer_to_agent
        cdef = CouncilDefinition(
            council_id="c",
            name="c",
            arbitrator_agent_id="arbitrator",
            member_agent_ids=("m1",),
            max_analysis_tokens=500,
            max_counter_tokens=300,
        )
        orch = CouncilOrchestrator(sup)
        orch.deliberate(cdef, "problem", calling_agent_state)

        # Analysis prompt should mention the token limit guidance
        assert "500 tokens" in prompts_seen[0]
