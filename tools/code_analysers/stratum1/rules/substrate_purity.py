from tools.code_analysers.shared.rule_base import Rule

class SubstratePurityRule(Rule):
    id = "S1-SUBSTRATE-PURITY"
    description = "Substrate must not import planner/orchestrator logic."

    def run(self, ctx):
        # Placeholder — fill in once Stratum 2 exists
        return []