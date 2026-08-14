"""Tests for the files a replaced upload leaves behind."""

from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from video_app.tasks import generate_thumbnail
from video_app.tests.test_thumbnail import (
    TemporaryMediaTestCase,
    create_video,
    fake_ffmpeg,
)

VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
OTHER_NAME = "feature.mp4"
OTHER_CONTENT = b"different source bytes"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"uploaded bytes"
NEW_TITLE = "Corrected Title"
ROLLBACK_MESSAGE = "rollback"


class SwapCleanupTestCase(TemporaryMediaTestCase):
    """A stored video whose upload these tests replace."""

    def setUp(self):
        """Store the video and remember the file it started with."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.previous = Path(self.video.video_file.path)
        self.before = len(self.uploads())

    def uploads(self):
        """Return the files lying in the upload directory."""
        return list(Path(self.video.video_file.path).parent.iterdir())

    def swap(self, name=OTHER_NAME):
        """Put a different file on the stored video and save it."""
        self.video.video_file = SimpleUploadedFile(name, OTHER_CONTENT)
        self.video.save()

    def perform(self, action):
        """Run this action and let its commit callbacks run."""
        with patch("django_rq.get_queue"):
            with self.captureOnCommitCallbacks(execute=True):
                action()

    def current(self):
        """Return the path of the file the row points at now."""
        self.video.refresh_from_db()
        return Path(self.video.video_file.path)


class ReplacedSourceTests(SwapCleanupTestCase):
    """Replacing the upload takes the previous one with it."""

    def test_the_previous_source_is_gone(self):
        """The upload the swap pushed aside is removed from disk."""
        self.perform(self.swap)
        self.assertFalse(self.previous.exists())

    def test_the_current_source_stays(self):
        """The upload the row points at survives the cleanup."""
        self.perform(self.swap)
        self.assertTrue(self.current().exists())

    def test_the_upload_directory_does_not_grow(self):
        """The swap leaves as many uploads behind as it found."""
        self.perform(self.swap)
        self.assertEqual(len(self.uploads()), self.before)

    def test_a_swap_reusing_the_name_removes_the_previous_one(self):
        """A new upload of the same name still frees the old file."""
        self.perform(lambda: self.swap(name=VIDEO_NAME))
        self.assertFalse(self.previous.exists())

    def test_the_reused_name_keeps_the_current_file(self):
        """The file stored under the suffixed name is kept."""
        self.perform(lambda: self.swap(name=VIDEO_NAME))
        self.assertTrue(self.current().exists())


class UnchangedSourceTests(SwapCleanupTestCase):
    """Saves that leave the stored upload exactly as it was."""

    def rename(self):
        """Correct the title of the stored video and save it."""
        self.video.title = NEW_TITLE
        self.video.save()

    def test_a_title_edit_removes_nothing(self):
        """A save that changes no file keeps the upload on disk."""
        self.perform(self.rename)
        self.assertTrue(self.previous.exists())

    def test_a_new_video_removes_nothing(self):
        """Storing a first upload has no previous file to drop."""
        self.perform(lambda: create_video(video_file=VIDEO_NAME))
        self.assertTrue(self.previous.exists())


class RolledBackSwapTests(SwapCleanupTestCase):
    """A swap the database takes back before it holds."""

    def roll_back_a_swap(self):
        """Replace the upload inside a transaction that fails."""
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.swap()
                raise RuntimeError(ROLLBACK_MESSAGE)

    def test_the_previous_source_survives_the_rollback(self):
        """The file the restored row points at is still on disk."""
        self.perform(self.roll_back_a_swap)
        self.assertTrue(self.previous.exists())

    def test_the_row_still_points_at_it(self):
        """The row the rollback restored keeps its own upload."""
        self.perform(self.roll_back_a_swap)
        self.assertEqual(self.current(), self.previous)


class ReplacedThumbnailTests(TemporaryMediaTestCase):
    """The frame grab that writes a new thumbnail frees the old one."""

    def setUp(self):
        """Store a video that already carries a thumbnail."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT),
            thumbnail=SimpleUploadedFile(THUMBNAIL_NAME, THUMBNAIL_CONTENT),
        )
        self.previous = Path(self.video.thumbnail.path)
        self.before = len(self.frames())

    def frames(self):
        """Return the files lying in the thumbnail directory."""
        return list(Path(self.video.thumbnail.path).parent.iterdir())

    def run_job(self):
        """Run the frame extraction with a stand-in for FFmpeg."""
        with patch("subprocess.run", side_effect=fake_ffmpeg):
            with self.captureOnCommitCallbacks(execute=True):
                generate_thumbnail(self.video.pk)

    def current(self):
        """Return the path of the thumbnail the row points at now."""
        self.video.refresh_from_db()
        return Path(self.video.thumbnail.path)

    def test_the_previous_thumbnail_is_gone(self):
        """The frame the write back replaced is removed from disk."""
        self.run_job()
        self.assertFalse(self.previous.exists())

    def test_the_new_thumbnail_stays(self):
        """The frame the row points at survives the cleanup."""
        self.run_job()
        self.assertTrue(self.current().exists())

    def test_the_new_thumbnail_is_a_different_file(self):
        """The write back really wrote a second name."""
        self.run_job()
        self.assertNotEqual(self.current(), self.previous)

    def test_the_thumbnail_directory_does_not_grow(self):
        """The write back leaves as many frames behind as it found."""
        self.run_job()
        self.assertEqual(len(self.frames()), self.before)

    def test_a_first_thumbnail_removes_nothing(self):
        """A video without a thumbnail has no previous file to drop."""
        self.video.thumbnail.delete(save=True)
        self.run_job()
        self.assertTrue(self.current().exists())
