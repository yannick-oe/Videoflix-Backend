"""Tests for the thumbnail job and the frame it extracts."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from redis.exceptions import ConnectionError as RedisConnectionError

from video_app.models import Video
from video_app.services.thumbnail import (
    ENQUEUE_FAILURE_MESSAGE,
    EXTRACTION_FAILURE_MESSAGE,
    FFMPEG_BINARY,
    FRAME_TIMEOUT,
    THUMBNAIL_SUFFIX,
)
from video_app.tasks import generate_thumbnail

LOGGER = "video_app.services.thumbnail"
TITLE = "Movie Title"
NEW_TITLE = "Corrected Title"
DESCRIPTION = "Movie Description"
CATEGORY = "Drama"
VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"uploaded bytes"
FRAME_CONTENT = b"extracted frame"
MISSING_ID = 9999


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


def fake_ffmpeg(command, **kwargs):
    """Write frame bytes where the FFmpeg call would write them."""
    Path(command[-1]).write_bytes(FRAME_CONTENT)
    return subprocess.CompletedProcess(command, 0)


def thumbnail_enqueue(enqueue):
    """Return a mock holding the frame extraction calls only."""
    calls = Mock()
    for call in enqueue.call_args_list:
        if call.args[0] is generate_thumbnail:
            calls(*call.args, **call.kwargs)
    return calls


class TemporaryMediaTestCase(TestCase):
    """Media root every test writing a file needs."""

    @classmethod
    def setUpClass(cls):
        """Point MEDIA_ROOT at a directory this class removes."""
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        cls.addClassCleanup(override.disable)


class ThumbnailEnqueueTests(TemporaryMediaTestCase):
    """Storing a video hands the frame extraction to the queue."""

    def store(self, **overrides):
        """Store a video and return its mocked extraction calls."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                self.video = create_video(**overrides)
        return thumbnail_enqueue(get_queue.return_value.enqueue)

    def test_new_video_queues_one_job(self):
        """Storing a video queues exactly one job."""
        self.assertEqual(self.store().call_count, 1)

    def test_queued_job_is_the_frame_extraction(self):
        """The queued job generates the thumbnail of that video."""
        enqueue = self.store()
        enqueue.assert_called_once_with(generate_thumbnail, self.video.pk)

    def test_queued_argument_is_the_video_id(self):
        """The queue receives the id, not the video object."""
        argument = self.store().call_args.args[1]
        self.assertIsInstance(argument, int)

    def test_uploaded_thumbnail_queues_no_job(self):
        """A video that arrives with a thumbnail queues nothing."""
        enqueue = self.store(
            thumbnail=SimpleUploadedFile(THUMBNAIL_NAME, THUMBNAIL_CONTENT)
        )
        self.assertEqual(enqueue.call_count, 0)


class ThumbnailCommitTests(TestCase):
    """The job reaches the queue only once the row is committed."""

    def test_nothing_is_queued_before_the_commit(self):
        """No job leaves while the storing transaction is open."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                create_video()
                pending = get_queue.return_value.enqueue.call_count
        self.assertEqual(pending, 0)

    def test_the_job_is_queued_after_the_commit(self):
        """The same job leaves as soon as the transaction commits."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                create_video()
        enqueue = thumbnail_enqueue(get_queue.return_value.enqueue)
        self.assertEqual(enqueue.call_count, 1)


class ThumbnailReenqueueTests(TemporaryMediaTestCase):
    """Saves that must not put a second job into the queue."""

    def setUp(self):
        """Store the video every one of these saves starts from."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )

    def enqueues_during(self, action):
        """Return how many jobs this action puts into the queue."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                action()
        return get_queue.return_value.enqueue.call_count

    def run_job(self):
        """Run the thumbnail job with a stand-in for FFmpeg."""
        with patch("subprocess.run", side_effect=fake_ffmpeg):
            generate_thumbnail(self.video.pk)

    def test_storing_the_frame_queues_no_further_job(self):
        """Writing the thumbnail back does not queue another job."""
        self.assertEqual(self.enqueues_during(self.run_job), 0)

    def test_storing_the_frame_did_happen(self):
        """The write back this count covers really took place."""
        self.enqueues_during(self.run_job)
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail)

    def test_editing_the_title_queues_no_job(self):
        """Correcting a title does not queue a frame extraction."""

        def rename():
            self.video.title = NEW_TITLE
            self.video.save()

        self.assertEqual(self.enqueues_during(rename), 0)


