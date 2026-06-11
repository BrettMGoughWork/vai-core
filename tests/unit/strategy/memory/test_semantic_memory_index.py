from __future__ import annotations

import pytest

from src.strategy.memory.semantic_memory_index import (
    SemanticIndexWeights,
    SemanticMemoryIndex,
    _jaccard,
    _score_record,
)
from src.strategy.memory.semantic_memory_types import SemanticMemoryRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    record_id: str = "sem-001",
    memory_type: str = "subgoal",
    source_id: str = "sg-1",
    topics: tuple = (),
    entities: tuple = (),
    capability_patterns: tuple = (),
    embedding_vector: tuple | None = None,
    outcome: str = "unknown",
    metadata: dict | None = None,
    created_at: int = 1000,
) -> SemanticMemoryRecord:
    return SemanticMemoryRecord(
        record_id=record_id,
        memory_type=memory_type,
        source_id=source_id,
        topics=topics,
        entities=entities,
        capability_patterns=capability_patterns,
        embedding_vector=embedding_vector,
        outcome=outcome,
        metadata=metadata or {},
        created_at=created_at,
    )


# ============================================================================
# SemanticIndexWeights
# ============================================================================

class TestSemanticIndexWeights:
    def test_default_weights(self):
        w = SemanticIndexWeights()
        assert w.topic == 0.4
        assert w.entity == 0.3
        assert w.capability == 0.3

    def test_custom_weights(self):
        w = SemanticIndexWeights(topic=0.5, entity=0.2, capability=0.3)
        assert w.topic == 0.5
        assert w.entity == 0.2
        assert w.capability == 0.3

    def test_weights_frozen(self):
        w = SemanticIndexWeights()
        with pytest.raises(Exception):
            w.topic = 0.9  # type: ignore[misc]

    @pytest.mark.parametrize("field", ["topic", "entity", "capability"])
    def test_out_of_range_raises(self, field):
        with pytest.raises(ValueError, match=field):
            SemanticIndexWeights(**{field: 1.5})  # type: ignore[arg-type]
        with pytest.raises(ValueError, match=field):
            SemanticIndexWeights(**{field: -0.1})  # type: ignore[arg-type]


# ============================================================================
# Jaccard helper
# ============================================================================

class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard(frozenset("abc"), frozenset("abc")) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard(frozenset("abc"), frozenset("xyz")) == 0.0

    def test_partial_overlap(self):
        assert _jaccard(frozenset("ab"), frozenset("bc")) == 1.0 / 3.0

    def test_both_empty(self):
        assert _jaccard(frozenset(), frozenset()) == 0.0

    def test_one_empty(self):
        assert _jaccard(frozenset("abc"), frozenset()) == 0.0


# ============================================================================
# SemanticMemoryIndex — mutation
# ============================================================================

