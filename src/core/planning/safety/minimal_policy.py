class MinimalSafetyPolicy:
    """
    No-ope safety policy for testing and development.
    Always returns safe for any tool and does not trigger self-healing.
    """

    def pre_step(self, state, step):
        # Allow all steps
        return None
    
    def post_step(self, state, result):
        # Allow all results
        return None