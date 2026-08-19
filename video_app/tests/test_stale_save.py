"""Tests for a save that does not write the source file."""

from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from video_app.models import Video
from video_app.tests.test_thumbnail import (
    TemporaryMediaTestCase,
    create_video,
)

VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
OTHER_NAME = "feature.mp4"
OTHER_CONTENT = b"different source bytes"
FRAME_NAME = "cover.jpg"
FRAME_CONTENT = b"frame bytes"


class StaleWriteBackTests(TemporaryMediaTestCase):
    """A worker writing back a handle loaded before a swap."""

    def setUp(self):
        """Store a video, hold a handle on it and swap its source."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.stale = Video.objects.get(pk=self.video.pk)
        self.swap()

    def swap(self):
        """Replace the source through a freshly loaded handle."""
        fresh = Video.objects.get(pk=self.video.pk)
        fresh.video_file = SimpleUploadedFile(OTHER_NAME, OTHER_CONTENT)
        with patch("django_rq.get_queue"):
            with self.captureOnCommitCallbacks(execute=True):
                fresh.save()
        self.current = Path(fresh.video_file.path)

    def write_back(self):
        """Store a thumbnail through the handle loaded earlier."""
        self.stale.thumbnail.save(
            FRAME_NAME, ContentFile(FRAME_CONTENT), save=False
        )
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                self.stale.save(update_fields=["thumbnail"])
        return get_queue.return_value.enqueue

    def test_the_live_source_survives(self):
        """The file the row points at stays on disk."""
        self.write_back()
        self.assertTrue(self.current.is_file())

    def test_the_row_keeps_its_source(self):
        """The row still names the source the swap stored."""
        self.write_back()
        self.video.refresh_from_db()
        self.assertEqual(Path(self.video.video_file.path), self.current)

    def test_the_write_back_queues_nothing(self):
        """A thumbnail write back starts no second conversion."""
        self.assertFalse(self.write_back().called)

    def test_the_stored_thumbnail_is_kept(self):
        """The frame the write back stored reaches the row."""
        self.write_back()
        self.video.refresh_from_db()
        self.assertTrue(Path(self.video.thumbnail.path).is_file())
