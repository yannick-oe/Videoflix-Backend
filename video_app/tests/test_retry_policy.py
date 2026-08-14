"""Tests for the jobs that are deliberately not retried."""

from unittest.mock import patch

from django.test import TestCase

from video_app.services.conversion import queue_renditions
from video_app.services.thumbnail import queue_thumbnail

VIDEO_ID = 1


class UnretriedJobTests(TestCase):
    """A failing FFmpeg run is not repeated at the worker's cost."""

    def enqueue_during(self, action):
        """Return the enqueue mock this action wrote its jobs to."""
        with patch("django_rq.get_queue") as get_queue:
            action()
        return get_queue.return_value.enqueue

    def retries_of(self, enqueue):
        """Return the retry policy of every call this mock holds."""
        return [call.kwargs.get("retry") for call in enqueue.call_args_list]

    def test_the_frame_extraction_carries_no_policy(self):
        """A frame FFmpeg refuses is not extracted again."""
        enqueue = self.enqueue_during(lambda: queue_thumbnail(VIDEO_ID))
        self.assertEqual(self.retries_of(enqueue), [None])

    def test_no_conversion_carries_a_policy(self):
        """A source FFmpeg refuses is not converted again."""
        enqueue = self.enqueue_during(lambda: queue_renditions(VIDEO_ID))
        self.assertNotIn(True, [bool(r) for r in self.retries_of(enqueue)])

    def test_every_conversion_was_queued(self):
        """The conversions these counts cover really were queued."""
        enqueue = self.enqueue_during(lambda: queue_renditions(VIDEO_ID))
        self.assertGreater(enqueue.call_count, 0)
