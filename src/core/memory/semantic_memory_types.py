from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from src.core.types.json_pure import ensure_json_pure


# ---------------------------------------------------------------------------
# Outcome classification constants (string-based, following the project
# convention of storing enum-like values as plain strings for JSON purity).
# ---------------------------------------------------------------------------
VALID_OUTCOMES = frozenset({"success", "partial_success", "failure", "unknown"})


@dataclass(frozen=True)
class SemanticMemoryRecord:
    """
    Meaning-aware memory record that enriches existing memory types (subgoal,
    segment, plan, drift) with semantic metadata.

    This is a pure-S2 structure. Embedding vectors are precomputed in S3 and
    attached here. The record is JSON-serialisable and immutable.

    Fields
    ------
    record_id:
        Unique identifier for this semantic record.
    memory_type:
        Which memory store the source record belongs to:
        "subgoal" | "segment" | "plan" | "drift".
    source_id:
        The id of the underlying source record (e.g. subgoal_id, plan_id).
    topics:
        Ordered tuple of topic strings extracted from the source content.
        Topics are deterministic — derived from capability names, intent
        keywords, or LLM prompts in higher strata.
    entities:
        Ordered tuple of named entities (tools, skills, argument keys, etc.).
    capability_patterns:
        Ordered tuple of capability chains observed during execution.
        Each entry is a "/" delimited path (e.g. "stdlib.echo → stdlib.read").
    embedding_vector:
        Precomputed embedding of the source content (S3 responsibility).
        None when no embedding has been computed.
    outcome:
        Classified outcome: "success" | "partial_success" | "failure" | "unknown".
    metadata:
        Arbitrary JSON-pure payload. Deep-copied at construction.
    created_at:
        Logical timestamp in ms (consistent with GovernedSignal / StepContext).
    """

    record_id: str
    memory_type: str
    source_id: str
    topics: Tuple[str, ...]
    entities: Tuple[str, ...]
    capability_patterns: Tuple[str, ...]
    embedding_vector: Optional[Tuple[float, ...]]
    outcome: str
    metadata: Dict[str, Any]
    created_at: int

    def __post_init__(self) -> None:
        # --- field presence ---
        if not self.record_id:
            raise ValueError("record_id must be non-empty")
        if not self.source_id:
            raise ValueError("source_id must be non-empty")
        if self.memory_type not in ("subgoal", "segment", "plan", "drift"):
            raise ValueError(
                f"memory_type must be one of subgoal|segment|plan|drift, got {self.memory_type!r}"
            )
        if self.outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, got {self.outcome!r}"
            )
        if self.created_at < 0:
            raise ValueError(f"created_at must be >= 0, got {self.created_at}")

        # --- embedding_vector validation ---
        if self.embedding_vector is not None:
            if not isinstance(self.embedding_vector, tuple):
                raise ValueError("embedding_vector must be a tuple of floats or None")
            if len(self.embedding_vector) == 0:
                raise ValueError("embedding_vector must be None or non-empty tuple")
            for i, v in enumerate(self.embedding_vector):
                if not isinstance(v, (int, float)):
                    raise ValueError(
                        f"embedding_vector[{i}] must be float, got {type(v).__name__}"
                    )

        # --- metadata purity ---
        ensure_json_pure(self.metadata)
        object.__setattr__(self, "metadata", copy.deepcopy(self.metadata))


@dataclass(frozen=True)
class SemanticMemorySnapshot:
    """
    Immutable ordered collection of SemanticMemoryRecords.

    records is a tuple to satisfy frozen dataclass requirements.
    Order is deterministic (sorted by created_at, then record_id).
    """

    records: Tuple[SemanticMemoryRecord, ...]
