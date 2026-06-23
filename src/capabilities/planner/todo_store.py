"""TodoStore — Pure data layer for the todo-list planner (Sprint 12a.2 / 12b.1).

Manages the ``todos`` and ``todo_deps`` SQLite tables. Supports a two-level
planning model: ``type='goal'`` items (sub-goals, coarse milestones) and
``type='task'`` items (dynamically-discovered tasks within a sub-goal).

No S4 or agent knowledge — just a plain Python class that operates on a
``sqlite3.Connection``.

Usage::

    store = TodoStore(conn)
    store.ensure_tables()
    store.add_goal("auth-module", "Auth Module", "Implement complete auth system",
                    completion_criterion="All auth endpoints pass integration tests")
    store.add_todo("create-jwt", "Creating JWT middleware", "...",
                    type="task", parent_goal_id="auth-module")
    next_item = store.get_next_pending()  # respects deps, goals before tasks
    store.mark_done("create-jwt")
"""

from __future__ import annotations

import datetime
import sqlite3
from dataclasses import dataclass, field


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_TODOS = """
CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    type TEXT DEFAULT 'task',
    parent_goal_id TEXT,
    retries_remaining INTEGER DEFAULT 3,
    error_message TEXT DEFAULT '',
    completion_criterion TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_CREATE_DEPS = """
