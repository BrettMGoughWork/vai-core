class MinimalSafetyPolicy:
    """
    Minimal safety policy compatible with the new SafeStepDispatcher API.
    """

    def pre_execute(self, ctx):
        # old method name compatibility
        if hasattr(self, "check_pre"):
            return self.check_pre(ctx)
        return None

    def post_execute(self, ctx, result):
        # old method name compatibility
        if hasattr(self, "check_post"):
            return self.check_post(ctx, result)
        return None
