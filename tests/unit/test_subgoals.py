# tests/core/planning/subgoals/test_subgoals.py

import pytest

from src.core.planning.subgoals.manager import SubgoalManager
from src.core.planning.subgoals.state import SubgoalState
from src.core.planning.validators.subgoal_validator import SubgoalValidator
from src.core.types.subgoal import SubgoalLifecycleState
from src.core.planning.subgoals.errors import (
    SubgoalNotFoundError,
    InvalidSubgoalError,
    IllegalSubgoalTransitionError,
    SubgoalHierarchyError,
)


# ------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------

@pytest.fixture
def state():
    return SubgoalState()

@pytest.fixture
def validator():
    return SubgoalValidator()

@pytest.fixture
def manager(state, validator):
    return SubgoalManager(state=state, validator=validator)


# ------------------------------------------------------------
# Creation tests
# ------------------------------------------------------------

def test_create_subgoal_basic(manager, state):
    sg = manager.create_subgoal(
        goal="root-goal",
        context={"x": 1},
        metadata={"m": True},
    )

    assert sg.goal == "root-goal"
    assert sg.state == SubgoalLifecycleState.PENDING
    assert state.get(sg.subgoal_id) is not None

    # Event emitted
    events = state.events()
    assert len(events) == 1
    assert events[0]["type"] == "subgoal_created"
    assert events[0]["subgoal_id"] == sg.subgoal_id


def test_create_subgoal_with_parent(manager, state):
    parent = manager.create_subgoal("parent", {}, {})
    child = manager.create_subgoal("child", {}, {}, parent_id=parent.subgoal_id)

    assert child.parent_id == parent.subgoal_id
    assert child.subgoal_id in state._subgoals


def test_create_subgoal_invalid_parent(manager):
    with pytest.raises(SubgoalHierarchyError):
        manager.create_subgoal("child", {}, {}, parent_id="missing")


# ------------------------------------------------------------
# Validation tests
# ------------------------------------------------------------

def test_invalid_subgoal_fails_validation(manager, validator):
    # Force validator to fail by patching the validate method directly
    from unittest.mock import patch
    with patch.object(validator, 'validate', return_value=False):
        with pytest.raises(InvalidSubgoalError):
            manager.create_subgoal("bad", {}, {})


# ------------------------------------------------------------
# Transition tests
# ------------------------------------------------------------

def test_transition_pending_to_active(manager, state):
    sg = manager.create_subgoal("goal", {}, {})
    updated = manager.transition(sg.subgoal_id, SubgoalLifecycleState.ACTIVE)

    assert updated.state == SubgoalLifecycleState.ACTIVE

    # Event emitted
    events = state.events()
    assert events[-1]["type"] == "subgoal_transition"
    assert events[-1]["from_state"] == "pending"
    assert events[-1]["to_state"] == "active"


def test_illegal_transition_raises(manager):
    sg = manager.create_subgoal("goal", {}, {})

    # Cannot go pending → satisfied
    with pytest.raises(IllegalSubgoalTransitionError):
        manager.transition(sg.subgoal_id, SubgoalLifecycleState.SATISFIED)


def test_transition_active_to_terminal(manager):
    sg = manager.create_subgoal("goal", {}, {})
    sg = manager.transition(sg.subgoal_id, SubgoalLifecycleState.ACTIVE)

    # Active → satisfied → closed
    sg = manager.transition(sg.subgoal_id, SubgoalLifecycleState.SATISFIED)
    sg = manager.transition(sg.subgoal_id, SubgoalLifecycleState.CLOSED)

    assert sg.state == SubgoalLifecycleState.CLOSED


# ------------------------------------------------------------
# Hierarchy tests
# ------------------------------------------------------------

def test_active_chain(manager, state):
    root = manager.create_subgoal("root", {}, {})
    c1 = manager.create_subgoal("child1", {}, {}, parent_id=root.subgoal_id)
    c2 = manager.create_subgoal("child2", {}, {}, parent_id=c1.subgoal_id)

    # Activate chain
    manager.transition(root.subgoal_id, SubgoalLifecycleState.ACTIVE)
    manager.transition(c1.subgoal_id, SubgoalLifecycleState.ACTIVE)
    manager.transition(c2.subgoal_id, SubgoalLifecycleState.ACTIVE)

    chain = state.active_chain()
    assert [sg.subgoal_id for sg in chain] == [
        root.subgoal_id,
        c1.subgoal_id,
        c2.subgoal_id,
    ]


def test_active_chain_chooses_lexicographically(manager, state):
    root = manager.create_subgoal("root", {}, {})
    a = manager.create_subgoal("a", {}, {}, parent_id=root.subgoal_id)
    b = manager.create_subgoal("b", {}, {}, parent_id=root.subgoal_id)

    manager.transition(root.subgoal_id, SubgoalLifecycleState.ACTIVE)
    manager.transition(a.subgoal_id, SubgoalLifecycleState.ACTIVE)
    manager.transition(b.subgoal_id, SubgoalLifecycleState.ACTIVE)

    chain = state.active_chain()

    # active_chain() sorts active children by subgoal_id (a stable hash),
    # and picks the lexicographically smallest. The winner is determined by
    # hash value, not goal text — so we derive the expected leaf from the IDs.
    expected_leaf = a if a.subgoal_id < b.subgoal_id else b
    assert chain[-1].subgoal_id == expected_leaf.subgoal_id


# ------------------------------------------------------------
# State store tests
# ------------------------------------------------------------

def test_state_update_requires_existing(manager, state):
    sg = manager.create_subgoal("goal", {}, {})

    # Remove it manually to simulate corruption
    state._subgoals.pop(sg.subgoal_id)

    with pytest.raises(SubgoalNotFoundError):
        state.update(sg)


# ------------------------------------------------------------
# Event tests
# ------------------------------------------------------------

def test_events_are_json_pure(manager, state):
    sg = manager.create_subgoal("goal", {}, {})
    manager.transition(sg.subgoal_id, SubgoalLifecycleState.ACTIVE)

    for event in state.events():
        assert isinstance(event, dict)
        assert "type" in event
        assert "subgoal_id" in event


# ------------------------------------------------------------
# Canonical hash tests
# ------------------------------------------------------------

def test_canonical_hash_changes_on_state_change(manager):
    sg = manager.create_subgoal("goal", {}, {})
    h1 = sg.canonical_hash

    sg2 = manager.transition(sg.subgoal_id, SubgoalLifecycleState.ACTIVE)
    h2 = sg2.canonical_hash

    assert h1 != h2