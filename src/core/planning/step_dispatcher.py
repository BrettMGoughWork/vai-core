class StepDispatcher:
    """
    Executes a single validated plan step via CoreStepV2.
    """

    def __init__(self, core_step: CoreStepV2):
        self.core_step = core_step

    def dispatch(self, plan: Plan) -> tuple[StepState, StepResult]:
        # Build a StepState for execution
        state = StepState(
            step_id="plan_execute",
            parent_id=None,
            cognitive_input={
                "mode": "execute",
                "targetSkillId": plan.targetskillid,
                "arguments": plan.arguments,
            },
            last_result=None,
            status=StepStatus.PENDING,
            created_at=0,
            attempt=0,
            trace=[],
            canonical_hash="plan_execute",
        )

        return self.core_step.run(state)