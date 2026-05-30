from src.core.types.errors import ValidationError
from src.core.types.json_pure import ensure_json_pure
from src.core.types.hashing import stable_hash
from src.core.types.plan_segment import PlanSegment


class PlanSegmentValidator:
    @staticmethod
    def validate(segment: PlanSegment) -> bool:
        try:
            # Required fields
            if not segment.segment_id:
                raise ValidationError("segment_id is required")

            if not segment.subgoal_id:
                raise ValidationError("subgoal_id is required")

            if not isinstance(segment.steps, list):
                raise ValidationError("steps must be a list")

            # Steps must be strings
            for step_id in segment.steps:
                if not isinstance(step_id, str):
                    raise ValidationError("steps must contain only string step_ids")

            # JSON purity
            ensure_json_pure(segment.context)
            ensure_json_pure(segment.metadata)

            # Canonical hash stability
            expected_hash = stable_hash(
                {
                    "subgoal_id": segment.subgoal_id,
                    "steps": segment.steps,
                    "context": segment.context,
                    "metadata": segment.metadata,
                }
            )

            if segment.canonical_hash != expected_hash:
                raise ValidationError("canonical_hash does not match computed hash")

            return True
        except Exception:
            return False