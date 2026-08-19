"""Tests for a file removal that cannot finish."""

from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from video_app.models import Video
from video_app.services.cleanup import REMOVAL_FAILURE_MESSAGE
from video_app.tests.test_thumbnail import (
    TemporaryMediaTestCase,
    create_video,
)

VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
OTHER_NAME = "feature.mp4"
OTHER_CONTENT = b"different source bytes"
BLOCKER_NAME = "occupied"
CLEANUP_LOGGER = "video_app.services.cleanup"


def block_removal(path):
    """Put a directory nothing can remove where this file lies."""
    path.unlink()
    path.mkdir()
    (path / BLOCKER_NAME).touch()


class BlockedCleanupTestCase(TemporaryMediaTestCase):
    """A stored video whose upload no removal can drop."""

    def setUp(self):
        """Store a video and block the removal of its upload."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.blocked = Path(self.video.video_file.path)
        block_removal(self.blocked)

    def stored(self):
        """Return the path of the file the row points at now."""
        self.video.refresh_from_db()
        return Path(self.video.video_file.path)


class BlockedSwapCleanupTests(BlockedCleanupTestCase):
    """A swap whose cleanup cannot drop the previous upload."""

    def swap(self):
        """Replace the upload and run the commit callbacks."""
        with patch("django_rq.get_queue"):
            with self.captureOnCommitCallbacks(execute=True):
                self.video.video_file = SimpleUploadedFile(
                    OTHER_NAME, OTHER_CONTENT
                )
                self.video.save()

    def test_the_save_survives_the_failure(self):
        """A removal that cannot finish raises nothing."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR"):
            self.swap()

    def test_the_failure_is_logged(self):
        """The removal that failed reports itself in the log."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR") as logs:
            self.swap()
        self.assertIn(REMOVAL_FAILURE_MESSAGE, logs.output[0])

    def test_the_row_holds_the_stored_upload(self):
        """The file the committed save stored lies on disk."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR"):
            self.swap()
        self.assertTrue(self.stored().is_file())

    def test_the_row_lets_go_of_the_blocked_upload(self):
        """The row no longer points at the file that stayed."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR"):
            self.swap()
        self.assertNotEqual(self.stored(), self.blocked)


class BlockedDeleteCleanupTests(BlockedCleanupTestCase):
    """A delete whose cleanup cannot drop the stored upload."""

    def remove(self):
        """Delete the row and run the commit callbacks."""
        with self.captureOnCommitCallbacks(execute=True):
            self.video.delete()

    def test_the_delete_survives_the_failure(self):
        """A removal that cannot finish raises nothing."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR"):
            self.remove()

    def test_the_failure_is_logged(self):
        """The removal that failed reports itself in the log."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR") as logs:
            self.remove()
        self.assertIn(REMOVAL_FAILURE_MESSAGE, logs.output[0])

    def test_the_row_stays_deleted(self):
        """The row the failed cleanup followed is still gone."""
        with self.assertLogs(CLEANUP_LOGGER, "ERROR"):
            self.remove()
        self.assertFalse(Video.objects.filter(pk=self.video.pk).exists())
