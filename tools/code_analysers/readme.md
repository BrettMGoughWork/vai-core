# Code Analysers

Static enforcement tools for the Agent Runtime.

## Structure

- `shared/` — AST utilities, import graph, reporter, rule base
- `stratum1/` — Stratum 1 invariant checker
- `stratum2/` — (future) cognitive layer checker
- `stratum3/` — (future) planner/orchestrator checker

## Usage

```bash
python -m tools.code_analysers.stratum1.cli --strict