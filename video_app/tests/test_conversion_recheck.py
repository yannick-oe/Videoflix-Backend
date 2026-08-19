"""Tests for a conversion that finishes after its row is gone."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from video_app.services.conversion import (
    CONVERSION_FAILURE_MESSAGE,
    PLAYLIST_NAME,
    video_directory,
)
from video_app.tasks import generate_rendition
from video_app.tests.test_conversion import fake_ffmpeg
from video_app.tests.test_thumbnail import TemporaryMediaTestCase, create_video

LOGGER = "video_app.services.conversion"
VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
RESOLUTION = "480p"


class LateConversionTests(TemporaryMediaTestCase):
    """A row deleted while the worker is still converting it."""

    def setUp(self):
        """Store the video the conversion under test starts from."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.directory = video_directory(self.video.pk)

    def delete_while_converting(self, command, **kwargs):
        """Remove the row and its files the way a delete would."""
        with self.captureOnCommitCallbacks(execute=True):
            self.video.delete()
        return fake_ffmpeg(command, **kwargs)

    def convert(self, behaviour):
        """Run the conversion job against this stand-in for FFmpeg."""
        with patch("subprocess.run", side_effect=behaviour):
            generate_rendition(self.video.pk, RESOLUTION)

    def convert_into_the_delete(self):
        """Convert while the row goes and read the logged failure."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            self.convert(self.delete_while_converting)
        self.assertIn(CONVERSION_FAILURE_MESSAGE, logs.output[0])

    def test_a_late_conversion_leaves_no_tree(self):
        """The rendition finished for a deleted row is removed."""
        self.convert_into_the_delete()
        self.assertFalse(self.directory.exists())

    def test_a_late_conversion_leaves_no_playlist(self):
        """No playlist of the deleted video survives the job."""
        self.convert_into_the_delete()
        playlist = self.directory / RESOLUTION / PLAYLIST_NAME
        self.assertFalse(playlist.exists())

    def test_the_conversion_really_ran(self):
        """The job these tests cover reached FFmpeg at all."""
        with self.assertLogs(LOGGER, level="ERROR"):
            with patch("subprocess.run") as process:
                process.side_effect = self.delete_while_converting
                generate_rendition(self.video.pk, RESOLUTION)
        process.assert_called_once()

    def test_a_conversion_for_a_living_row_keeps_its_tree(self):
        """A video that is still stored keeps its rendition."""
        self.convert(fake_ffmpeg)
        playlist = self.directory / RESOLUTION / PLAYLIST_NAME
        self.assertTrue(playlist.exists())

    def test_a_row_deleted_before_the_job_never_converts(self):
        """A job taken up after the delete starts no process."""
        with self.captureOnCommitCallbacks(execute=True):
            self.video.delete()
        with patch("subprocess.run") as process:
            generate_rendition(self.video.pk, RESOLUTION)
        process.assert_not_called()
