"""Unit tests for CouncilSession state transitions."""

import pytest

from src.agent.council.session import CouncilSession
from src.domain.council import CouncilDefinition


@pytest.fixture
def council_def() -> CouncilDefinition:
    return CouncilDefinition(
        council_id="test",
        name="Test Council",
        arbitrator_agent_id="arb",
        member_agent_ids=("m1", "m2", "m3"),
    )


class TestCouncilSession:
    """CouncilSession manages lifecycle of a single deliberation."""

    def test_create_session(self, council_def: CouncilDefinition) -> None:
        """Session starts in convene phase with an ID."""
        session = CouncilSession.create(council_def, "Should we deploy?")
        assert session.phase == "convene"
        assert session.session_id
        assert session.problem_statement == "Should we deploy?"
        assert session.started_at is not None
        assert session.completed_at is None

    def test_valid_phase_transitions(self, council_def: CouncilDefinition) -> None:
        """Session transitions through all phases correctly."""
        session = CouncilSession.create(council_def, "problem")
        phases = ["analysis", "counter", "arbitration", "complete"]
        for phase in phases:
            session.transition_to(phase)
            assert session.phase == phase

    def test_invalid_phase_raises(self, council_def: CouncilDefinition) -> None:
        """Transition to invalid phase name raises ValueError."""
        session = CouncilSession.create(council_def, "problem")
        with pytest.raises(ValueError, match="invalid phase"):
            session.transition_to("invalid_phase")

    def test_skip_phase_raises(self, council_def: CouncilDefinition) -> None:
        """Skipping a phase (convene -> arbitration) raises ValueError."""
        session = CouncilSession.create(council_def, "problem")
        with pytest.raises(ValueError, match="cannot transition"):
            session.transition_to("arbitration")

    def test_complete_sets_timestamp(self, council_def: CouncilDefinition) -> None:
        """complete() sets phase to 'complete' and records timestamp."""
        session = CouncilSession.create(council_def, "problem")
        session.transition_to("analysis")
        session.transition_to("counter")
        session.transition_to("arbitration")
        session.complete()
        assert session.phase == "complete"
        assert session.completed_at is not None
