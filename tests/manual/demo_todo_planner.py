"""Manual smoke-test: run the Todo-List Planner with verbose output.

Usage:
    python tests/manual/demo_todo_planner.py

Creates an in-memory todo list with dependencies, simulates the worker
processing loop, and prints results at each step.
"""

import logging
import sys

from src.capabilities.planner.todo_store import TodoStore


def main():
    store = TodoStore(":memory:")

    # Create a realistic dependency chain
    store.add_todo("design-db", "Designing the database schema", "Define tables, relations, and indexes")
    store.add_todo("write-models", "Writing SQLAlchemy models", "Implement ORM models matching the schema")
    store.add_todo("write-tests", "Writing unit tests for models", "Test CRUD, constraints, and edge cases")
    store.add_todo("write-api", "Writing REST API endpoints", "Expose CRUD via FastAPI routes")
    store.add_todo("integrate", "Integration testing the full stack", "End-to-end test of API → DB flow")

    # Set dependencies: models depend on design; tests & API depend on models;
    # integration depends on everything
    store.add_dep("write-models", "design-db")
    store.add_dep("write-tests", "write-models")
    store.add_dep("write-api", "write-models")
    store.add_dep("integrate", "write-tests")
    store.add_dep("integrate", "write-api")

    print("=== Initial Todo List ===")
    _print_list(store)

    # Simulate the worker loop: pick the next pending unblocked item,
    # mark it in_progress, then mark it done. Repeat.
    print("\n=== Simulating Worker Loop ===")
    step = 0
    while store.has_work_remaining():
        step += 1
        next_item = store.get_next_pending()
        if next_item is None:
            print(f"  Step {step}: No unblocked pending items — blocked by dependencies")
            # Show what's blocking
            for item in store.get_all():
                if item.status == "blocked":
                    deps = store.get_deps(item.id)
                    print(f"    [{item.id}] blocked by: {deps}")
            break

        print(f"  Step {step}: [{next_item.id}] pending → in_progress")
        store.mark_in_progress(next_item.id)

        # Simulate work (in reality the todo-execute-item workflow would run here)
        import time
        time.sleep(0.1)

        print(f"  Step {step}: [{next_item.id}] in_progress → done ✓")
        store.mark_done(next_item.id)

    print("\n=== Final Todo List ===")
    _print_list(store)

    counts = store.get_status_counts()
    print(f"\nDone: {counts.get('done', 0)}, Pending: {counts.get('pending', 0)}, "
          f"In Progress: {counts.get('in_progress', 0)}, "
          f"Blocked: {counts.get('blocked', 0)}, "
          f"Failed: {counts.get('failed', 0)}")
    print(f"Complete: {store.is_complete()}")


def _print_list(store: TodoStore) -> None:
    for item in store.get_all():
        deps = store.get_deps(item.id)
        dep_str = f" → deps={deps}" if deps else ""
        print(f"  [{item.status:12}] {item.id:20s} {item.title}{dep_str}")


if __name__ == "__main__":
    main()

