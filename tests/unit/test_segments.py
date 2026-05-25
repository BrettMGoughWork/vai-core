import pytest

from src.core.planning.segments.manager import PlanSegmentManager
from src.core.planning.segments.state import SegmentState
from src.core.planning.segments.errors import (
    SegmentValidationError,
    SegmentStitchingError,
)
from src.core.planning.segments.model import PlanSegment


# ------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------
@pytest.fixture
def state():
    return SegmentState()


@pytest.fixture
def manager(state):
    return PlanSegmentManager(state=state)


# ------------------------------------------------------------
# Creation
# ------------------------------------------------------------
def test_create_segment(manager, state):
    seg = manager.create_segment(
        subgoal_id="sg1",
        steps=["1", "2", "3"],
        context={"a": 1},
        metadata={"b": 2},
    )

    assert seg.subgoal_id == "sg1"
    assert seg.steps == ["1", "2", "3"]
    assert state.get(seg.segment_id) is seg

    # Event emitted
    events = state.events()
    assert len(events) == 1
    assert events[0]["type"] == "segment_created"
    assert events[0]["segment_id"] == seg.segment_id


def test_invalid_segment_fails_validation(manager):
    # Missing steps → invalid
    with pytest.raises(SegmentValidationError):
        manager.create_segment(
            subgoal_id="sg1",
            steps=[],
        )


# ------------------------------------------------------------
# Stitching — valid
# ------------------------------------------------------------
def test_stitch_two_segments(manager, state):
    s1 = manager.create_segment("sg1", ["1", "2"])
    s2 = manager.create_segment("sg1", ["3", "4"])

    chain = manager.stitch([s2, s1]) # out of order on purpose

    assert chain == [s1, s2]

    events = state.events()
    assert events[-1]["type"] == "segments_stitched"
    assert events[-1]["segment_ids"] == [s1.segment_id, s2.segment_id]


def test_stitch_three_segments(manager):
    s1 = manager.create_segment("sg1", ["1"])
    s2 = manager.create_segment("sg1", ["2"])
    s3 = manager.create_segment("sg1", ["3"])

    chain = manager.stitch([s3, s1, s2])
    assert chain == [s1, s2, s3]


# ------------------------------------------------------------
# Stitching — invalid
# ------------------------------------------------------------
def test_stitch_fails_on_gap(manager):
    s1 = manager.create_segment("sg1", ["1"])
    s2 = manager.create_segment("sg1", ["3"]) # gap: missing "2"

    with pytest.raises(SegmentStitchingError):
        manager.stitch([s1, s2])


def test_stitch_fails_on_overlap(manager):
    s1 = manager.create_segment("sg1", ["1", "2"])
    s2 = manager.create_segment("sg1", ["2", "3"]) # overlap at "2"

    with pytest.raises(SegmentStitchingError):
        manager.stitch([s1, s2])


def test_stitch_fails_on_mixed_subgoals(manager):
    s1 = manager.create_segment("sg1", ["1"])
    s2 = manager.create_segment("sg2", ["2"])

    with pytest.raises(SegmentStitchingError):
        manager.stitch([s1, s2])


# ------------------------------------------------------------
# Determinism
# ------------------------------------------------------------
def test_stitch_is_deterministic(manager):
    s1 = manager.create_segment("sg1", ["1"])
    s2 = manager.create_segment("sg1", ["2"])

    chain1 = manager.stitch([s2, s1])
    chain2 = manager.stitch([s1, s2])

    assert chain1 == chain2 == [s1, s2]


# ------------------------------------------------------------
# JSON purity of events
# ------------------------------------------------------------
def test_events_are_json_pure(manager, state):
    seg = manager.create_segment("sg1", ["1", "2"])
    manager.stitch([seg])

    for event in state.events():
        assert isinstance(event, dict)
        assert all(isinstance(k, str) for k in event.keys())