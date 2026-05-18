from dataclasses import dataclass

@dataclass
class Violation:
    rule_id: str
    message: str
    file: str
    line: int | None = None
    severity: str = "error" # "error" or "warn"

class Rule:
    id: str
    description: str

    def run(self, ctx):
        raise NotImplementedError