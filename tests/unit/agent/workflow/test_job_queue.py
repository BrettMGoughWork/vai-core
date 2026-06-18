"""Sprint 5.1 — InMemoryJobQueue unit tests."""

from __future__ import annotations

from src.agent.workflow.job_queue import InMemoryJobQueue, JobRecord


class TestInMemoryJobQueue:
    """Cover submit, get, list, mark_*, and clear."""

    def test_submit_returns_job_id(self) -> None:
        queue = InMemoryJobQueue()
        job_id = queue.submit({"skill_name": "test_tool"})
        assert isinstance(job_id, str)
        assert job_id.startswith("job_")

    def test_submitted_job_is_queued(self) -> None:
        queue = InMemoryJobQueue()
        job_id = queue.submit({"skill_name": "test_tool"})
        record = queue.get(job_id)
        assert record is not None
        assert record.status == "queued"
        assert record.payload == {"skill_name": "test_tool"}

    def test_get_unknown_returns_none(self) -> None:
        queue = InMemoryJobQueue()
        assert queue.get("nonexistent") is None

    def test_list_all(self) -> None:
        queue = InMemoryJobQueue()
        queue.submit({"a": 1})
        queue.submit({"b": 2})
        all_jobs = queue.list()
        assert len(all_jobs) == 2

    def test_list_filtered_by_status(self) -> None:
        queue = InMemoryJobQueue()
        j1 = queue.submit({"a": 1})
        j2 = queue.submit({"b": 2})
        queue.mark_running(j1)
        queue.mark_complete(j2)

        running = queue.list(status="running")
        completed = queue.list(status="completed")
        queued = queue.list(status="queued")

        assert len(running) == 1
        assert running[0].job_id == j1
        assert len(completed) == 1
        assert completed[0].job_id == j2
        assert len(queued) == 0

    def test_mark_running(self) -> None:
        queue = InMemoryJobQueue()
        jid = queue.submit({"x": 1})
        queue.mark_running(jid)
        assert queue.get(jid).status == "running"

    def test_mark_complete_stores_result(self) -> None:
        queue = InMemoryJobQueue()
        jid = queue.submit({"x": 1})
        queue.mark_complete(jid, result={"output": "done"})
        record = queue.get(jid)
        assert record.status == "completed"
        assert record.result == {"output": "done"}
        assert record.error is None

    def test_mark_failed_stores_error(self) -> None:
        queue = InMemoryJobQueue()
        jid = queue.submit({"x": 1})
        queue.mark_failed(jid, error="Something went wrong")
        record = queue.get(jid)
        assert record.status == "failed"
        assert record.error == "Something went wrong"

    def test_clear_removes_all_jobs(self) -> None:
        queue = InMemoryJobQueue()
        queue.submit({"a": 1})
        queue.submit({"b": 2})
        assert len(queue.list()) == 2
        queue.clear()
        assert len(queue.list()) == 0

    def test_submit_is_callable_compatible(self) -> None:
        """The queue.submit method matches the submit_job_callable signature.

        The Supervisor and StrategyRouter expect Callable[[dict], str].
        """
        queue = InMemoryJobQueue()
        fn = queue.submit  # Callable[[dict[str, Any]], str]
        job_id = fn({"skill_name": "test_tool"})
        assert isinstance(job_id, str)
        assert queue.get(job_id) is not None
