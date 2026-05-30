from src.core.types.core_step import CoreStep
from src.core.types.result import CoreResult

class MinimalCoreStepExecutor:
    """
    Minimal executor for 2.3.6.
    Does not call an LLM.
    Simply echoes the step payload.
    """

    def execute(self, step: CoreStep) -> CoreResult:
        return CoreResult.from_text(str(step.payload))
