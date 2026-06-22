"""Planner capability — todo-list planner (Sprint 12a).

A flat, SQLite-backed todo list that replaces the monolithic S2 hierarchical planner.

Modules:
    todo_store:  Pure data layer — SQLite CRUD for todos and dependencies.

Note: ``TodoWorker`` and ``TodoOrchestrator`` live in ``src.agent.planner``
since they orchestrate agent, workflow, and platform concerns (adapter stratum).
"""

from src.capabilities.planner.todo_store import TodoStore

__all__ = [
    "TodoStore",
]
