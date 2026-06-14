"""
File-backed AgentStateStore — durable JSON snapshots, one file per agent.

Atomicity
---------
Writes use a temp-file + rename pattern: write to temporary file,
then ``os.replace()`` to ``<agent_id>.json``.  This prevents partial
writes from corrupting the snapshot.

If the process crashes during a write, the previous snapshot (if any)
remains intact.

Layout
------
All agent files live under a single directory (``storage_dir``).
Each agent is stored as ``<storage_dir>/<agent_id>.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from src.agent.interfaces.agent_state import AgentState
from src.agent.interfaces.agent_state_store import AgentStateStore, StoreError


class FileAgentStateStore(AgentStateStore):
    """File-backed agent state store.

    One JSON file per agent.  Atomic writes via temp-file + rename.
    """

    def __init__(self, storage_dir: str | Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────────

    def save(self, agent_id: str, state: AgentState) -> None:
        self._validate_agent_id(agent_id)
        path = self._path_for(agent_id)

        # Serialise to JSON
        try:
            data = self._serialise(state)
        except Exception as exc:
            raise StoreError(
                f"failed to serialise state for agent {agent_id!r}: {exc}"
            ) from exc

        # Atomic write: temp file → rename
        tmp_name: str = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self._storage_dir,
                prefix=f"{agent_id}_",
                suffix=".tmp",
                delete=False,
            ) as f:
                f.write(data)
                tmp_name = f.name
            os.replace(tmp_name, str(path))
        except OSError as exc:
            if tmp_name and os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise StoreError(
                f"failed to write state for agent {agent_id!r}: {exc}"
            ) from exc

    def load(self, agent_id: str) -> Optional[AgentState]:
        self._validate_agent_id(agent_id)
        path = self._path_for(agent_id)

        if not path.exists():
            return None

        try:
            raw = path.read_text(encoding="utf-8")
            return self._deserialise(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise StoreError(
                f"failed to load state for agent {agent_id!r}: {exc}"
            ) from exc

    def list_agent_ids(self) -> List[str]:
        ids: List[str] = []
        for f in self._storage_dir.glob("*.json"):
            stem = f.stem
            if stem:
                ids.append(stem)
        return sorted(ids)

    # ── Internals ───────────────────────────────────────────────────────

    def _path_for(self, agent_id: str) -> Path:
        return self._storage_dir / f"{agent_id}.json"

    @staticmethod
    def _validate_agent_id(agent_id: str) -> None:
        if not agent_id:
            raise StoreError("agent_id must be non-empty")
        if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
            raise StoreError(
                f"invalid agent_id {agent_id!r}: "
                "must not contain path separators or '..'"
            )

    @staticmethod
    def _serialise(state: AgentState) -> str:
        """Convert an AgentState to a JSON string."""
        import dataclasses
        d = dataclasses.asdict(state)
        # Add schema version for future migrations
        d["_schema_version"] = 1
        return json.dumps(d, indent=2, default=str)

    @staticmethod
    def _deserialise(raw: str) -> AgentState:
        """Parse a JSON string back into an AgentState."""
        d: Dict = json.loads(raw)

        # Remove schema metadata before deserialisation
        d.pop("_schema_version", None)

        # Rehydrate LifecycleState enum
        from src.agent.interfaces.agent_state import LifecycleState
        ls_val = d.get("lifecycle_state", "created")
        if isinstance(ls_val, str):
            d["lifecycle_state"] = LifecycleState(ls_val)

        # Rehydrate nested objects
        from src.agent.interfaces.agent_state import LifecycleEvent
        if "lifecycle_history" in d and isinstance(d["lifecycle_history"], list):
            d["lifecycle_history"] = [
                LifecycleEvent(**ev) if isinstance(ev, dict) else ev
                for ev in d["lifecycle_history"]
            ]

        # Rehydrate ActionIntent list from dicts
        if "pending_intents" in d and isinstance(d["pending_intents"], list):
            from src.agent.contracts import ActionIntent
            d["pending_intents"] = [
                ActionIntent(**ai) if isinstance(ai, dict) else ai
                for ai in d["pending_intents"]
            ]

        # Rehydrate ActivationContext
        if "activation_snapshot" in d and isinstance(d["activation_snapshot"], dict):
            from src.agent.activation import ActivatedAgentContext
            d["activation_snapshot"] = _rehydrate_activation_context(
                d["activation_snapshot"]
            )

        # Rehydrate dispatch result
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


def _rehydrate_activation_context(d: Dict) -> "ActivatedAgentContext":
    """Rehydrate an ActivatedAgentContext from a dict."""
    from src.agent.activation import ActivatedAgentContext
    from src.agent.contracts import AgentMessage

    msg = d.get("message", {})
    if isinstance(msg, dict):
        d["message"] = AgentMessage(**msg)

    return ActivatedAgentContext(**d)
