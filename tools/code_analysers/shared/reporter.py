import json
from dataclasses import asdict

class Reporter:
    def __init__(self, output_format: str, strict: bool):
        self.output_format = output_format
        self.strict = strict
        self._violations = []

    def add_violation(self, v):
        self._violations.append(v)

    def summary(self):
        errors = [v for v in self._violations if v.severity == "error"]
        warns = [v for v in self._violations if v.severity == "warn"]
        ok = len(errors) == 0 and (len(warns) == 0 or not self.strict)
        return type("Result", (), {"ok": ok, "errors": errors, "warnings": warns})

    def render(self):
        if self.output_format == "json":
            print(json.dumps([asdict(v) for v in self._violations], indent=2))
        else:
            for v in self._violations:
                loc = f"{v.file}" + (f":{v.line}" if v.line else "")
                print(f"[{v.severity.upper()}] {v.rule_id} @ {loc} - {v.message}")

            summary = self.summary()
            print(
                f"\nErrors: {len(summary.errors)}, Warnings: {len(summary.warnings)}, Strict: {self.strict}"
            )