CREATE TABLE IF NOT EXISTS todo_deps (
    todo_id TEXT NOT NULL REFERENCES todos(id),
    depends_on TEXT NOT NULL REFERENCES todos(id),
    goal_id TEXT REFERENCES todos(id),
    PRIMARY KEY (todo_id, depends_on)
)
"""

# ── Data model ────────────────────────────────────────────────────────────────

_VALID_STATUSES = frozenset({"pending", "in_progress", "done", "failed", "blocked"})
_VALID_TYPES = frozenset({"task", "goal"})


@dataclass
class TodoItem:
    """A single todo row, populated from the database."""

    id: str
    title: str
    description: str = ""
    status: str = "pending"
    type: str = "task"
    parent_goal_id: str = ""
    retries_remaining: int = 3
    error_message: str = ""
    completion_criterion: str = ""
    created_at: str = ""
    updated_at: str = ""
    depends_on: list[str] = field(default_factory=list)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ── TodoStore ─────────────────────────────────────────────────────────────────


class TodoStore:
    """Pure data layer for a single todo-list plan backed by SQLite.

    Args:
        conn: An open ``sqlite3.Connection``.  The caller is responsible for
              connection lifecycle (open, close, commit).  Row factory should
              be ``sqlite3.Row`` for dict-like access.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── schema management ─────────────────────────────────────────────────

    @staticmethod
    def _ensure_table(db_path: str) -> None:
        """Convenience: open ``db_path``, create tables, migrate, and close.

        Useful in tests and one-off setup scripts where you don't want to
        manage the connection lifecycle yourself.
        """
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(_CREATE_TODOS)
            conn.execute(_CREATE_DEPS)
            _run_migration(conn)
            conn.commit()
        finally:
            conn.close()

    def ensure_tables(self) -> None:
        """Create the ``todos`` and ``todo_deps`` tables if they do not exist.

        Also runs the schema migration so pre-existing DBs from 12a are
        upgraded to the 12b schema automatically.
        """
        self._conn.execute(_CREATE_TODOS)
        self._conn.execute(_CREATE_DEPS)
        _run_migration(self._conn)
        self._conn.commit()

    # ── CRUD ───────────────────────────────────────────────────────────────

    def add_todo(
        self,
        todo_id: str,
        title: str,
        description: str = "",
        *,
        type: str = "task",
        parent_goal_id: str = "",
        completion_criterion: str = "",
        retries_remaining: int = 3,
    ) -> None:
        """Insert a new todo item (task or goal).

        Args:
            todo_id:               Unique kebab-case identifier.
            title:                 Human-readable gerund-form title.
            description:           Sufficient detail to execute without context.
            type:                  ``"task"`` (default) or ``"goal"``.
            parent_goal_id:        For tasks: the id of the owning sub-goal.
            completion_criterion:  For goals: a verifiable condition that
                                    signals the sub-goal is done.
            retries_remaining:     Maximum retry count (default 3).

        Raises:
            sqlite3.IntegrityError: If ``todo_id`` already exists.
            ValueError: If ``type`` is not ``"task"`` or ``"goal"``.
        """
        if type not in _VALID_TYPES:
            raise ValueError(
                f"Invalid type {type!r}; must be one of {sorted(_VALID_TYPES)}"
            )
        now = _now_iso()
        self._conn.execute(
            """INSERT INTO todos (id, title, description, status, type,
               parent_goal_id, completion_criterion, retries_remaining,
               created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
            (
                todo_id, title, description, type, parent_goal_id or "",
                completion_criterion, retries_remaining, now, now,
            ),
        )
        self._conn.commit()

    def add_todos_batch(self, items: list[dict]) -> None:
        """Insert multiple todos in a single transaction.

        Each dict must have ``id``, ``title``, and optionally ``description``,
        ``type``, ``parent_goal_id``, ``completion_criterion``,
        ``retries_remaining``, and ``depends_on`` (list of todo ids).
        """
        now = _now_iso()
        with self._conn:
            for item in items:
                item_type = item.get("type", "task")
                self._conn.execute(
                    """INSERT OR IGNORE INTO todos (id, title, description, status,
                       type, parent_goal_id, completion_criterion,
                       retries_remaining, created_at, updated_at)
                       VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
                    (
                        item["id"],
                        item["title"],
                        item.get("description", ""),
                        item_type,
                        item.get("parent_goal_id", ""),
                        item.get("completion_criterion", ""),
                        item.get("retries_remaining", 3),
                        now,
                        now,
                    ),
                )
                for dep_id in item.get("depends_on", []):
                    self._conn.execute(
                        "INSERT OR IGNORE INTO todo_deps (todo_id, depends_on, goal_id) VALUES (?, ?, ?)",
                        (
                            item["id"],
                            dep_id,
                            item.get("parent_goal_id", ""),
                        ),
                    )

    def add_goal(
        self,
        goal_id: str,
        title: str,
        description: str = "",
        *,
        completion_criterion: str = "",
        retries_remaining: int = 3,
    ) -> None:
        """Insert a new sub-goal item.

        Convenience wrapper around ``add_todo`` that sets ``type='goal'``.
        """
        self.add_todo(
            goal_id,
            title,
            description,
            type="goal",
            completion_criterion=completion_criterion,
            retries_remaining=retries_remaining,
        )

    def get(self, todo_id: str) -> TodoItem | None:
        """Return a single todo by id, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM todos WHERE id = ?", (todo_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_item(row, self._conn)

    def get_all(self) -> list[TodoItem]:
        """Return every todo, in insertion order."""
        rows = self._conn.execute(
            "SELECT * FROM todos ORDER BY created_at"
        ).fetchall()
        return [_row_to_item(r, self._conn) for r in rows]

    def get_goals(self) -> list[TodoItem]:
        """Return all sub-goal (``type='goal'``) items in insertion order."""
        rows = self._conn.execute(
            "SELECT * FROM todos WHERE type = 'goal' ORDER BY created_at"
        ).fetchall()
        return [_row_to_item(r, self._conn) for r in rows]

    def get_goal_tasks(self, goal_id: str) -> list[TodoItem]:
        """Return all tasks belonging to ``goal_id``, in insertion order."""
        rows = self._conn.execute(
            "SELECT * FROM todos WHERE parent_goal_id = ? AND type = 'task' "
            "ORDER BY created_at",
            (goal_id,),
        ).fetchall()
        return [_row_to_item(r, self._conn) for r in rows]

    def get_next_pending_for_goal(self, goal_id: str) -> TodoItem | None:
        """Return the next pending task for ``goal_id`` whose deps are met.

        Used by the inner ReAct loop to dynamically select the first/next
        task within a sub-goal.  Only considers tasks that belong to
        ``goal_id`` *and* have no unsatisfied dependencies.
        """
        # 1. In-progress task for this goal?
        row = self._conn.execute(
            "SELECT * FROM todos WHERE parent_goal_id = ? AND type = 'task' "
            "AND status = 'in_progress' ORDER BY created_at LIMIT 1",
            (goal_id,),
        ).fetchone()
        if row is not None:
            return _row_to_item(row, self._conn)

        # 2. Pending task with all deps done.
        row = self._conn.execute(
            """SELECT t.* FROM todos t
               WHERE t.parent_goal_id = ? AND t.type = 'task'
               AND t.status = 'pending'
               AND NOT EXISTS (
                   SELECT 1 FROM todo_deps td
                   JOIN todos dep ON td.depends_on = dep.id
                   WHERE td.todo_id = t.id AND dep.status != 'done'
               )
               ORDER BY t.created_at
               LIMIT 1""",
            (goal_id,),
        ).fetchone()
        if row is not None:
            return _row_to_item(row, self._conn)

        return None

    def append_progress(self, goal_id: str, summary: str) -> None:
        """Append a one-line progress entry to the goal's description.

        Used by the inner ReAct loop for *progress compaction* — after
        each task completes the loop appends a brief summary so the
        anchor/adviser context stays bounded (max ~30 lines) while still
        conveying what has been accomplished so far.
        """
        now = _now_iso()
        line = f"\n[progress] {now}: {summary}"
        self._conn.execute(
            "UPDATE todos SET description = description || ?, updated_at = ? "
            "WHERE id = ?",
            (line, now, goal_id),
        )
        self._conn.commit()

    def get_status_counts(self) -> dict[str, int]:
        """Return ``{status: count}`` for all statuses currently in the list."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM todos GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ── next-item selection (topological) ──────────────────────────────────

    def get_next_pending(self) -> TodoItem | None:
        """Return the next todo that is ready to execute.

        Priority:
            1. Any item already ``in_progress`` (resume after crash).
            2. Pending **goals** whose dependencies are all ``done``.
            3. Pending **tasks** whose dependencies are all ``done``.

        Goals are prioritised over sibling tasks so that the system
        completes one sub-goal before moving on to the next, even when
        tasks for multiple goals are ready.

        Returns ``None`` when every item is ``done``, ``failed``, or
        ``blocked`` (or the list is empty).
        """
        # 1. Resume — pick up any in_progress item first.
        row = self._conn.execute(
            "SELECT * FROM todos WHERE status = 'in_progress' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is not None:
            return _row_to_item(row, self._conn)

        # 2. Pending goals with all deps satisfied — oldest first.
        row = self._conn.execute(
            """SELECT t.* FROM todos t
               WHERE t.status = 'pending'
               AND t.type = 'goal'
               AND NOT EXISTS (
                   SELECT 1 FROM todo_deps td
                   JOIN todos dep ON td.depends_on = dep.id
                   WHERE td.todo_id = t.id AND dep.status != 'done'
               )
               ORDER BY t.created_at
               LIMIT 1"""
        ).fetchone()
        if row is not None:
            return _row_to_item(row, self._conn)

        # 3. Pending tasks with all deps satisfied.
        row = self._conn.execute(
            """SELECT t.* FROM todos t
               WHERE t.status = 'pending'
               AND t.type = 'task'
               AND NOT EXISTS (
                   SELECT 1 FROM todo_deps td
                   JOIN todos dep ON td.depends_on = dep.id
                   WHERE td.todo_id = t.id AND dep.status != 'done'
               )
               ORDER BY t.created_at
               LIMIT 1"""
        ).fetchone()
        if row is not None:
            return _row_to_item(row, self._conn)

        return None

    def has_work_remaining(self) -> bool:
        """Return ``True`` if there are pending or in_progress items left."""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM todos WHERE status IN ('pending', 'in_progress')"
        ).fetchone()
        return row is not None and row["cnt"] > 0

    # ── status transitions ─────────────────────────────────────────────────

    def mark_in_progress(self, todo_id: str) -> None:
        """Move a pending item to in_progress."""
        self._conn.execute(
            "UPDATE todos SET status = 'in_progress', updated_at = ? WHERE id = ? AND status = 'pending'",
            (_now_iso(), todo_id),
        )
        self._conn.commit()

    def mark_done(self, todo_id: str) -> None:
        """Mark a todo as successfully completed."""
        self._conn.execute(
            "UPDATE todos SET status = 'done', updated_at = ? WHERE id = ?",
            (_now_iso(), todo_id),
        )
        self._conn.commit()

    def mark_failed(self, todo_id: str, error_message: str = "") -> bool:
        """Mark a todo as failed, decrementing retries_remaining.

        Returns ``True`` if the item still has retries remaining (caller
        should re-queue it as ``pending``).  Returns ``False`` if retries
        are exhausted — the item stays ``failed``.
        """
        row = self._conn.execute(
            "SELECT retries_remaining FROM todos WHERE id = ?", (todo_id,)
        ).fetchone()
        if row is None:
            return False

        remaining = row["retries_remaining"] - 1
        if remaining > 0:
            # Still has retries — reset to pending for another attempt.
            self._conn.execute(
                """UPDATE todos SET status = 'pending', retries_remaining = ?,
                   error_message = ?, updated_at = ? WHERE id = ?""",
                (remaining, error_message, _now_iso(), todo_id),
            )
            self._conn.commit()
            return True
        else:
            # Exhausted — stay failed.
            self._conn.execute(
                "UPDATE todos SET status = 'failed', retries_remaining = 0, "
                "error_message = ?, updated_at = ? WHERE id = ?",
                (error_message, _now_iso(), todo_id),
            )
            self._conn.commit()
            return False

    def mark_blocked(self, todo_id: str, reason: str = "") -> None:
        """Mark a todo as blocked (cannot proceed until a dependency resolves)."""
        self._conn.execute(
            "UPDATE todos SET status = 'blocked', error_message = ?, updated_at = ? WHERE id = ?",
            (reason, _now_iso(), todo_id),
        )
        self._conn.commit()

    # ── dependencies ───────────────────────────────────────────────────────

    def add_dep(self, todo_id: str, depends_on: str) -> None:
        """Declare that ``todo_id`` depends on ``depends_on``.

        Safe to call multiple times — duplicate deps are silently ignored.
        """
        self._conn.execute(
            "INSERT OR IGNORE INTO todo_deps (todo_id, depends_on) VALUES (?, ?)",
            (todo_id, depends_on),
        )
        self._conn.commit()

    def get_deps(self, todo_id: str) -> list[str]:
        """Return the ids of all items that ``todo_id`` depends on."""
        rows = self._conn.execute(
            "SELECT depends_on FROM todo_deps WHERE todo_id = ?", (todo_id,)
        ).fetchall()
        return [r["depends_on"] for r in rows]

    def get_dependents(self, todo_id: str) -> list[str]:
        """Return the ids of all items that depend on ``todo_id``."""
        rows = self._conn.execute(
            "SELECT todo_id FROM todo_deps WHERE depends_on = ?", (todo_id,)
        ).fetchall()
        return [r["todo_id"] for r in rows]

    # ── statistics ─────────────────────────────────────────────────────────

    def total_count(self) -> int:
        """Return the total number of todos."""
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM todos").fetchone()
        return row["cnt"] if row else 0

    def done_count(self) -> int:
        """Return the number of completed todos."""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM todos WHERE status = 'done'"
        ).fetchone()
        return row["cnt"] if row else 0

    def is_complete(self) -> bool:
        """Return ``True`` when all todos are done (no pending, in_progress, or blocked)."""
        return self.done_count() == self.total_count()


