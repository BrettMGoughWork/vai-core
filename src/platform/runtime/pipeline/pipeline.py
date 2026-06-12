"""EvaluatorPipeline — ordered stage runner."""

from __future__ import annotations

from src.platform.runtime.job import Job
from src.platform.runtime.pipeline.base import PipelineContext, PipelineStage


class EvaluatorPipeline:
    """Runs an ordered list of :class:`PipelineStage` instances.

    Each stage receives the mutable :class:`PipelineContext` and may return
    the :class:`Job` to short-circuit the pipeline.  The first stage that
    returns a non-``None`` value wins; all subsequent stages are skipped.
    """

    def __init__(self, stages: list[PipelineStage]) -> None:
        if not stages:
            raise ValueError("EvaluatorPipeline requires at least one stage")
        self._stages = list(stages)

    def run(self, ctx: PipelineContext) -> Job:
        """Run all stages in order.

        Args:
            ctx: Mutable pipeline context.

        Returns:
            The :class:`Job` as returned by the winning stage.
        """
        for stage in self._stages:
            result = stage.evaluate(ctx)
            if result is not None:
                return result
        # Guaranteed unreachable if the final stage always returns the job.
        return ctx.job
