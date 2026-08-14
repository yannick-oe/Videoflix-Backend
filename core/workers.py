"""Worker class that serves the background queue."""

from rq import Worker


class SchedulingWorker(Worker):
    """Worker that runs the scheduler its delayed retries need."""

    def work(self, *args, **kwargs):
        """Start working with the retry scheduler switched on."""
        kwargs["with_scheduler"] = True
        return super().work(*args, **kwargs)