class ThumbnailEnqueueFailureTests(TestCase):
    """A queue that refuses the frame extraction job."""

    def store_with_broken_queue(self):
        """Store a video while the queue rejects every connection."""
        with patch("django_rq.get_queue", side_effect=RedisConnectionError):
            with self.captureOnCommitCallbacks(execute=True):
                return create_video()

    def test_the_lost_job_is_logged(self):
        """An unreachable queue leaves an error in the log."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            self.store_with_broken_queue()
        self.assertIn(ENQUEUE_FAILURE_MESSAGE, logs.output[0])

    def test_the_video_survives_the_lost_job(self):
        """The video stays stored although its job was lost."""
        with self.assertLogs(LOGGER, level="ERROR"):
            video = self.store_with_broken_queue()
        self.assertTrue(Video.objects.filter(pk=video.pk).exists())


class ThumbnailExtractionTests(TemporaryMediaTestCase):
    """What the worker runs once the frame extraction job starts."""

    def setUp(self):
        """Store the video whose frame the job extracts."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )

    def run_job(self, behaviour=fake_ffmpeg):
        """Run the job with this stand-in and return the mock."""
        with patch("subprocess.run", side_effect=behaviour) as process:
            generate_thumbnail(self.video.pk)
        return process

    def command(self):
        """Return the argument list the job handed to FFmpeg."""
        return self.run_job().call_args.args[0]

    def keyword(self, name):
        """Return this keyword argument of the FFmpeg call."""
        return self.run_job().call_args.kwargs[name]

    def after(self, flag):
        """Return the command argument following this flag."""
        command = self.command()
        return command[command.index(flag) + 1]

    def test_ffmpeg_is_called_as_an_argument_list(self):
        """The call passes a list, so no shell parses it."""
        self.assertIsInstance(self.command(), list)

    def test_the_command_runs_ffmpeg(self):
        """The program the job starts is FFmpeg."""
        self.assertEqual(self.command()[0], FFMPEG_BINARY)

    def test_no_shell_is_involved(self):
        """The call leaves shell interpretation switched off."""
        self.assertNotIn("shell", self.run_job().call_args.kwargs)

    def test_the_command_reads_the_stored_video_file(self):
        """The input of the call is the stored video file."""
        self.assertEqual(self.after("-i"), self.video.video_file.path)

    def test_the_command_writes_a_single_image(self):
        """The call writes one image and no image sequence."""
        self.assertEqual(self.after("-update"), "1")

    def test_the_command_takes_one_frame(self):
        """The call stops after the first extracted frame."""
        self.assertEqual(self.after("-frames:v"), "1")

    def test_the_command_writes_a_jpeg(self):
        """The destination of the call carries the image suffix."""
        self.assertTrue(self.command()[-1].endswith(THUMBNAIL_SUFFIX))

    def test_the_call_carries_its_own_timeout(self):
        """The call bounds FFmpeg below the timeout of the queue."""
        self.assertEqual(self.keyword("timeout"), FRAME_TIMEOUT)

    def test_a_failing_exit_code_is_raised(self):
        """The call turns a non-zero exit code into an error."""
        self.assertTrue(self.keyword("check"))

    def test_the_extracted_frame_becomes_the_thumbnail(self):
        """The video carries a thumbnail once the job ran."""
        self.run_job()
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail)

    def test_the_thumbnail_lands_in_its_subdirectory(self):
        """The stored thumbnail is written below thumbnails/."""
        self.run_job()
        self.video.refresh_from_db()
        self.assertTrue(self.video.thumbnail.name.startswith("thumbnails/"))

    def test_the_thumbnail_carries_the_extracted_frame(self):
        """The stored file holds the bytes FFmpeg wrote."""
        self.run_job()
        self.video.refresh_from_db()
        self.assertEqual(self.video.thumbnail.read(), FRAME_CONTENT)

    def test_the_temporary_frame_is_removed(self):
        """The job leaves no file outside the media directory."""
        destination = Path(self.command()[-1])
        self.assertFalse(destination.parent.exists())


class FailingExtractionTests(TemporaryMediaTestCase):
    """A frame extraction the external program does not finish."""

    def setUp(self):
        """Store the video whose extraction is going to fail."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )

    def fail_with(self, error):
        """Run the job against an FFmpeg raising this error."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            with patch("subprocess.run", side_effect=error):
                generate_thumbnail(self.video.pk)
        return logs

    def test_a_failing_exit_code_is_logged(self):
        """FFmpeg reporting a failure leaves an error in the log."""
        logs = self.fail_with(subprocess.CalledProcessError(1, FFMPEG_BINARY))
        self.assertIn(EXTRACTION_FAILURE_MESSAGE, logs.output[0])

    def test_a_timeout_is_logged(self):
        """FFmpeg exceeding its timeout leaves an error in the log."""
        logs = self.fail_with(
            subprocess.TimeoutExpired(FFMPEG_BINARY, FRAME_TIMEOUT)
        )
        self.assertIn(EXTRACTION_FAILURE_MESSAGE, logs.output[0])

    def test_a_missing_ffmpeg_is_logged(self):
        """An FFmpeg that cannot be started leaves an error too."""
        logs = self.fail_with(FileNotFoundError)
        self.assertIn(EXTRACTION_FAILURE_MESSAGE, logs.output[0])

    def test_a_failure_leaves_the_thumbnail_empty(self):
        """The video keeps an empty thumbnail after a failure."""
        self.fail_with(subprocess.CalledProcessError(1, FFMPEG_BINARY))
        self.video.refresh_from_db()
        self.assertFalse(self.video.thumbnail)


class MissingVideoTests(TestCase):
    """A job whose video disappeared before the worker took it."""

    def test_the_job_starts_no_process(self):
        """A job for an absent video never reaches FFmpeg."""
        with patch("subprocess.run") as process:
            generate_thumbnail(MISSING_ID)
        process.assert_not_called()

    def test_a_deleted_video_ends_the_job_quietly(self):
        """A job for a deleted video raises nothing."""
        video = create_video()
        video.delete()
        with patch("subprocess.run"):
            self.assertIsNone(generate_thumbnail(video.pk))
