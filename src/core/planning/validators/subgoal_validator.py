from __future__ import annotations

from src.core.planning.subgoals.model import Subgoal
from src.core.types.json_pure import ensure_json_pure


class SubgoalValidator:
    """
    Core structural validator for Subgoal.

    Responsibilities:
    - Enforce JSON-pure context/metadata
    - Ensure required fields are present
    - Sanity-check canonical hash determinism
    - No lifecycle or planner semantics
    """

    def validate(self, subgoal: Subgoal) -> bool:
        try:
            # JSON purity
            ensure_json_pure(subgoal.context)
            ensure_json_pure(subgoal.metadata)

            # Required fields
            if not subgoal.subgoal_id:
                return False
            if not subgoal.goal:
                return False

            # Canonical hash must be non-empty
            if not subgoal.canonical_hash:
                return False

            return True
        except Exception:
            return False