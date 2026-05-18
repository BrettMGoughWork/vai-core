from pathlib import Path
from tools.code_analysers.shared.rule_base import Rule, Violation

class FolderBoundariesRule(Rule):
    id = "S1-FOLDER-BOUNDARIES"
    description = "Stratum 1 modules must not import forbidden Stratum 2 modules."

    def run(self, ctx):
        violations = []

        allowed = [Path(p).resolve() for p in ctx.config["stratum1_allowed_roots"]]
        forbidden = [Path(p).resolve() for p in ctx.config["stratum1_forbidden_roots"]]

        for path in ctx.files:
            path_resolved = path.resolve()

            # Only check files inside allowed roots
            if not any(str(path_resolved).startswith(str(a)) for a in allowed):
                continue

            module = ctx.module_for_path(path)
            imports = ctx.import_graph.get(module, set())

            for imp in imports:
                for f in forbidden:
                    if imp.startswith(f.name):
                        violations.append(
                            Violation(
                                rule_id=self.id,
                                message=f"Stratum 1 module {module} imports forbidden module '{imp}'.",
                                file=str(path),
                            )
                        )
        return violations