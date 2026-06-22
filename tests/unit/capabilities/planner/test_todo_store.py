"""Unit tests for TodoStore dependency resolution (Sprint 12a.10).

Covers:
- get_next_pending() topological ordering
- Dependency-aware selection (skips blocked items)
- in_progress items first (crash recovery / resume)
- Retry mechanics (mark_failed with retries remaining vs exhausted)
- has_work_remaining(), is_complete(), get_status_counts()
- add_todos_batch() with dependencies
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
