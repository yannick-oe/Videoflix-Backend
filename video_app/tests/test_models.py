"""Tests for the video model."""

import tempfile
from datetime import datetime, timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from video_app.models import Video

TITLE = "Movie Title"
DESCRIPTION = "Movie Description"
CATEGORY = "Drama"
VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"binary"


def create_video(**overrides):
    """Return a stored video built from the default field values."""
    fields = {
        "title": TITLE,
        "description": DESCRIPTION,
        "category": CATEGORY,
        "video_file": "videos/clip.mp4",
    }
    fields.update(overrides)
    return Video.objects.create(**fields)


def backdate(video, day):
    """Move the creation date of a video to a day in January 2023."""
    Video.objects.filter(pk=video.pk).update(
        created_at=datetime(2023, 1, day, tzinfo=timezone.utc)
    )


class VideoModelTests(TestCase):
    """Structure and constraints of a stored video."""

    def test_string_representation_is_the_title(self):
        """A video prints as its title."""
        self.assertEqual(str(create_video()), TITLE)

    def test_thumbnail_may_stay_empty(self):
        """A video is storable before its thumbnail exists."""
        self.assertFalse(create_video().thumbnail)

    def test_created_at_is_set_on_save(self):
        """Storing a video stamps its creation date."""
        self.assertIsNotNone(create_video().created_at)

    def test_empty_category_is_rejected(self):
        """A video without a category never reaches the table."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_video(category="")

    def test_missing_category_is_rejected(self):
        """Leaving the category out falls under the same constraint."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            Video.objects.create(
                title=TITLE,
                description=DESCRIPTION,
                video_file="videos/clip.mp4",
            )


class VideoOrderingTests(TestCase):
    """Order in which the model hands videos out."""

    def setUp(self):
        """Store three videos with known creation dates."""
        self.oldest = create_video(title="Oldest")
        self.newest = create_video(title="Newest")
        self.middle = create_video(title="Middle")
        backdate(self.oldest, 1)
        backdate(self.middle, 2)
        backdate(self.newest, 3)

    def test_videos_come_newest_first(self):
        """The default order is the creation date descending."""
        self.assertEqual(
            list(Video.objects.all()),
            [self.newest, self.middle, self.oldest],
        )

    def test_videos_created_together_come_newest_first(self):
        """Videos sharing a creation date keep the newest in front."""
        Video.objects.all().delete()
        first = create_video(title="First")
        second = create_video(title="Second")
        backdate(first, 1)
        backdate(second, 1)
        self.assertEqual(list(Video.objects.all()), [second, first])


class VideoUploadTests(TestCase):
    """Where an uploaded file of a video lands."""

    @classmethod
    def setUpClass(cls):
        """Point MEDIA_ROOT at a directory this class removes."""
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        cls.addClassCleanup(override.disable)

    def test_video_file_lands_in_its_subdirectory(self):
        """An uploaded video file is stored below videos/."""
        video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.assertTrue(video.video_file.name.startswith("videos/"))

    def test_thumbnail_lands_in_its_subdirectory(self):
        """An uploaded thumbnail is stored below thumbnails/."""
        video = create_video(
            thumbnail=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )
        self.assertTrue(video.thumbnail.name.startswith("thumbnails/"))
