from __future__ import annotations

import json
import pytest

from src.strategy.memory.semantic_memory_types import (
    SemanticMemoryRecord,
    SemanticMemorySnapshot,
    VALID_OUTCOMES,
)


# ============================================================================
# Construction — happy paths
# ============================================================================

class TestSemanticMemoryRecordConstruction:
    """Successful construction with valid arguments."""

    def test_minimal_construction(self):
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="plan-abc",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=0,
        )
        assert record.record_id == "sem-001"
        assert record.memory_type == "plan"
        assert record.source_id == "plan-abc"
        assert record.topics == ()
        assert record.entities == ()
        assert record.capability_patterns == ()
        assert record.embedding_vector is None
        assert record.outcome == "unknown"
        assert record.metadata == {}
        assert record.created_at == 0

    def test_full_construction_with_embedding(self):
        record = SemanticMemoryRecord(
            record_id="sem-002",
            memory_type="subgoal",
            source_id="sg-xyz",
            topics=("fetch", "http", "api"),
            entities=("github", "rest"),
            capability_patterns=("stdlib.fetch → stdlib.parse",),
            embedding_vector=(0.1, 0.2, 0.3),
            outcome="success",
            metadata={"confidence": 0.95},
            created_at=1700000000000,
        )
        assert record.topics == ("fetch", "http", "api")
        assert record.entities == ("github", "rest")
        assert record.capability_patterns == ("stdlib.fetch → stdlib.parse",)
        assert record.embedding_vector == (0.1, 0.2, 0.3)
        assert record.outcome == "success"
        assert record.metadata == {"confidence": 0.95}

    @pytest.mark.parametrize("memory_type", ["subgoal", "segment", "plan", "drift"])
    def test_all_valid_memory_types(self, memory_type):
        record = SemanticMemoryRecord(
            record_id="sem-003",
            memory_type=memory_type,
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=1,
        )
        assert record.memory_type == memory_type

    @pytest.mark.parametrize("outcome", sorted(VALID_OUTCOMES))
    def test_all_valid_outcomes(self, outcome):
        record = SemanticMemoryRecord(
            record_id="sem-004",
            memory_type="plan",
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome=outcome,
            metadata={},
            created_at=1,
        )
        assert record.outcome == outcome

    def test_embedding_vector_with_ints_converted(self):
        """Ints in embedding_vector are accepted (float-compatible)."""
        record = SemanticMemoryRecord(
            record_id="sem-005",
            memory_type="segment",
            source_id="seg-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=(0, 1, 0),
            outcome="failure",
            metadata={},
            created_at=1,
        )
        assert record.embedding_vector == (0, 1, 0)


# ============================================================================
# Construction — validation failures
# ============================================================================

class TestSemanticMemoryRecordValidation:
    """Construction rejects invalid arguments."""

    def test_empty_record_id_raises(self):
        with pytest.raises(ValueError, match="record_id"):
            SemanticMemoryRecord(
                record_id="",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata={},
                created_at=0,
            )

    def test_empty_source_id_raises(self):
        with pytest.raises(ValueError, match="source_id"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata={},
                created_at=0,
            )

    def test_invalid_memory_type_raises(self):
        with pytest.raises(ValueError, match="memory_type"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="invalid_type",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata={},
                created_at=0,
            )

    def test_invalid_outcome_raises(self):
        with pytest.raises(ValueError, match="outcome"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="invalid_outcome",
                metadata={},
                created_at=0,
            )

    def test_negative_created_at_raises(self):
        with pytest.raises(ValueError, match="created_at"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata={},
                created_at=-1,
            )

    def test_empty_embedding_vector_raises(self):
        with pytest.raises(ValueError, match="embedding_vector"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=(),
                outcome="unknown",
                metadata={},
                created_at=0,
            )

    def test_non_float_in_embedding_vector_raises(self):
        with pytest.raises(ValueError, match="embedding_vector"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=(0.1, "bad", 0.3),  # type: ignore[arg-type]
                outcome="unknown",
                metadata={},
                created_at=0,
            )

    def test_non_json_pure_metadata_raises(self):
        with pytest.raises(TypeError, match="JSON"):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata={"fn": lambda x: x},  # type: ignore[dict-item]
                created_at=0,
            )

    def test_circular_reference_metadata_raises(self):
        circ: dict = {}
        circ["self"] = circ
        with pytest.raises((TypeError, ValueError)):
            SemanticMemoryRecord(
                record_id="sem-001",
                memory_type="plan",
                source_id="src-1",
                topics=(),
                entities=(),
                capability_patterns=(),
                embedding_vector=None,
                outcome="unknown",
                metadata=circ,
                created_at=0,
            )