# ── helpers ───────────────────────────────────────────────────────────────────


def _row_to_item(row: sqlite3.Row, conn: sqlite3.Connection) -> TodoItem:
    """Convert a ``sqlite3.Row`` into a ``TodoItem``, including deps."""
    deps_rows = conn.execute(
        "SELECT depends_on FROM todo_deps WHERE todo_id = ?", (row["id"],)
    ).fetchall()
    return TodoItem(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        status=row["status"],
        type=row["type"] if "type" in row.keys() else "task",
        parent_goal_id=row["parent_goal_id"] or "" if "parent_goal_id" in row.keys() else "",
        retries_remaining=row["retries_remaining"],
        error_message=row["error_message"] or "",
        completion_criterion=row["completion_criterion"] or "" if "completion_criterion" in row.keys() else "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        depends_on=[r["depends_on"] for r in deps_rows],
    )


def _run_migration(conn: sqlite3.Connection) -> None:
    """Migrate pre-Sprint-12b ``todos`` / ``todo_deps`` tables.

    Idempotent — safe to call on already-migrated databases.
    Adds ``type``, ``parent_goal_id``, and ``completion_criterion``
    to ``todos``, and ``goal_id`` to ``todo_deps``, if they are missing.
    """
    try:
        conn.execute("ALTER TABLE todos ADD COLUMN type TEXT DEFAULT 'task'")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        conn.execute("ALTER TABLE todos ADD COLUMN parent_goal_id TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE todos ADD COLUMN completion_criterion TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE todo_deps ADD COLUMN goal_id TEXT REFERENCES todos(id)")
    except sqlite3.OperationalError:
        pass
