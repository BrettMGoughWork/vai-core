from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from src.core.memory.semantic_memory_types import (
    SemanticMemoryRecord,
    SemanticMemorySnapshot,
)


# ---------------------------------------------------------------------------
# Deterministic scoring weights — pure S2, no ML.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SemanticIndexWeights:
    """
    Weights for deterministic scoring during similarity lookups.

    All weights are in [0.0, 1.0]. The combined score is a weighted sum of
    topic, entity, and capability-pattern overlap fractions.
    """

    topic: float = 0.4
    entity: float = 0.3
    capability: float = 0.3

    def __post_init__(self) -> None:
        for name, val in (("topic", self.topic), ("entity", self.entity), ("capability", self.capability)):
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} weight must be in [0.0, 1.0], got {val}")


def _jaccard(a: frozenset, b: frozenset) -> float:
    """Deterministic Jaccard similarity between two frozensets."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _score_record(
    record: SemanticMemoryRecord,
    query_topics: frozenset,
    query_entities: frozenset,
    query_capabilities: frozenset,
    weights: SemanticIndexWeights,
) -> float:
    """Compute a deterministic [0.0, 1.0] relevance score for a record."""
    topic_sim = _jaccard(frozenset(record.topics), query_topics)
    entity_sim = _jaccard(frozenset(record.entities), query_entities)
    cap_sim = _jaccard(frozenset(record.capability_patterns), query_capabilities)
    return (
        topic_sim * weights.topic
        + entity_sim * weights.entity
        + cap_sim * weights.capability
    )


# ---------------------------------------------------------------------------
# SemanticMemoryIndex
# ---------------------------------------------------------------------------

class SemanticMemoryIndex:
    """
    Deterministic index over SemanticMemoryRecords (pure S2).

    Provides:
    - Similar subgoal lookup (by topic / entity / capability overlap)
    - Similar drift lookup (same dimensions, filtered to memory_type="drift")
    - Similar capability-chain lookup (exact or prefix match on capability_patterns)
    - Historical outcome retrieval by source_id

    All lookups are deterministic — no embeddings, no LLM, no randomness.
    Embedding-based ranking occurs in S3 when available.
    """

    def __init__(self, weights: Optional[SemanticIndexWeights] = None) -> None:
        self._weights = weights or SemanticIndexWeights()
        self._records: Dict[str, SemanticMemoryRecord] = {}

        # --- inverted indices ---
        self._by_topic: Dict[str, Set[str]] = defaultdict(set)
        self._by_entity: Dict[str, Set[str]] = defaultdict(set)
        self._by_capability: Dict[str, Set[str]] = defaultdict(set)
        self._by_source: Dict[str, str] = {}       # source_id -> record_id
        self._by_memory_type: Dict[str, Set[str]] = defaultdict(set)
        self._by_outcome: Dict[str, Set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, record: SemanticMemoryRecord) -> None:
        """Index a record. Overwrites any existing record with the same record_id."""
        # Remove old indices if record_id already present
        if record.record_id in self._records:
            self.remove(record.record_id)

        self._records[record.record_id] = record
        self._by_source[record.source_id] = record.record_id
        self._by_memory_type[record.memory_type].add(record.record_id)
        self._by_outcome[record.outcome].add(record.record_id)

        for topic in record.topics:
            self._by_topic[topic].add(record.record_id)
        for entity in record.entities:
            self._by_entity[entity].add(record.record_id)
        for cap in record.capability_patterns:
            self._by_capability[cap].add(record.record_id)

    def remove(self, record_id: str) -> None:
        """Remove a record from the index by record_id. No-op if not present."""
        record = self._records.pop(record_id, None)
        if record is None:
            return

        self._by_source.pop(record.source_id, None)

        self._discard_and_prune(self._by_memory_type, record.memory_type, record_id)
        self._discard_and_prune(self._by_outcome, record.outcome, record_id)

        for topic in record.topics:
            self._discard_and_prune(self._by_topic, topic, record_id)
        for entity in record.entities:
            self._discard_and_prune(self._by_entity, entity, record_id)
        for cap in record.capability_patterns:
            self._discard_and_prune(self._by_capability, cap, record_id)

    @staticmethod
    def _discard_and_prune(
        mapping: Dict[str, Set[str]], key: str, record_id: str
    ) -> None:
        """Discard record_id from the set at mapping[key]; remove key if set becomes empty."""
        rids = mapping.get(key)
        if rids is None:
            return
        rids.discard(record_id)
        if not rids:
            del mapping[key]

    def clear(self) -> None:
        """Remove all records from the index."""
        self._records.clear()
        self._by_topic.clear()
        self._by_entity.clear()
        self._by_capability.clear()
        self._by_source.clear()
        self._by_memory_type.clear()
        self._by_outcome.clear()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(self, record_id: str) -> Optional[SemanticMemoryRecord]:
        """Retrieve a record by its unique id."""
        return self._records.get(record_id)

    def get_by_source(self, source_id: str) -> Optional[SemanticMemoryRecord]:
        """Retrieve a record by the source record id it enriches."""
        record_id = self._by_source.get(source_id)
        if record_id is None:
            return None
        return self._records.get(record_id)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, record_id: str) -> bool:
        return record_id in self._records

    def snapshot(self) -> SemanticMemorySnapshot:
        """Return an immutable snapshot of all records, sorted by created_at then record_id."""
        sorted_records = tuple(
            sorted(self._records.values(), key=lambda r: (r.created_at, r.record_id))
        )
        return SemanticMemorySnapshot(records=sorted_records)

    # ------------------------------------------------------------------
    # Deterministic similarity lookups
    # ------------------------------------------------------------------

    def find_similar_subgoals(
        self,
        topics: Sequence[str] = (),
        entities: Sequence[str] = (),
        capability_patterns: Sequence[str] = (),
        k: int = 5,
    ) -> List[SemanticMemoryRecord]:
        """
        Return the top-k SemanticMemoryRecords whose topics, entities, and
        capability patterns overlap with the query, ranked by deterministic score.

        Only records with memory_type="subgoal" are considered.
        """
        return self._find_similar(
            topics=topics,
            entities=entities,
            capability_patterns=capability_patterns,
            k=k,
            memory_type_filter="subgoal",
        )

    def find_similar_drifts(
        self,
        topics: Sequence[str] = (),
        entities: Sequence[str] = (),
        capability_patterns: Sequence[str] = (),
        k: int = 5,
    ) -> List[SemanticMemoryRecord]:
        """
        Return the top-k SemanticMemoryRecords for drift events, ranked by
        deterministic score with memory_type="drift".
        """
        return self._find_similar(
            topics=topics,
            entities=entities,
            capability_patterns=capability_patterns,
            k=k,
            memory_type_filter="drift",
        )

    def find_similar(
        self,
        topics: Sequence[str] = (),
        entities: Sequence[str] = (),
        capability_patterns: Sequence[str] = (),
        k: int = 5,
    ) -> List[SemanticMemoryRecord]:
        """
        Return the top-k SemanticMemoryRecords across ALL memory types,
        ranked by deterministic score.
        """
        return self._find_similar(
            topics=topics,
            entities=entities,
            capability_patterns=capability_patterns,
            k=k,
            memory_type_filter=None,
        )

    def _find_similar(
        self,
        topics: Sequence[str],
        entities: Sequence[str],
        capability_patterns: Sequence[str],
        k: int,
        memory_type_filter: Optional[str],
    ) -> List[SemanticMemoryRecord]:
        if k < 1:
            return []

        query_topics = frozenset(topics)
        query_entities = frozenset(entities)
        query_caps = frozenset(capability_patterns)
        is_empty_query = not topics and not entities and not capability_patterns

        # Collect candidate record_ids via inverted indices
        candidate_ids: Set[str] = set()
        for topic in topics:
            candidate_ids.update(self._by_topic.get(topic, ()))
        for entity in entities:
            candidate_ids.update(self._by_entity.get(entity, ()))
        for cap in capability_patterns:
            candidate_ids.update(self._by_capability.get(cap, ()))

        # If query is fully empty, consider all records of the filtered type
        if is_empty_query:
            if memory_type_filter is not None:
                candidate_ids = set(self._by_memory_type.get(memory_type_filter, ()))
            else:
                candidate_ids = set(self._records.keys())

        # Score and filter
        scored: List[Tuple[float, SemanticMemoryRecord]] = []
        for rid in candidate_ids:
            record = self._records.get(rid)
            if record is None:
                continue
            if memory_type_filter is not None and record.memory_type != memory_type_filter:
                continue
            if is_empty_query:
                # All candidates returned; score is 0 but we don't filter
                scored.append((0.0, record))
            else:
                score = _score_record(record, query_topics, query_entities, query_caps, self._weights)
                if score > 0.0:
                    scored.append((score, record))

        # Sort descending by score, then by created_at, then record_id for determinism
        scored.sort(key=lambda x: (-x[0], x[1].created_at, x[1].record_id))
        return [record for _, record in scored[:k]]

    # ------------------------------------------------------------------
    # Capability-chain lookup
    # ------------------------------------------------------------------

    def find_by_capability_chain(
        self, pattern: str, exact: bool = False
    ) -> List[SemanticMemoryRecord]:
        """
        Return all records whose capability_patterns include the given pattern.

        If exact is True, require an exact match. Otherwise, match any pattern
        that contains `pattern` as a substring (prefix/partial match).

        Results are sorted by created_at, then record_id.
        """
        results: List[SemanticMemoryRecord] = []
        for rid in self._by_capability.get(pattern, ()):
            record = self._records.get(rid)
            if record is not None:
                results.append(record)

        if not exact:
            # Also match records where pattern is a substring of any capability_pattern
            for cap, rids in self._by_capability.items():
                if cap == pattern:
                    continue  # already handled above
                if pattern in cap:
                    for rid in rids:
                        record = self._records.get(rid)
                        if record is not None and record not in results:
                            results.append(record)

        results.sort(key=lambda r: (r.created_at, r.record_id))
        return results

    # ------------------------------------------------------------------
    # Historical outcome retrieval
    # ------------------------------------------------------------------

    def historical_outcomes(self, source_id: str) -> List[str]:
        """
        Return all recorded outcomes for a given source_id, in chronological order.

        If no record exists for the source_id, returns an empty list.
        """
        record = self.get_by_source(source_id)
        if record is None:
            return []
        return [record.outcome]

    def outcome_counts(self) -> Dict[str, int]:
        """
        Return a mapping of outcome -> count across all indexed records.
        """
        return {outcome: len(rids) for outcome, rids in self._by_outcome.items()}

    def records_by_outcome(self, outcome: str) -> List[SemanticMemoryRecord]:
        """
        Return all records with the given outcome, sorted by created_at then record_id.
        """
        rids = self._by_outcome.get(outcome, ())
        results = [self._records[rid] for rid in rids if rid in self._records]
        results.sort(key=lambda r: (r.created_at, r.record_id))
        return results