# ============================================================================
# Immutability & deep-copy safety
# ============================================================================

class TestSemanticMemoryRecordImmutability:
    """Records are frozen and protect against external mutation."""

    def test_record_is_frozen(self):
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=0,
        )
        with pytest.raises(Exception):
            record.record_id = "changed"  # type: ignore[misc]

    def test_metadata_deep_copy_prevents_mutation(self):
        mutable_meta = {"key": ["original"]}
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata=mutable_meta,
            created_at=0,
        )
        # Mutate the original dict — must not affect the stored record
        mutable_meta["key"].append("mutated")
        mutable_meta["new_key"] = "added"
        assert record.metadata == {"key": ["original"]}

    def test_topics_are_tuple(self):
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="src-1",
            topics=("a", "b"),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=0,
        )
        with pytest.raises(Exception):
            record.topics[0] = "changed"  # type: ignore[index]


# ============================================================================
# JSON round-trip
# ============================================================================

class TestSemanticMemoryRecordSerialization:
    """Records can be serialized to and from JSON."""

    def test_json_round_trip_minimal(self):
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=0,
        )
        data = json.dumps(record.__dict__)
        reloaded = json.loads(data)
        assert reloaded["record_id"] == "sem-001"
        assert reloaded["outcome"] == "unknown"
        assert reloaded["embedding_vector"] is None

    def test_json_round_trip_full(self):
        record = SemanticMemoryRecord(
            record_id="sem-002",
            memory_type="subgoal",
            source_id="sg-abc",
            topics=("fetch", "api"),
            entities=("github",),
            capability_patterns=("stdlib.echo",),
            embedding_vector=(0.1, 0.2),
            outcome="partial_success",
            metadata={"attempts": 3},
            created_at=1700000000000,
        )
        data = json.dumps(record.__dict__)
        reloaded = json.loads(data)
        assert reloaded["topics"] == ["fetch", "api"]
        assert reloaded["entities"] == ["github"]
        assert reloaded["capability_patterns"] == ["stdlib.echo"]
        assert reloaded["embedding_vector"] == [0.1, 0.2]
        assert reloaded["outcome"] == "partial_success"
        assert reloaded["metadata"] == {"attempts": 3}


# ============================================================================
# SemanticMemorySnapshot
# ============================================================================

class TestSemanticMemorySnapshot:
    """SemanticMemorySnapshot collects records immutably."""

    def test_empty_snapshot(self):
        snap = SemanticMemorySnapshot(records=())
        assert snap.records == ()
        assert len(snap.records) == 0

    def test_single_record_snapshot(self):
        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="plan",
            source_id="src-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="unknown",
            metadata={},
            created_at=1000,
        )
        snap = SemanticMemorySnapshot(records=(record,))
        assert len(snap.records) == 1
        assert snap.records[0].record_id == "sem-001"

    def test_multiple_records_preserve_order(self):
        r1 = SemanticMemoryRecord(
            record_id="sem-a",
            memory_type="subgoal",
            source_id="sg-1",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="success",
            metadata={},
            created_at=1000,
        )
        r2 = SemanticMemoryRecord(
            record_id="sem-b",
            memory_type="subgoal",
            source_id="sg-2",
            topics=(),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="failure",
            metadata={},
            created_at=2000,
        )
        snap = SemanticMemorySnapshot(records=(r1, r2))
        assert snap.records[0].record_id == "sem-a"
        assert snap.records[1].record_id == "sem-b"

    def test_snapshot_is_frozen(self):
        snap = SemanticMemorySnapshot(records=())
        with pytest.raises(Exception):
            snap.records = ()  # type: ignore[misc]

    def test_snapshot_json_round_trip(self):
        from dataclasses import asdict

        record = SemanticMemoryRecord(
            record_id="sem-001",
            memory_type="drift",
            source_id="drift-1",
            topics=("drift",),
            entities=(),
            capability_patterns=(),
            embedding_vector=None,
            outcome="failure",
            metadata={},
            created_at=1,
        )
        snap = SemanticMemorySnapshot(records=(record,))
        data = json.dumps(asdict(snap))
        reloaded = json.loads(data)
        assert len(reloaded["records"]) == 1
        assert reloaded["records"][0]["record_id"] == "sem-001"