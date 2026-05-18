from pathlib import Path
from tools.code_analysers.shared.rule_base import Rule, Violation

class NoLLMRule(Rule):
    id = "S1-NO-LLM"
    description = "Stratum 1 must not import LLM client libraries."

    def run(self, ctx):
        violations = []

        # Resolve allowed Stratum 1 roots
        allowed_roots = [Path(p).resolve() for p in ctx.config["stratum1_allowed_roots"]]
        forbidden = set(ctx.config["llm_modules_forbidden"])

        for path in ctx.files:
            path_resolved = path.resolve()

            # Only enforce rule inside Stratum 1 allowed roots
            if not any(str(path_resolved).startswith(str(a)) for a in allowed_roots):
                continue

            module = ctx.module_for_path(path)
            imports = ctx.import_graph.get(module, set())

            for imp in imports:
                if imp in forbidden:
                    violations.append(
                        Violation(
                            rule_id=self.id,
                            message=f"Forbidden LLM import '{imp}' in Stratum 1 module '{module}'.",
                            file=str(path),
                        )
                    )

        return violations