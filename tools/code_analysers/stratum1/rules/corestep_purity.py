import ast
from pathlib import Path
from tools.code_analysers.shared.rule_base import Rule, Violation

class CoreStepPurityRule(Rule):
    id = "S1-CORESTEP-PURITY"
    description = "CoreStep must remain pure and free of side-effectful imports."

    def run(self, ctx):
        violations = []
        path = Path(ctx.config["corestep_module"]).resolve()
        forbidden = {"requests", "httpx", "openai", "subprocess"}

        if path not in ctx.files:
            return violations

        tree = ast.parse(path.read_text(), filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name.split(".")[0] in forbidden:
                        violations.append(
                            Violation(
                                rule_id=self.id,
                                message=f"CoreStep imports forbidden module '{n.name}'.",
                                file=str(path),
                                line=node.lineno,
                            )
                        )
        return violations