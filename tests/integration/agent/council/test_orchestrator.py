"""Integration test for the full council deliberation cycle.

Uses a mock Supervisor that returns canned responses to verify the
orchestrator's 5-phase cycle works end-to-end without touching real LLMs.

Phases 2 and 3 use ``parallelize()`` (fan-out/fan-in); Phase 4 still
uses ``defer_to_agent()`` for the single arbitrator.
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

    Phases 2 & 3 use ``parallelize()`` — the mock returns the canned
    responses keyed by agent_id.  The arbitrator response is also in the
    dict and returned via ``defer_to_agent()``.

    Parameters
    ----------
    canned_responses:
        Maps agent_id to the response text that agent should return.
    """
    sup = MagicMock()

    # Phase 2 & 3: parallelize returns (merge_mock, agent_results)
    def _parallelize(items, *, parent_task="", merge_strategy="concat"):
        agent_results: dict[str, dict[str, str]] = {}
        for agent_id, _prompt in items:
            text = canned_responses.get(agent_id, "Default response")
            agent_results[agent_id] = {
                "output": text,
                "status": "success",
                "done": True,
            }
        return MagicMock(), agent_results

    sup.parallelize.side_effect = _parallelize

    # Phase 4: arbitrator uses defer_to_agent
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

        def _parallelize(items, *, parent_task="", merge_strategy="concat"):
            agent_results: dict[str, dict[str, str]] = {}
            for agent_id, _prompt in items:
                if agent_id == "m2":
                    agent_results[agent_id] = {
                        "output": "", "status": "error", "done": True,
                    }
                else:
                    agent_results[agent_id] = {
                        "output": f"Response from {agent_id}",
                        "status": "success",
                        "done": True,
                    }
            return MagicMock(), agent_results

        sup.parallelize.side_effect = _parallelize
        sup.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: Default\nConfidence: LOW\n",
            }
        }
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

        def _parallelize(items, *, parent_task="", merge_strategy="concat"):
            agent_results: dict[str, dict[str, str]] = {}
            for agent_id, _prompt in items:
                agent_results[agent_id] = {
                    "output": "", "status": "error", "done": True,
                }
            return MagicMock(), agent_results

        sup.parallelize.side_effect = _parallelize
        sup.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: Default to safe option\nConfidence: LOW\n",
            }
        }
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

        def _parallelize(items, *, parent_task="", merge_strategy="concat"):
            agent_results: dict[str, dict[str, str]] = {}
            for agent_id, _prompt in items:
                agent_results[agent_id] = {
                    "output": "Member analysis", "status": "success", "done": True,
                }
            return MagicMock(), agent_results

        sup.parallelize.side_effect = _parallelize

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

        def _parallelize(items, *, parent_task="", merge_strategy="concat"):
            for _agent_id, prompt in items:
                prompts_seen.append(prompt)
            agent_results: dict[str, dict[str, str]] = {}
            for agent_id, _prompt in items:
                agent_results[agent_id] = {
                    "output": "Member analysis", "status": "success", "done": True,
                }
            return MagicMock(), agent_results

        sup.parallelize.side_effect = _parallelize
        sup.defer_to_agent.return_value.supervisor_metadata = {
            "deferral_result": {
                "success": True,
                "response": "Decision: Accept\nConfidence: LOW\n",
            }
        }

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

        # The first prompt (analysis) should mention the token limit guidance
        analysis_prompt = prompts_seen[0]
        assert "500 tokens" in analysis_prompt
