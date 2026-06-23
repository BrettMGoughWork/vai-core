"""Unit tests for TodoStore dependency resolution (Sprint 12a.10 / 12b.11).

Covers:
- get_next_pending() topological ordering
- Dependency-aware selection (skips blocked items)
- in_progress items first (crash recovery / resume)
- Retry mechanics (mark_failed with retries remaining vs exhausted)
- has_work_remaining(), is_complete(), get_status_counts()
- add_todos_batch() with dependencies
- Sub-goal operations: add_goal(), get_goals(), get_goal_tasks(),
  get_next_pending_for_goal(), append_progress()
- Two-level planning: goals interleaved with tasks in get_next_pending()
"""
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from src.capabilities.planner.todo_store import TodoStore


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def store(tmp_path: Any) -> TodoStore:
    """A fresh TodoStore backed by a temporary SQLite database."""
    db_path = str(tmp_path / "todos.db")
    TodoStore._ensure_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return TodoStore(conn)


# =========================================================================
# get_next_pending() — empty state
# =========================================================================


class TestGetNextPendingEmpty:
    def test_empty_db_returns_none(self, store: TodoStore) -> None:
        assert store.get_next_pending() is None

    def test_all_done_returns_none(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_done("a")
        assert store.get_next_pending() is None

    def test_all_failed_exhausted_returns_none(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        # Exhaust retries (default 3)
        store.mark_failed("a")
        store.mark_failed("a")
        store.mark_failed("a")
        assert store.get_next_pending() is None


# =========================================================================
# get_next_pending() — simple pending selection
# =========================================================================


class TestGetNextPendingSimple:
    def test_single_pending_returned(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "a"
        assert item.status == "pending"

    def test_returns_first_by_creation_order(self, store: TodoStore) -> None:
        store.add_todo("b", "B")
        store.add_todo("a", "A")
        item = store.get_next_pending()
        assert item is not None
        # 'b' was added first
        assert item.id == "b"

    def test_marks_in_progress(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_in_progress("a")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "a"
        assert item.status == "in_progress"


# =========================================================================
# get_next_pending() — dependency ordering
# =========================================================================


class TestGetNextPendingDependencies:
    def test_blocked_item_skipped_when_dep_pending(self, store: TodoStore) -> None:
        """B depends on A, A is still pending → B is skipped, A is returned."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_dep("b", "a")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "a"

    def test_blocked_item_returned_after_dep_done(self, store: TodoStore) -> None:
        """B depends on A, A is done → B is returned."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_dep("b", "a")
        store.mark_done("a")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "b"

    def test_diamond_dependency_respected(self, store: TodoStore) -> None:
        """D depends on B and C; B and C depend on A.
        A is returned first, then B or C after B and C are done → D returned."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        store.add_todo("d", "D")
        store.add_dep("b", "a")
        store.add_dep("c", "a")
        store.add_dep("d", "b")
        store.add_dep("d", "c")

        # First: only A is unblocked
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "a"

        # Mark A done → B and C become unblocked
        store.mark_done("a")
        item = store.get_next_pending()
        assert item is not None
        assert item.id in ("b", "c")
        first_of_bc = item.id

        # Mark the first B/C done — the other is still unblocked
        store.mark_done(first_of_bc)
        item = store.get_next_pending()
        assert item is not None
        assert item.id in ("b", "c")
        assert item.id != first_of_bc

        # D is still blocked (both B and C not yet done).
        # Mark the remaining B/C done → D becomes unblocked
        store.mark_done(item.id)
        item2 = store.get_next_pending()
        assert item2 is not None
        assert item2.id == "d"  # D is now unblocked

    def test_multiple_deps_all_must_be_done(self, store: TodoStore) -> None:
        """C depends on A and B — neither done → C blocked."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        store.add_dep("c", "a")
        store.add_dep("c", "b")

        # C is blocked; A or B returned first
        item = store.get_next_pending()
        assert item is not None
        assert item.id in ("a", "b")

        # Mark one done, the other pending — C still blocked
        store.mark_done(item.id)
        item2 = store.get_next_pending()
        assert item2 is not None
        assert item2.id in ("a", "b")
        assert item2.id != item.id


# =========================================================================
# get_next_pending() — in_progress items first (crash recovery/resume)
# =========================================================================


class TestGetNextPendingCrashRecovery:
    def test_in_progress_returned_before_pending(self, store: TodoStore) -> None:
        """When an item is in_progress (e.g., crash resume), it's returned first."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.mark_in_progress("b")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "b"
        assert item.status == "in_progress"

    def test_in_progress_item_after_reconnect(self, store: TodoStore) -> None:
        """Simulating a crash: item is left in_progress, reconnects and resumes it."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.mark_in_progress("b")
        # Simulate disconnect/reconnect with new TodoStore instance on same DB
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "b"

    def test_multiple_in_progress_returns_first(self, store: TodoStore) -> None:
        """Multiple in_progress items → first by created_at is returned."""
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        store.mark_in_progress("c")
        store.mark_in_progress("a")
        item = store.get_next_pending()
        assert item is not None
        # 'a' created before 'c'
        assert item.id == "a"


# =========================================================================
# has_work_remaining() / is_complete()
# =========================================================================


class TestWorkRemaining:
    def test_empty_db_no_work(self, store: TodoStore) -> None:
        assert store.has_work_remaining() is False

    def test_pending_items_have_work(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        assert store.has_work_remaining() is True

    def test_in_progress_items_have_work(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_in_progress("a")
        assert store.has_work_remaining() is True

    def test_done_items_no_work(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_done("a")
        assert store.has_work_remaining() is False

    def test_failed_exhausted_no_work(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_failed("a")  # 3→2
        store.mark_failed("a")  # 2→1
        store.mark_failed("a")  # 1→0, exhausted
        assert store.has_work_remaining() is False

    def test_mixed_statuses_has_work(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        store.mark_done("a")
        store.mark_failed("b")
        store.mark_failed("b")
        store.mark_failed("b")  # exhausted
        # c still pending
        assert store.has_work_remaining() is True


class TestIsComplete:
    def test_empty_db_is_complete(self, store: TodoStore) -> None:
        assert store.is_complete() is True

    def test_all_done_is_complete(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.mark_done("a")
        store.mark_done("b")
        assert store.is_complete() is True

    def test_pending_not_complete(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_done("a")
        store.add_todo("b", "B")  # still pending
        assert store.is_complete() is False

    def test_in_progress_not_complete(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_in_progress("a")
        assert store.is_complete() is False

    def test_failed_not_complete(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_failed("a")
        store.mark_failed("a")
        store.mark_failed("a")  # exhausted → failed
        assert store.is_complete() is False


# =========================================================================
# Status counts
# =========================================================================


class TestStatusCounts:
    def test_empty_db_all_zero(self, store: TodoStore) -> None:
        counts = store.get_status_counts()
        assert counts == {}

    def test_mixed_statuses(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.add_todo("b", "B")
        store.add_todo("c", "C")
        store.add_todo("d", "D")
        store.mark_done("a")
        store.mark_done("b")
        store.mark_in_progress("c")
        # d is pending

        counts = store.get_status_counts()
        assert counts.get("done") == 2
        assert counts.get("pending") == 1
        assert counts.get("in_progress") == 1


# =========================================================================
# mark_failed() — retry mechanics
# =========================================================================


class TestMarkFailedRetries:
    def test_has_retries_returns_true_and_resets_to_pending(self, store: TodoStore) -> None:
        store.add_todo("a", "A", retries_remaining=3)
        has_retries = store.mark_failed("a", "Oops")
        assert has_retries is True
        item = store.get("a")
        assert item is not None
        assert item.status == "pending"
        assert item.retries_remaining == 2
        assert item.error_message == "Oops"

    def test_exhausted_retries_returns_false_and_stays_failed(self, store: TodoStore) -> None:
        store.add_todo("a", "A", retries_remaining=3)
        store.mark_failed("a")  # 2 left
        store.mark_failed("a")  # 1 left
        has_retries = store.mark_failed("a", "Gave up")  # 0 left → exhausted
        assert has_retries is False
        item = store.get("a")
        assert item is not None
        assert item.status == "failed"
        assert item.retries_remaining == 0
        assert item.error_message == "Gave up"

    def test_nonexistent_id_returns_false(self, store: TodoStore) -> None:
        assert store.mark_failed("nonexistent") is False


# =========================================================================
# mark_blocked()
# =========================================================================


class TestMarkBlocked:
    def test_marks_blocked_with_reason(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_blocked("a", "Waiting for external API")
        item = store.get("a")
        assert item is not None
        assert item.status == "blocked"
        assert item.error_message == "Waiting for external API"

    def test_blocked_item_not_returned_by_get_next_pending(self, store: TodoStore) -> None:
        store.add_todo("a", "A")
        store.mark_blocked("a", "Blocked")
        assert store.get_next_pending() is None


# =========================================================================
# add_todos_batch() with dependencies
# =========================================================================


class TestAddTodosBatch:
    def test_batch_insert_with_deps(self, store: TodoStore) -> None:
        items = [
            {"id": "setup-db", "title": "Setting up database"},
            {"id": "setup-auth", "title": "Setting up auth"},
            {
                "id": "api-routes",
                "title": "Creating API routes",
                "depends_on": ["setup-db", "setup-auth"],
            },
        ]
        store.add_todos_batch(items)

        assert store.total_count() == 3
        api_routes = store.get("api-routes")
        assert api_routes is not None
        assert set(api_routes.depends_on) == {"setup-db", "setup-auth"}

    def test_batch_insert_retries_custom(self, store: TodoStore) -> None:
        items = [{"id": "a", "title": "A", "retries_remaining": 5}]
        store.add_todos_batch(items)
        item = store.get("a")
        assert item is not None
        assert item.retries_remaining == 5


# =========================================================================
# Sub-goal operations (Sprint 12b.11)
# =========================================================================


class TestAddGoal:
    """add_goal() inserts type='goal' items with completion_criterion."""

    def test_add_goal_creates_goal_type(self, store: TodoStore) -> None:
        store.add_goal("auth", "Auth Module", "Implement auth",
                       completion_criterion="All auth tests pass")
        item = store.get("auth")
        assert item is not None
        assert item.type == "goal"
        assert item.completion_criterion == "All auth tests pass"

    def test_add_goal_default_criterion_empty(self, store: TodoStore) -> None:
        store.add_goal("setup", "Setup", "Initial setup")
        item = store.get("setup")
        assert item is not None
        assert item.type == "goal"
        assert item.completion_criterion == ""

    def test_add_goal_appears_in_get_goals(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_goal("g2", "Goal 2")
        goals = store.get_goals()
        assert len(goals) == 2
        assert goals[0].id == "g1"
        assert goals[1].id == "g2"

    def test_goal_not_in_get_goals_for_tasks(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("t1", "Task 1", type="task")
        goals = store.get_goals()
        assert len(goals) == 1
        assert goals[0].id == "g1"


class TestGetGoalTasks:
    """get_goal_tasks() returns tasks parented to a specific goal."""

    def test_get_goal_tasks_empty(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        tasks = store.get_goal_tasks("g1")
        assert tasks == []

    def test_get_goal_tasks_returns_only_this_goal(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_goal("g2", "Goal 2")
        store.add_todo("g1-task1", "G1 Task 1", type="task", parent_goal_id="g1")
        store.add_todo("g1-task2", "G1 Task 2", type="task", parent_goal_id="g1")
        store.add_todo("g2-task1", "G2 Task 1", type="task", parent_goal_id="g2")

        g1_tasks = store.get_goal_tasks("g1")
        assert len(g1_tasks) == 2
        assert all(t.parent_goal_id == "g1" for t in g1_tasks)

        g2_tasks = store.get_goal_tasks("g2")
        assert len(g2_tasks) == 1
        assert g2_tasks[0].id == "g2-task1"

    def test_get_goal_tasks_non_existent_goal(self, store: TodoStore) -> None:
        tasks = store.get_goal_tasks("no-such-goal")
        assert tasks == []


class TestGetNextPendingForGoal:
    """get_next_pending_for_goal() returns the next ready task within a goal."""

    def test_returns_none_for_empty_goal(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        assert store.get_next_pending_for_goal("g1") is None

    def test_returns_first_pending_task(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("g1-t1", "Task 1", type="task", parent_goal_id="g1")
        store.add_todo("g1-t2", "Task 2", type="task", parent_goal_id="g1")
        item = store.get_next_pending_for_goal("g1")
        assert item is not None
        assert item.id == "g1-t1"

    def test_in_progress_returned_first(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("g1-t1", "Task 1", type="task", parent_goal_id="g1")
        store.add_todo("g1-t2", "Task 2", type="task", parent_goal_id="g1")
        store.mark_in_progress("g1-t2")
        item = store.get_next_pending_for_goal("g1")
        assert item is not None
        assert item.id == "g1-t2"

    def test_skips_blocked_task(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("g1-t1", "Task 1", type="task", parent_goal_id="g1")
        store.add_todo("g1-t2", "Task 2", type="task", parent_goal_id="g1")
        store.add_dep("g1-t2", "g1-t1")
        item = store.get_next_pending_for_goal("g1")
        assert item is not None
        assert item.id == "g1-t1"

    def test_returns_blocked_after_dep_done(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("g1-t1", "Task 1", type="task", parent_goal_id="g1")
        store.add_todo("g1-t2", "Task 2", type="task", parent_goal_id="g1")
        store.add_dep("g1-t2", "g1-t1")
        store.mark_done("g1-t1")
        item = store.get_next_pending_for_goal("g1")
        assert item is not None
        assert item.id == "g1-t2"


class TestAppendProgress:
    """append_progress() appends progress entries to a goal's description."""

    def test_appends_line_to_description(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1", "Initial description")
        store.append_progress("g1", "Created auth middleware")
        item = store.get("g1")
        assert item is not None
        assert "Initial description" in item.description
        assert "Created auth middleware" in item.description

    def test_multiple_progress_entries_accumulate(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1", "Base")
        store.append_progress("g1", "Step 1 done")
        store.append_progress("g1", "Step 2 done")
        item = store.get("g1")
        assert item is not None
        assert "Step 1 done" in item.description
        assert "Step 2 done" in item.description

    def test_progress_includes_timestamp(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1", "Base")
        store.append_progress("g1", "A task done")
        item = store.get("g1")
        assert item is not None
        assert "[progress]" in item.description


# =========================================================================
# Two-level planning: goals before tasks in get_next_pending() (12b.11)
# =========================================================================


class TestTwoLevelGetNextPending:
    """get_next_pending() returns goals before tasks when both are ready."""

    def test_goal_returned_before_ready_tasks(self, store: TodoStore) -> None:
        """Goals have priority over tasks so the system processes one sub-goal
        at a time rather than interleaving."""
        store.add_goal("g1", "Goal 1")
        store.add_todo("t1", "Task 1")
        item = store.get_next_pending()
        assert item is not None
        assert item.type == "goal"
        assert item.id == "g1"

    def test_task_returned_after_goal_done(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_todo("t1", "Independent task", type="task")
        store.mark_done("g1")
        item = store.get_next_pending()
        assert item is not None
        assert item.type == "task"
        assert item.id == "t1"

    def test_in_progress_goal_before_everything(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_goal("g2", "Goal 2")
        store.add_todo("t1", "Task 1")
        store.mark_in_progress("g2")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "g2"

    def test_multiple_goals_oldest_first(self, store: TodoStore) -> None:
        store.add_goal("g2", "Goal 2")
        store.add_goal("g1", "Goal 1")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "g2"

    def test_blocked_goal_skipped_for_next_ready_goal(self, store: TodoStore) -> None:
        store.add_goal("g1", "Goal 1")
        store.add_goal("g2", "Goal 2")
        store.add_dep("g2", "g1")
        item = store.get_next_pending()
        assert item is not None
        assert item.id == "g1"
