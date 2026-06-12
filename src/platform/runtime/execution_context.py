"""ExecutionContext v1 — Stratum-4 runtime.

A pure data envelope that carries cognitive state, last result, memory
snapshots, and a cycle trace across execution cycles.  Fully opaque to S4
— S4 stores and forwards but never inspects the contents.

Fields:
    cognitive_state: Opaque dict for S2/S3 cognitive state.
    last_result:     Opaque dict for the last step result.
    memory:          Opaque dict for memory snapshots.
    cycle_trace:     Append-only list of cycle event dicts.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionContext(BaseModel):
    """Envelope for cross-cycle cognitive state, results, and memory.

    All cognitive fields are opaque to Stratum-4 — they are JSON blobs
    that only Stratum-2 and Stratum-3 are expected to read and write.
    S4 stores, serialises, and forwards them without inspection.
    """

    cognitive_state: dict = Field(default_factory=dict)
    last_result: dict | None = None
    memory: dict = Field(default_factory=dict)
    cycle_trace: list[dict] = Field(default_factory=list)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Dehydrate to a plain JSON-serialisable dict."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutionContext":
        """Hydrate from a plain dict."""
        return cls.model_validate(data)
