import ast
from pathlib import Path
from tools.code_analysers.shared.rule_base import Rule, Violation

class EventEnvelopeRule(Rule):
    id = "S1-EVENT-ENVELOPE"
    description = "EventEnvelope must expose required fields."

    def run(self, ctx):
        violations = []
        path = Path(ctx.config["event_envelope_module"]).resolve()
        required = {"id", "timestamp", "payload", "source"}

        if path not in ctx.files:
            return violations

        tree = ast.parse(path.read_text(), filename=str(path))

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "EventEnvelope":
                fields = {
                    n.target.id
                    for n in node.body
                    if isinstance(n, ast.AnnAssign)
                }
                missing = required - fields
                if missing:
                    violations.append(
                        Violation(
                            rule_id=self.id,
                            message=f"Missing fields: {', '.join(sorted(missing))}",
                            file=str(path),
                            line=node.lineno,
                        )
                    )
        return violations