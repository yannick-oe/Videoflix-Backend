"""Tests for the jobs a replaced video file starts again."""

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile

from video_app.services.conversion import RENDITIONS
from video_app.tasks import generate_thumbnail
from video_app.tests.test_conversion import conversion_calls
from video_app.tests.test_thumbnail import (
    TemporaryMediaTestCase,
    create_video,
    fake_ffmpeg,
    thumbnail_enqueue,
)

VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
OTHER_NAME = "feature.mp4"
OTHER_CONTENT = b"different source bytes"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"uploaded bytes"
NEW_TITLE = "Corrected Title"
NEW_DESCRIPTION = "Corrected Description"
TOTAL_JOBS = len(RENDITIONS) + 1


class SwapTestCase(TemporaryMediaTestCase):
    """A stored video whose saves these tests watch."""

    def setUp(self):
        """Store the video every one of these saves starts from."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )

    def enqueue_during(self, action):
        """Return the enqueue mock this action wrote its jobs to."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                action()
        return get_queue.return_value.enqueue

    def swap(self, name=OTHER_NAME):
        """Put a different file on the stored video and save it."""
        self.video.video_file = SimpleUploadedFile(name, OTHER_CONTENT)
        self.video.save()


class FileSwapTests(SwapTestCase):
    """Replacing the stored video file starts the work again."""

    def test_a_swap_queues_the_frame_extraction(self):
        """The replaced file gets a new preview frame."""
        enqueue = self.enqueue_during(self.swap)
        self.assertEqual(thumbnail_enqueue(enqueue).call_count, 1)

    def test_a_swap_queues_every_rendition(self):
        """The replaced file is converted for every resolution."""
        enqueue = self.enqueue_during(self.swap)
        self.assertEqual(len(conversion_calls(enqueue)), len(RENDITIONS))

    def test_a_swap_queues_nothing_beyond_those_jobs(self):
        """A swap queues the frame extraction and the renditions."""
        enqueue = self.enqueue_during(self.swap)
        self.assertEqual(enqueue.call_count, TOTAL_JOBS)

    def test_a_swap_reusing_the_name_is_seen_as_well(self):
        """Uploading a file of the same name still counts as a swap."""
        enqueue = self.enqueue_during(lambda: self.swap(name=VIDEO_NAME))
        self.assertEqual(enqueue.call_count, TOTAL_JOBS)

    def test_a_swap_replaces_an_existing_thumbnail(self):
        """A video that already has a thumbnail gets a fresh one."""
        self.video.thumbnail = SimpleUploadedFile(
            THUMBNAIL_NAME, THUMBNAIL_CONTENT
        )
        enqueue = self.enqueue_during(self.swap)
        self.assertEqual(thumbnail_enqueue(enqueue).call_count, 1)


class UnchangedFileTests(SwapTestCase):
    """Saves that leave the stored video file exactly as it was."""

    def rename(self):
        """Correct the title of the stored video and save it."""
        self.video.title = NEW_TITLE
        self.video.save()

    def edit_description(self):
        """Correct the description of the stored video and save it."""
        self.video.description = NEW_DESCRIPTION
        self.video.save()

    def write_back_thumbnail(self):
        """Run the frame extraction that saves the video again."""
        with patch("subprocess.run", side_effect=fake_ffmpeg):
            generate_thumbnail(self.video.pk)

    def test_a_title_edit_queues_no_frame_extraction(self):
        """Correcting a title does not queue a frame extraction."""
        enqueue = self.enqueue_during(self.rename)
        self.assertEqual(thumbnail_enqueue(enqueue).call_count, 0)

    def test_a_title_edit_queues_no_conversion(self):
        """Correcting a title does not start three FFmpeg runs."""
        enqueue = self.enqueue_during(self.rename)
        self.assertEqual(conversion_calls(enqueue), [])

    def test_a_description_edit_queues_nothing(self):
        """Any field but the file leaves the queue untouched."""
        enqueue = self.enqueue_during(self.edit_description)
        self.assertEqual(enqueue.call_count, 0)

    def test_the_thumbnail_write_back_queues_no_frame_extraction(self):
        """Storing the frame does not queue another extraction."""
        enqueue = self.enqueue_during(self.write_back_thumbnail)
        self.assertEqual(thumbnail_enqueue(enqueue).call_count, 0)

    def test_the_thumbnail_write_back_queues_no_conversion(self):
        """Storing the frame does not look like a replaced file."""
        enqueue = self.enqueue_during(self.write_back_thumbnail)
        self.assertEqual(conversion_calls(enqueue), [])

    def test_the_thumbnail_write_back_did_happen(self):
        """The write back these counts cover really took place."""
        self.enqueue_during(self.write_back_thumbnail)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail)
