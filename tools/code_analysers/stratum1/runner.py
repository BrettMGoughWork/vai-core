from tools.code_analysers.shared.fs_walker import collect_python_files
from tools.code_analysers.shared.import_graph import build_import_graph
from tools.code_analysers.shared.reporter import Reporter
from tools.code_analysers.shared.context import CheckerContext
from .rules import load_rules

def run_checks(root: str, output_format: str, strict: bool):
    files = collect_python_files(root)
    import_graph = build_import_graph(files)

    ctx = CheckerContext(
        root=root,
        files=files,
        import_graph=import_graph,
        config=_default_config(root),
    )

    rules = load_rules()
    reporter = Reporter(output_format=output_format, strict=strict)

    for rule in rules:
        for v in rule.run(ctx):
            reporter.add_violation(v)

    reporter.render()
    return reporter.summary()

def _default_config(root: str):
    return {
        "stratum1_allowed_roots": [
            "src/core/config",
            "src/core/llm",
            "src/core/types",
            "src/core/skills",
            "src/core/errors",
            "src/execution",
            "src/governance",
            "src/observability",
            "src/policy",
            "src/skills",
            "src/primitives",
            "src/telemetry",
        ],
        "stratum1_forbidden_roots": [
            "src/core/planning",
            "src/core/agent",
        ],
        "llm_modules_forbidden": ["openai", "anthropic", "litellm", "vertexai"],
        "corestep_module": "src/core/agent/core_step.py",
        "event_envelope_module": "src/core/types/event_envelope.py",
    }