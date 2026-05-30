class AgentDispatcher:
    """
    Modern dispatcher API:
        dispatch(state) -> step
    """

    def dispatch(self, state):
        """
        Old API expected: dispatch(state, signals)
        New API removes signals entirely.
        """

        # If your old dispatcher used signals, adapt here:
        # signals = None

        # If your old dispatcher used plan extraction, adapt here:
        # plan = self._build_plan_from_state(state)

        # For now, return a simple step object that your executor understands.
        # Replace this with your actual logic.
        return {
            "type": "llm_step",
            "input": state.input,
        }