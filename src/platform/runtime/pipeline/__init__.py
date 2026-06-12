"""Worker pipeline — composable pre-flight and execution stages for S4 runtime."""

from src.platform.runtime.pipeline.base import (
    PipelineContext,
    PipelineStage,
)
from src.platform.runtime.pipeline.pipeline import EvaluatorPipeline
from src.platform.runtime.pipeline.stages import (
    CrashRecoveryStage,
    IdempotencyStage,
    DegradedModeStage,
    ExecutionStage,
)

__all__ = [
    "PipelineContext",
    "PipelineStage",
    "EvaluatorPipeline",
    "CrashRecoveryStage",
    "IdempotencyStage",
    "DegradedModeStage",
    "ExecutionStage",
]
