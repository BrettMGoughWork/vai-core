"""
SQLite-backed AgentStateStore — transactional snapshots, single file.

Atomicity
---------
Each ``save()`` is wrapped in a transaction.  If the write fails or the
process crashes mid-write, the previous snapshot remains intact.

Schema
------
.. code-block:: sql

    CREATE TABLE IF NOT EXISTS agent_state (
        agent_id     TEXT PRIMARY KEY,
        version      INTEGER NOT NULL,
        schema_version INTEGER NOT NULL DEFAULT 1,
        blob         TEXT NOT NULL,       -- JSON-serialised AgentState
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL
    );

Each row holds the most recent snapshot for a given agent.  Old versions
are overwritten (last-write-wins concurrency).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from src.agent.interfaces.agent_state import AgentState
from src.agent.interfaces.agent_state_store import AgentStateStore, StoreError


class SQLiteAgentStateStore(AgentStateStore):
    """SQLite-backed agent state store.

    Single file, transactional writes.  One row per agent.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._init_db()

    # ── Public API ──────────────────────────────────────────────────────

    def save(self, agent_id: str, state: AgentState) -> None:
        if not agent_id:
            raise StoreError("agent_id must be non-empty")

        serialised = self._serialise(state)
        now = _now()

        with closing(sqlite3.connect(str(self._db_path))) as conn:
            conn.execute("BEGIN")
            try:
                conn.execute(
                    """
                    INSERT INTO agent_state (agent_id, version, schema_version,
                                             blob, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        version = excluded.version,
                        schema_version = excluded.schema_version,
                        blob = excluded.blob,
                        updated_at = excluded.updated_at
                    """,
                    (
                        agent_id,
                        state.version,
                        1,
                        serialised,
                        state.timestamps.get("created_at", now),
                        now,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise StoreError(
                    f"failed to save state for agent {agent_id!r}: {exc}"
                ) from exc

    def load(self, agent_id: str) -> Optional[AgentState]:
        if not agent_id:
            raise StoreError("agent_id must be non-empty")

        with closing(sqlite3.connect(str(self._db_path))) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT blob FROM agent_state WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()

        if row is None:
            return None

        try:
            return self._deserialise(row["blob"])
        except (json.JSONDecodeError, ValueError) as exc:
            raise StoreError(
                f"failed to deserialise state for agent {agent_id!r}: {exc}"
            ) from exc

    def list_agent_ids(self) -> List[str]:
        with closing(sqlite3.connect(str(self._db_path))) as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agent_state ORDER BY agent_id"
            ).fetchall()
        return [r[0] for r in rows]

    # ── Internals ───────────────────────────────────────────────────────

    @staticmethod
    def _serialise(state: AgentState) -> str:
        import dataclasses
        d = dataclasses.asdict(state)
        d["_schema_version"] = 1
        return json.dumps(d, default=str)

    @staticmethod
    def _deserialise(raw: str) -> AgentState:
        d: Dict = json.loads(raw)
        d.pop("_schema_version", None)

        from src.agent.interfaces.agent_state import LifecycleState
        ls_val = d.get("lifecycle_state", "created")
        if isinstance(ls_val, str):
            d["lifecycle_state"] = LifecycleState(ls_val)

        from src.agent.interfaces.agent_state import LifecycleEvent
        if "lifecycle_history" in d and isinstance(d["lifecycle_history"], list):
            d["lifecycle_history"] = [
                LifecycleEvent(**ev) if isinstance(ev, dict) else ev
                for ev in d["lifecycle_history"]
            ]

        if "pending_intents" in d and isinstance(d["pending_intents"], list):
            from src.agent.contracts import ActionIntent
            d["pending_intents"] = [
                ActionIntent(**ai) if isinstance(ai, dict) else ai
                for ai in d["pending_intents"]
            ]

        if "activation_snapshot" in d and isinstance(d["activation_snapshot"], dict):
            from src.agent.activation import ActivatedAgentContext
            d["activation_snapshot"] = _rehydrate_activation_context(
                d["activation_snapshot"]
            )

        if "dispatch_result" in d and isinstance(d["dispatch_result"], dict):
            from src.agent.job_interface import JobDispatchResult
            dr = d["dispatch_result"]
            d["dispatch_result"] = JobDispatchResult(
                dispatched_jobs=dr.get("dispatched_jobs", []),
                terminal_intents=dr.get("terminal_intents", []),
                errors=[tuple(e) if isinstance(e, list) else e
                        for e in dr.get("errors", [])],
            )

        return AgentState(**d)

    def _init_db(self) -> None:
        """Create the schema if it doesn't exist."""
        with closing(sqlite3.connect(str(self._db_path))) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_state (
                    agent_id       TEXT PRIMARY KEY,
                    version        INTEGER NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    blob           TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                )
                """
            )
            conn.commit()


def _rehydrate_activation_context(d: Dict) -> "ActivatedAgentContext":
    """Rehydrate an ActivatedAgentContext from a dict."""
    from src.agent.activation import ActivatedAgentContext
    from src.agent.contracts import AgentMessage

    msg = d.get("message", {})
    if isinstance(msg, dict):
        d["message"] = AgentMessage(**msg)

    return ActivatedAgentContext(**d)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
