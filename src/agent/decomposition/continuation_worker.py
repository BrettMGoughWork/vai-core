"""ContinuationWorker — WorkExecutor for decomposition continuation (merge) jobs.

A continuation job is enqueued by ``DecompositionOrchestrator.fan_out()``
after all subtask jobs are dispatched.  The worker:

1. Loads the ``JoinHandle`` from ``JoinStore``
2. Collects all child job results from ``JobStore``
3. Executes the configured merge strategy
4. Returns the merged result

Continuation metadata is carried in ``ChannelMessage.metadata``:

* ``join_handle_id`` — which ``JoinHandle`` to reconcile
* ``merge_strategy`` — one of ``"concat"``, ``"summarize_llm"``, etc.
* ``merge_agent_id`` — optional agent for LLM-based merges
* ``merge_prompt_template`` — optional prompt template for LLM merge
"""

from __future__ import annotations

from typing import Any


class ContinuationWorker:
    """WorkExecutor for decomposition continuation (merge) jobs.

    Args:
        join_store:
            Store for loading ``JoinHandle`` state.
        job_store:
            Store for loading completed child job results.
        execute_merge:
            Callable with the signature::

                (strategy: str, child_results: dict[str, dict],
                 parent_task: str = "", prompt_template: str | None = None)
                -> MergeResult
    """

    def __init__(
        self,
        join_store: Any,  # JoinStore
        job_store: Any,  # JobStore
        execute_merge: Any,  # Callable — avoids circular dep on MergeResult
    ) -> None:
        self._join_store = join_store
        self._job_store = job_store
        self._execute_merge = execute_merge

    def __call__(
        self,
        payload: Any,
        execution_context: Any = None,
        resume_token: Any = None,
        **kwargs: Any,
    ) -> dict:
        """Process a continuation (merge) job.

        Args:
            payload: The ``ChannelMessage`` with continuation metadata.
            **kwargs: Ignored (Worker passes ``attempt``, ``job_id``, etc.).

        Returns:
            A result dict with the merged output.
        """
        # --- Extract metadata ------------------------------------------------
        # Lazy-import to avoid circular / missing-dependency issues.
        try:
            from src.gateway.normalization import ChannelMessage

            _channel_type = ChannelMessage
        except ImportError:
            _channel_type = type(None)

        if isinstance(payload, _channel_type):
            metadata = payload.metadata or {}
        elif isinstance(payload, dict):
            metadata = payload.get("metadata", {})
        else:
            return {
                "output": f"Unexpected payload type: {type(payload).__name__}",
                "status": "error",
                "done": True,
            }

        join_handle_id: str | None = metadata.get("join_handle_id")
        merge_strategy: str = metadata.get("merge_strategy", "concat")
        merge_agent_id: str | None = metadata.get("merge_agent_id")
        merge_prompt_template: str | None = metadata.get("merge_prompt_template")
        parent_task: str = metadata.get("subtask_description", "")

        if not join_handle_id:
            return {
                "output": "No join_handle_id in continuation metadata.",
                "status": "error",
                "done": True,
            }

        # --- Load JoinHandle -------------------------------------------------
        handle = self._join_store.get(join_handle_id)
        if handle is None:
            return {
                "output": f"JoinHandle {join_handle_id} not found.",
                "status": "error",
                "done": True,
            }

        # --- Collect child results, keyed by subtask_id ----------------------
        child_results: dict[str, dict[str, Any]] = {}
        for child_job_id in handle.child_job_ids:
            job = self._job_store.get(child_job_id)
            if job is None:
                continue
            # Use subtask_id if available, otherwise fall back to job_id
            key = job.subtask_id or child_job_id
            child_results[key] = job.result or {}

        # --- Execute merge ---------------------------------------------------
        try:
            merged = self._execute_merge(
                strategy=merge_strategy,
                child_results=child_results,
                parent_task=parent_task,
                prompt_template=merge_prompt_template,
            )
        except Exception as exc:
            return {
                "output": f"Merge failed: {exc}",
                "status": "error",
                "done": True,
            }

        return {
            "output": merged.output if hasattr(merged, "output") else str(merged),
            "status": "success",
            "done": True,
            "merge_strategy": merge_strategy,
        }
