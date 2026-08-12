"""Tests for the files a deleted video takes with it."""

import shutil
from pathlib import Path

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from video_app.admin import VideoAdmin
from video_app.models import Video
from video_app.services.conversion import PLAYLIST_NAME, video_directory
from video_app.tests.test_thumbnail import (
    TemporaryMediaTestCase,
    create_video,
)

VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"uploaded bytes"
PLAYLIST_CONTENT = "#EXTM3U\n"
RESOLUTION = "480p"
ROLLBACK_MESSAGE = "rollback"


class DeletedVideoTestCase(TemporaryMediaTestCase):
    """A video whose source, frame and renditions lie on disk."""

    def setUp(self):
        """Store the video these deletions start from."""
        self.video = self.store()
        self.paths = self.paths_of(self.video)

    def store(self):
        """Return a stored video carrying every file it can have."""
        video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT),
            thumbnail=SimpleUploadedFile(THUMBNAIL_NAME, THUMBNAIL_CONTENT),
        )
        self.write_rendition(video)
        return video

    def write_rendition(self, video):
        """Write the playlist a finished conversion would leave."""
        directory = video_directory(video.pk) / RESOLUTION
        directory.mkdir(parents=True)
        (directory / PLAYLIST_NAME).write_text(PLAYLIST_CONTENT)

    def paths_of(self, video):
        """Return source, frame and HLS directory of this video."""
        return [
            Path(video.video_file.path),
            Path(video.thumbnail.path),
            video_directory(video.pk),
        ]

    def delete(self, video):
        """Delete this video and run what its commit triggers."""
        with self.captureOnCommitCallbacks(execute=True):
            video.delete()

    def existing(self, paths):
        """Return the paths of this list that are still on disk."""
        return [path for path in paths if path.exists()]


class SingleDeleteTests(DeletedVideoTestCase):
    """Deleting one video takes exactly its own files with it."""

    def test_the_hls_tree_is_gone(self):
        """The renditions of the deleted video are removed."""
        self.delete(self.video)
        self.assertFalse(self.paths[2].exists())

    def test_the_source_file_is_gone(self):
        """The uploaded video file is removed."""
        self.delete(self.video)
        self.assertFalse(self.paths[0].exists())

    def test_the_thumbnail_is_gone(self):
        """The preview frame of the deleted video is removed."""
        self.delete(self.video)
        self.assertFalse(self.paths[1].exists())

    def test_nothing_is_removed_before_the_commit(self):
        """The files stay while the deleting transaction is open."""
        with self.captureOnCommitCallbacks(execute=True):
            self.video.delete()
            pending = self.existing(self.paths)
        self.assertEqual(pending, self.paths)

    def test_a_video_without_files_deletes_quietly(self):
        """A video whose files vanished raises nothing on delete."""
        video = create_video()
        self.assertIsNone(self.delete(video))

    def test_files_removed_beforehand_raise_nothing(self):
        """A delete after a failed conversion finds nothing to do."""
        self.paths[0].unlink()
        shutil.rmtree(self.paths[2])
        self.assertIsNone(self.delete(self.video))


class NeighbourDeleteTests(DeletedVideoTestCase):
    """Deleting one video leaves the files of the others alone."""

    def setUp(self):
        """Store a second video beside the one being deleted."""
        super().setUp()
        self.neighbour = self.store()
        self.neighbour_paths = self.paths_of(self.neighbour)

    def test_the_neighbour_keeps_every_file(self):
        """The video that stays keeps source, frame and renditions."""
        self.delete(self.video)
        self.assertEqual(
            self.existing(self.neighbour_paths), self.neighbour_paths
        )

    def test_the_neighbour_keeps_its_playlist(self):
        """The rendition of the video that stays is still readable."""
        self.delete(self.video)
        playlist = self.neighbour_paths[2] / RESOLUTION / PLAYLIST_NAME
        self.assertEqual(playlist.read_text(), PLAYLIST_CONTENT)

    def test_the_deleted_video_still_loses_its_files(self):
        """The neighbour does not keep the other video alive."""
        self.delete(self.video)
        self.assertEqual(self.existing(self.paths), [])


class BulkDeleteTests(DeletedVideoTestCase):
    """The admin action that deletes a whole selection at once."""

    def bulk_delete(self):
        """Delete every video the way the admin action does."""
        modeladmin = VideoAdmin(Video, admin.site)
        with self.captureOnCommitCallbacks(execute=True):
            modeladmin.delete_queryset(None, Video.objects.all())

    def test_the_bulk_delete_removes_the_files(self):
        """A selection deleted at once loses its files as well."""
        self.bulk_delete()
        self.assertEqual(self.existing(self.paths), [])

    def test_the_bulk_delete_removes_every_row(self):
        """The rows this action removed are really gone."""
        self.bulk_delete()
        self.assertFalse(Video.objects.exists())

    def test_a_second_video_loses_its_files_too(self):
        """Every video of the selection is cleaned up, not one."""
        second = self.paths_of(self.store())
        self.bulk_delete()
        self.assertEqual(self.existing(second), [])


class RolledBackDeleteTests(DeletedVideoTestCase):
    """A delete the database takes back before it holds."""

    def roll_back_a_delete(self):
        """Delete the video inside a transaction that fails."""
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self.video.delete()
                    raise RuntimeError(ROLLBACK_MESSAGE)

    def test_the_files_survive_the_rollback(self):
        """Every file stays where it was before the failed delete."""
        self.roll_back_a_delete()
        self.assertEqual(self.existing(self.paths), self.paths)

    def test_the_row_survives_the_rollback(self):
        """The video the rollback restored is still in the table."""
        self.roll_back_a_delete()
        self.assertTrue(Video.objects.filter(title=self.video.title).exists())
