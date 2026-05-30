"""
Validator tests for governance-layer validators.

Covers:
- SubgoalValidator: structural validation of Subgoal objects
- PlanSegmentValidator: structural validation of PlanSegment stubs
  Note: the validator uses a different hash formula than the PlanSegment model,
  so a stub (SimpleNamespace) is used to set the canonical_hash independently.
"""
import pytest
from types import SimpleNamespace

from src.core.planning.validators.subgoal_validator import SubgoalValidator
from src.core.planning.validators.plan_segment_validator import PlanSegmentValidator
from src.core.types.subgoal import Subgoal, SubgoalLifecycleState
from src.core.types.hashing import stable_hash
from src.core.types.errors import ValidationError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _subgoal(subgoal_id="sg-1", goal="Do something", context=None, metadata=None, state=SubgoalLifecycleState.PENDING):
    return Subgoal(
        subgoal_id=subgoal_id,
        goal=goal,
        context=context or {},
        metadata=metadata or {},
        state=state,
    )


def _segment_stub(
    segment_id="seg-1",
    subgoal_id="sub-1",
    steps=None,
    context=None,
    metadata=None,
    canonical_hash=None,
):
    """
    Build a NameSpace that satisfies PlanSegmentValidator's duck-typing.
    The validator's canonical_hash check uses:
      stable_hash({subgoal_id, steps, context, metadata})
    which differs from PlanSegment.__post_init__ (a known discrepancy).
    """
    steps = steps if steps is not None else ["step-1"]
    context = context or {}
    metadata = metadata or {}
    if canonical_hash is None:
        canonical_hash = stable_hash(
            {"subgoal_id": subgoal_id, "steps": steps, "context": context, "metadata": metadata}
        )
    return SimpleNamespace(
        segment_id=segment_id,
        subgoal_id=subgoal_id,
        steps=steps,
        context=context,
        metadata=metadata,
        canonical_hash=canonical_hash,
    )


# ── SubgoalValidator ──────────────────────────────────────────────────────────

class TestSubgoalValidator:
    def test_valid_subgoal_returns_true(self):
        assert SubgoalValidator().validate(_subgoal()) is True

    def test_subgoal_with_context_and_metadata_is_valid(self):
        sg = _subgoal(context={"key": "value"}, metadata={"version": 1})
        assert SubgoalValidator().validate(sg) is True

    def test_all_lifecycle_states_pass_structural_check(self):
        validator = SubgoalValidator()
        for state in SubgoalLifecycleState:
            sg = _subgoal(state=state)
            assert validator.validate(sg) is True

    def test_empty_subgoal_id_returns_false(self):
        sg = Subgoal.__new__(Subgoal)
        object.__setattr__(sg, "subgoal_id", "")
        object.__setattr__(sg, "goal", "Do something")
        object.__setattr__(sg, "context", {})
        object.__setattr__(sg, "metadata", {})
        object.__setattr__(sg, "canonical_hash", "abc123")
        object.__setattr__(sg, "state", SubgoalLifecycleState.PENDING)

        assert SubgoalValidator().validate(sg) is False

    def test_empty_goal_returns_false(self):
        sg = Subgoal.__new__(Subgoal)
        object.__setattr__(sg, "subgoal_id", "sg-1")
        object.__setattr__(sg, "goal", "")
        object.__setattr__(sg, "context", {})
        object.__setattr__(sg, "metadata", {})
        object.__setattr__(sg, "canonical_hash", "abc123")
        object.__setattr__(sg, "state", SubgoalLifecycleState.PENDING)

        assert SubgoalValidator().validate(sg) is False

    def test_empty_canonical_hash_returns_false(self):
        sg = Subgoal.__new__(Subgoal)
        object.__setattr__(sg, "subgoal_id", "sg-1")
        object.__setattr__(sg, "goal", "Do something")
        object.__setattr__(sg, "context", {})
        object.__setattr__(sg, "metadata", {})
        object.__setattr__(sg, "canonical_hash", "")
        object.__setattr__(sg, "state", SubgoalLifecycleState.PENDING)

        assert SubgoalValidator().validate(sg) is False

    def test_non_json_pure_context_returns_false(self):
        sg = SimpleNamespace(
            subgoal_id="sg-1",
            goal="Do something",
            context={"bad": set([1, 2])},  # not JSON-pure
            metadata={},
            canonical_hash="abc123",
        )
        assert SubgoalValidator().validate(sg) is False


# ── PlanSegmentValidator ──────────────────────────────────────────────────────

class TestPlanSegmentValidator:
    def test_valid_stub_passes_all_checks(self):
        PlanSegmentValidator.validate(_segment_stub())  # no exception

    def test_valid_stub_with_multiple_steps_passes(self):
        PlanSegmentValidator.validate(_segment_stub(steps=["s1", "s2", "s3"]))

    def test_valid_stub_with_context_and_metadata_passes(self):
        PlanSegmentValidator.validate(
            _segment_stub(context={"key": "value"}, metadata={"version": 2})
        )

    def test_empty_segment_id_returns_false(self):
        stub = _segment_stub(segment_id="")
        assert PlanSegmentValidator.validate(stub) is False

    def test_empty_subgoal_id_returns_false(self):
        stub = _segment_stub()
        stub.subgoal_id = ""
        stub.canonical_hash = stable_hash({"subgoal_id": "", "steps": stub.steps, "context": stub.context, "metadata": stub.metadata})
        assert PlanSegmentValidator.validate(stub) is False

    def test_non_list_steps_returns_false(self):
        stub = _segment_stub()
        stub.steps = "not a list"
        assert PlanSegmentValidator.validate(stub) is False

    def test_steps_with_non_string_item_returns_false(self):
        stub = _segment_stub(steps=["step-1", 42])
        stub.canonical_hash = stable_hash({"subgoal_id": stub.subgoal_id, "steps": ["step-1", 42], "context": stub.context, "metadata": stub.metadata})
        assert PlanSegmentValidator.validate(stub) is False

    def test_non_json_pure_context_raises(self):
        stub = _segment_stub()
        stub.context = {"bad": set([1, 2])}
        assert PlanSegmentValidator.validate(stub) is False

    def test_canonical_hash_mismatch_returns_false(self):
        stub = _segment_stub()
        stub.canonical_hash = "wrong_hash"
        assert PlanSegmentValidator.validate(stub) is False