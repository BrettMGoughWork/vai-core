class PoisonJobDetector:
    def __init__(self, failure_threshold=5):
        self.failure_threshold = failure_threshold
        self.failure_counts = {}
        self.poisoned_jobs = set()

    def record_failure(self, job_id: str):
        count = self.failure_counts.get(job_id, 0) + 1
        self.failure_counts[job_id] = count
        if count >= self.failure_threshold:
            self.poisoned_jobs.add(job_id)

    def record_success(self, job_id: str):
        self.failure_counts.pop(job_id, None)
        self.poisoned_jobs.discard(job_id)

    def is_poison(self, job_id: str) -> bool:
        return job_id in self.poisoned_jobs