class TestIndexMutation:
    def test_add_and_get(self):
        idx = SemanticMemoryIndex()
        rec = _make_record(record_id="r1", topics=("http",))
        idx.add(rec)
        assert idx.get("r1") is rec
        assert "r1" in idx
        assert len(idx) == 1

    def test_add_duplicate_overwrites(self):
        idx = SemanticMemoryIndex()
        r1 = _make_record(record_id="r1", topics=("http",), outcome="success")
        r2 = _make_record(record_id="r1", topics=("fetch",), outcome="failure")
        idx.add(r1)
        idx.add(r2)
        assert len(idx) == 1
        assert idx.get("r1") is r2
        assert idx.get("r1").topics == ("fetch",)
        # Old topic should be cleaned from inverted index
        assert idx.find_similar(topics=("http",)) == []
        assert len(idx.find_similar(topics=("fetch",))) == 1

    def test_remove(self):
        idx = SemanticMemoryIndex()
        rec = _make_record(record_id="r1")
        idx.add(rec)
        idx.remove("r1")
        assert len(idx) == 0
        assert idx.get("r1") is None
        assert "r1" not in idx

    def test_remove_nonexistent_noop(self):
        idx = SemanticMemoryIndex()
        idx.remove("nonexistent")  # no error

    def test_clear(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1"))
        idx.add(_make_record(record_id="r2"))
        idx.clear()
        assert len(idx) == 0

    def test_get_by_source(self):
        idx = SemanticMemoryIndex()
        rec = _make_record(record_id="r1", source_id="sg-5")
        idx.add(rec)
        assert idx.get_by_source("sg-5") is rec
        assert idx.get_by_source("nonexistent") is None


# ============================================================================
# Snapshots
# ============================================================================

class TestSnapshot:
    def test_empty_snapshot(self):
        idx = SemanticMemoryIndex()
        snap = idx.snapshot()
        assert snap.records == ()

    def test_snapshot_sorted_by_created_at(self):
        idx = SemanticMemoryIndex()
        r1 = _make_record(record_id="r1", created_at=3000)
        r2 = _make_record(record_id="r2", created_at=1000)
        r3 = _make_record(record_id="r3", created_at=2000)
        idx.add(r1)
        idx.add(r2)
        idx.add(r3)
        snap = idx.snapshot()
        assert [r.record_id for r in snap.records] == ["r2", "r3", "r1"]

    def test_snapshot_tiebreak_by_record_id(self):
        idx = SemanticMemoryIndex()
        r1 = _make_record(record_id="b", created_at=1000)
        r2 = _make_record(record_id="a", created_at=1000)
        idx.add(r1)
        idx.add(r2)
        snap = idx.snapshot()
        assert [r.record_id for r in snap.records] == ["a", "b"]


# ============================================================================
# Deterministic similarity lookups
# ============================================================================

class TestFindSimilar:
    def test_exact_match_scores_highest(self):
        idx = SemanticMemoryIndex()
        exact = _make_record(
            record_id="exact",
            topics=("http", "fetch"),
            entities=("github",),
            capability_patterns=("stdlib.fetch",),
        )
        partial = _make_record(
            record_id="partial",
            topics=("http",),
            entities=(),
            capability_patterns=(),
        )
        none = _make_record(
            record_id="none",
            topics=("unrelated",),
            entities=(),
            capability_patterns=(),
        )
        idx.add(exact)
        idx.add(partial)
        idx.add(none)

        results = idx.find_similar(
            topics=("http", "fetch"),
            entities=("github",),
            capability_patterns=("stdlib.fetch",),
            k=5,
        )
        assert results[0].record_id == "exact"
        assert "partial" in [r.record_id for r in results]
        assert results[-1].record_id != "none"

    def test_k_limit(self):
        idx = SemanticMemoryIndex()
        for i in range(10):
            idx.add(_make_record(record_id=f"r{i}", topics=(f"topic{i%3}",)))
        results = idx.find_similar(topics=("topic0",), k=3)
        assert len(results) == 3

    def test_empty_index_returns_empty(self):
        idx = SemanticMemoryIndex()
        assert idx.find_similar(topics=("x",)) == []

    def test_empty_query_returns_all(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", memory_type="subgoal"))
        idx.add(_make_record(record_id="r2", memory_type="subgoal"))
        results = idx.find_similar()
        assert len(results) == 2

    def test_empty_query_with_k_smaller(self):
        idx = SemanticMemoryIndex()
        for i in range(5):
            idx.add(_make_record(record_id=f"r{i}"))
        results = idx.find_similar(k=2)
        assert len(results) == 2

    def test_k_zero_returns_empty(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", topics=("http",)))
        assert idx.find_similar(topics=("http",), k=0) == []

    def test_no_overlap_returns_empty(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", topics=("http",)))
        assert idx.find_similar(topics=("unrelated",)) == []

    def test_deterministic_ordering(self):
        """Same query always returns same order."""
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="a", topics=("http",), created_at=1000))
        idx.add(_make_record(record_id="b", topics=("http",), created_at=2000))
        idx.add(_make_record(record_id="c", topics=("http",), created_at=500))
        results1 = idx.find_similar(topics=("http",))
        results2 = idx.find_similar(topics=("http",))
        assert [r.record_id for r in results1] == [r.record_id for r in results2]


class TestFindSimilarSubgoals:
    def test_only_subgoals_returned(self):
        idx = SemanticMemoryIndex()
        sg = _make_record(record_id="sg", memory_type="subgoal", topics=("http",))
        plan = _make_record(record_id="plan", memory_type="plan", topics=("http",))
        idx.add(sg)
        idx.add(plan)
        results = idx.find_similar_subgoals(topics=("http",))
        assert len(results) == 1
        assert results[0].record_id == "sg"

    def test_empty_result_when_no_subgoals(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="p1", memory_type="plan", topics=("http",)))
        assert idx.find_similar_subgoals(topics=("http",)) == []


class TestFindSimilarDrifts:
    def test_only_drifts_returned(self):
        idx = SemanticMemoryIndex()
        drift = _make_record(record_id="d1", memory_type="drift", topics=("timeout",))
        sg = _make_record(record_id="sg", memory_type="subgoal", topics=("timeout",))
        idx.add(drift)
        idx.add(sg)
        results = idx.find_similar_drifts(topics=("timeout",))
        assert len(results) == 1
        assert results[0].record_id == "d1"


# ============================================================================
# Capability-chain lookup
# ============================================================================

class TestFindByCapabilityChain:
    def test_exact_match(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", capability_patterns=("stdlib.echo",)))
        idx.add(_make_record(record_id="r2", capability_patterns=("stdlib.fetch",)))
        results = idx.find_by_capability_chain("stdlib.echo", exact=True)
        assert len(results) == 1
        assert results[0].record_id == "r1"

    def test_partial_match(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", capability_patterns=("stdlib.echo → stdlib.fetch",)))
        idx.add(_make_record(record_id="r2", capability_patterns=("stdlib.read",)))
        results = idx.find_by_capability_chain("stdlib.echo", exact=False)
        assert len(results) == 1
        assert results[0].record_id == "r1"

    def test_partial_match_multiple(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", capability_patterns=("stdlib.echo → stdlib.fetch",)))
        idx.add(_make_record(record_id="r2", capability_patterns=("stdlib.echo → stdlib.read",)))
        results = idx.find_by_capability_chain("stdlib", exact=False)
        assert len(results) == 2

    def test_no_match(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", capability_patterns=("stdlib.echo",)))
        assert idx.find_by_capability_chain("stdlib.missing") == []


# ============================================================================
# Historical outcome retrieval
# ============================================================================

class TestHistoricalOutcomes:
    def test_outcome_for_existing_source(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", source_id="sg-1", outcome="success"))
        assert idx.historical_outcomes("sg-1") == ["success"]

    def test_outcome_for_missing_source(self):
        idx = SemanticMemoryIndex()
        assert idx.historical_outcomes("nonexistent") == []

    def test_outcome_counts(self):
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="r1", outcome="success"))
        idx.add(_make_record(record_id="r2", outcome="success"))
        idx.add(_make_record(record_id="r3", outcome="failure"))
        counts = idx.outcome_counts()
        assert counts["success"] == 2
        assert counts["failure"] == 1
        assert counts.get("unknown", 0) == 0

    def test_records_by_outcome(self):
        idx = SemanticMemoryIndex()
        r1 = _make_record(record_id="r1", outcome="failure", created_at=1000)
        r2 = _make_record(record_id="r2", outcome="failure", created_at=500)
        idx.add(r1)
        idx.add(r2)
        idx.add(_make_record(record_id="r3", outcome="success"))
        results = idx.records_by_outcome("failure")
        assert len(results) == 2
        assert results[0].record_id == "r2"  # earlier created_at

    def test_records_by_outcome_empty(self):
        idx = SemanticMemoryIndex()
        assert idx.records_by_outcome("success") == []


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    def test_remove_cleans_inverted_indices(self):
        idx = SemanticMemoryIndex()
        rec = _make_record(
            record_id="r1",
            topics=("http",),
            entities=("github",),
            capability_patterns=("stdlib.echo",),
            outcome="success",
            memory_type="subgoal",
            source_id="sg-1",
        )
        idx.add(rec)
        idx.remove("r1")

        assert idx.get_by_source("sg-1") is None
        assert idx.find_similar(topics=("http",)) == []
        assert idx.find_similar(entities=("github",)) == []
        assert idx.find_by_capability_chain("stdlib.echo") == []
        assert idx.find_similar_subgoals(topics=("http",)) == []
        assert idx.outcome_counts() == {}

    def test_mixed_query_ranking(self):
        """Entity + topic overlap ranks above topic-only overlap."""
        idx = SemanticMemoryIndex()
        idx.add(_make_record(record_id="both", topics=("http",), entities=("github",)))
        idx.add(_make_record(record_id="topic_only", topics=("http",), entities=()))
        results = idx.find_similar(topics=("http",), entities=("github",))
        assert results[0].record_id == "both"
        assert results[1].record_id == "topic_only"

    def test_custom_weights_affect_ranking(self):
        idx = SemanticMemoryIndex(
            weights=SemanticIndexWeights(topic=0.1, entity=0.8, capability=0.1)
        )
        idx.add(_make_record(record_id="entity_match", entities=("github",)))
        idx.add(_make_record(record_id="topic_match", topics=("http",)))
        results = idx.find_similar(topics=("http",), entities=("github",))
        # entity weight is higher, so entity_match should rank above topic_match
        assert results[0].record_id == "entity_match"
        assert results[1].record_id == "topic_match"