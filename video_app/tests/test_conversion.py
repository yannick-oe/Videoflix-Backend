"""Tests for the HLS conversion job and the files it writes."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from redis.exceptions import ConnectionError as RedisConnectionError

from video_app.services.conversion import (
    CONVERSION_FAILURE_MESSAGE,
    CONVERSION_TIMEOUT,
    ENQUEUE_FAILURE_MESSAGE,
    FFMPEG_BINARY,
    HLS_DIRECTORY,
    PLAYLIST_NAME,
    RENDITIONS,
    SCALE_WIDTH,
    SEGMENT_SECONDS,
    video_directory,
)
from video_app.services.thumbnail import (
    ENQUEUE_FAILURE_MESSAGE as THUMBNAIL_ENQUEUE_MESSAGE,
)
from video_app.tasks import generate_rendition
from video_app.tests.test_thumbnail import TemporaryMediaTestCase, create_video

LOGGER = "video_app.services.conversion"
THUMBNAIL_LOGGER = "video_app.services.thumbnail"
VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"uploaded bytes"
PLAYLIST_CONTENT = "#EXTM3U\n000.ts\n"
SEGMENT_NAME = "000.ts"
SEGMENT_CONTENT = b"segment bytes"
STALE_NAME = "099.ts"
STALE_CONTENT = b"stale bytes"
DEFAULT_RESOLUTION = "480p"
FAILING_RESOLUTION = "720p"
MISSING_ID = 9999


def fake_ffmpeg(command, **kwargs):
    """Write playlist and segment where the FFmpeg call would."""
    destination = Path(command[-1]).parent
    (destination / PLAYLIST_NAME).write_text(PLAYLIST_CONTENT)
    (destination / SEGMENT_NAME).write_bytes(SEGMENT_CONTENT)
    return subprocess.CompletedProcess(command, 0)


def conversion_calls(enqueue):
    """Return the calls this mock took for the HLS conversion."""
    return [
        call
        for call in enqueue.call_args_list
        if call.args[0] is generate_rendition
    ]


class ConversionEnqueueTests(TemporaryMediaTestCase):
    """Storing a video hands every rendition to the queue."""

    def store(self, **overrides):
        """Store a video and return its queued conversion calls."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                self.video = create_video(**overrides)
        return conversion_calls(get_queue.return_value.enqueue)

    def test_a_new_video_queues_every_rendition(self):
        """Storing a video queues one job per offered resolution."""
        self.assertEqual(len(self.store()), len(RENDITIONS))

    def test_the_queued_resolutions_are_the_offered_ones(self):
        """The queued jobs carry the three resolutions on offer."""
        resolutions = [call.args[2] for call in self.store()]
        self.assertEqual(resolutions, list(RENDITIONS))

    def test_the_queued_argument_is_the_video_id(self):
        """The queue receives the id, not the video object."""
        self.assertIsInstance(self.store()[0].args[1], int)

    def test_an_uploaded_thumbnail_still_queues_the_renditions(self):
        """A video that brings its own thumbnail is still converted."""
        calls = self.store(
            thumbnail=SimpleUploadedFile(THUMBNAIL_NAME, THUMBNAIL_CONTENT)
        )
        self.assertEqual(len(calls), len(RENDITIONS))


class ConversionEnqueueFailureTests(TestCase):
    """A queue that refuses the conversion jobs."""

    def store_with_broken_queue(self):
        """Store a video while the queue rejects every connection."""
        with self.assertLogs(THUMBNAIL_LOGGER, level="ERROR") as logs:
            with patch(
                "django_rq.get_queue", side_effect=RedisConnectionError
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    video = create_video()
        self.assertIn(THUMBNAIL_ENQUEUE_MESSAGE, logs.output[0])
        return video

    def test_the_lost_jobs_are_logged(self):
        """An unreachable queue leaves an error in the log."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            self.store_with_broken_queue()
        self.assertIn(ENQUEUE_FAILURE_MESSAGE, logs.output[0])

    def test_the_video_survives_the_lost_jobs(self):
        """The video stays stored although its jobs were lost."""
        with self.assertLogs(LOGGER, level="ERROR"):
            video = self.store_with_broken_queue()
        self.assertIsNotNone(video.pk)


class StoredVideoTestCase(TemporaryMediaTestCase):
    """A stored video the conversion job can be run against."""

    def setUp(self):
        """Store the video every one of these jobs converts."""
        self.video = create_video(
            video_file=SimpleUploadedFile(VIDEO_NAME, VIDEO_CONTENT)
        )

    def run_job(self, resolution=DEFAULT_RESOLUTION, behaviour=fake_ffmpeg):
        """Run one conversion job with this stand-in for FFmpeg."""
        with patch("subprocess.run", side_effect=behaviour) as process:
            generate_rendition(self.video.pk, resolution)
        return process

    def directory(self, resolution):
        """Return the directory this rendition is written into."""
        return video_directory(self.video.pk) / resolution

    def entries(self):
        """Return the names below the HLS directory of this video."""
        directory = video_directory(self.video.pk)
        if not directory.exists():
            return set()
        return {path.name for path in directory.iterdir()}


class ConversionCommandTests(StoredVideoTestCase):
    """What the worker runs once a conversion job starts."""

    def command(self, resolution=DEFAULT_RESOLUTION):
        """Return the argument list the job handed to FFmpeg."""
        return self.run_job(resolution).call_args.args[0]

    def after(self, flag, resolution=DEFAULT_RESOLUTION):
        """Return the command argument following this flag."""
        command = self.command(resolution)
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

    def test_every_rendition_scales_to_its_own_height(self):
        """Each resolution asks for the height that names it."""
        for resolution, height in RENDITIONS.items():
            scale = f"scale={SCALE_WIDTH}:{height}"
            self.assertEqual(self.after("-vf", resolution), scale)

    def test_the_scaled_width_stays_even(self):
        """The width follows the aspect ratio and stays divisible."""
        self.assertEqual(SCALE_WIDTH, "-2")

    def test_the_video_track_is_mapped(self):
        """The call takes the first video track of the source."""
        self.assertIn("0:v:0", self.command())

    def test_the_audio_track_is_optional(self):
        """A source without audio does not fail the call."""
        self.assertIn("0:a:0?", self.command())

    def test_the_audio_track_is_re_encoded(self):
        """A source with audio keeps it in a supported codec."""
        self.assertEqual(self.after("-c:a"), "aac")

    def test_the_playlist_is_written_for_video_on_demand(self):
        """The playlist declares the complete recording."""
        self.assertEqual(self.after("-hls_playlist_type"), "vod")

    def test_the_segments_are_bounded_in_length(self):
        """The call cuts the stream into segments of fixed length."""
        self.assertEqual(self.after("-hls_time"), SEGMENT_SECONDS)

    def test_the_keyframes_follow_the_segment_length(self):
        """The call forces a keyframe on every segment boundary."""
        self.assertIn(SEGMENT_SECONDS, self.after("-force_key_frames"))

    def test_the_segments_are_numbered(self):
        """The segment names the playlist points at are numbered."""
        self.assertTrue(self.after("-hls_segment_filename").endswith(".ts"))

    def test_the_call_carries_its_own_timeout(self):
        """The call bounds FFmpeg below the timeout of the queue."""
        timeout = self.run_job().call_args.kwargs["timeout"]
        self.assertEqual(timeout, CONVERSION_TIMEOUT)

    def test_the_timeout_stays_below_the_queue_ceiling(self):
        """The job ends by itself before the queue kills it."""
        ceiling = settings.RQ_QUEUES["default"]["DEFAULT_TIMEOUT"]
        self.assertLess(CONVERSION_TIMEOUT, ceiling)

    def test_a_failing_exit_code_is_raised(self):
        """The call turns a non-zero exit code into an error."""
        self.assertTrue(self.run_job().call_args.kwargs["check"])


class RenditionPathTests(StoredVideoTestCase):
    """Where a finished conversion leaves playlist and segments."""

    def relative(self, path):
        """Return this path as the streaming route would spell it."""
        return str(path.relative_to(settings.MEDIA_ROOT))

    def test_the_playlist_lands_where_the_route_expects_it(self):
        """The playlist path is the streaming route by substitution."""
        self.run_job()
        playlist = self.directory(DEFAULT_RESOLUTION) / PLAYLIST_NAME
        expected = f"{HLS_DIRECTORY}/{self.video.pk}/480p/{PLAYLIST_NAME}"
        self.assertEqual(self.relative(playlist), expected)

    def test_the_segment_lands_next_to_its_playlist(self):
        """A segment is addressed by the playlist directory and name."""
        self.run_job()
        segment = self.directory(DEFAULT_RESOLUTION) / SEGMENT_NAME
        expected = f"{HLS_DIRECTORY}/{self.video.pk}/480p/{SEGMENT_NAME}"
        self.assertEqual(self.relative(segment), expected)

    def test_every_rendition_writes_its_own_playlist(self):
        """All three resolutions end up with a playlist of their own."""
        for resolution in RENDITIONS:
            self.run_job(resolution)
            playlist = self.directory(resolution) / PLAYLIST_NAME
            self.assertTrue(playlist.exists())

    def test_the_renditions_do_not_share_a_directory(self):
        """Each resolution keeps its segments in its own directory."""
        for resolution in RENDITIONS:
            self.run_job(resolution)
        directories = {self.directory(name) for name in RENDITIONS}
        self.assertEqual(len(directories), len(RENDITIONS))

    def test_the_job_leaves_no_staging_directory(self):
        """The directory FFmpeg wrote into is gone once it ran."""
        self.run_job()
        self.assertEqual(self.entries(), {DEFAULT_RESOLUTION})


class RepeatedConversionTests(StoredVideoTestCase):
    """A conversion that runs a second time over its own output."""

    def stale_segment(self):
        """Return the segment left behind by a longer earlier run."""
        return self.directory(DEFAULT_RESOLUTION) / STALE_NAME

    def convert_twice(self):
        """Run the job, leave a stale segment, run it again."""
        self.run_job()
        self.stale_segment().write_bytes(STALE_CONTENT)
        self.run_job()

    def test_the_stale_segment_is_gone(self):
        """A second run does not keep segments of the first one."""
        self.convert_twice()
        self.assertFalse(self.stale_segment().exists())

    def test_the_fresh_playlist_is_there(self):
        """A second run leaves a complete rendition behind."""
        self.convert_twice()
        playlist = self.directory(DEFAULT_RESOLUTION) / PLAYLIST_NAME
        self.assertEqual(playlist.read_text(), PLAYLIST_CONTENT)

    def test_the_second_run_leaves_no_staging_directory(self):
        """Two runs leave the rendition directory and nothing else."""
        self.convert_twice()
        self.assertEqual(self.entries(), {DEFAULT_RESOLUTION})


class FailingConversionTests(StoredVideoTestCase):
    """A conversion the external program does not finish."""

    def fail_with(self, error, resolution=DEFAULT_RESOLUTION):
        """Run the job against an FFmpeg raising this error."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            self.run_job(resolution, behaviour=error)
        return logs

    def test_a_failing_exit_code_is_logged(self):
        """FFmpeg reporting a failure leaves an error in the log."""
        logs = self.fail_with(subprocess.CalledProcessError(1, FFMPEG_BINARY))
        self.assertIn(CONVERSION_FAILURE_MESSAGE, logs.output[0])

    def test_a_timeout_is_logged(self):
        """FFmpeg exceeding its timeout leaves an error in the log."""
        logs = self.fail_with(
            subprocess.TimeoutExpired(FFMPEG_BINARY, CONVERSION_TIMEOUT)
        )
        self.assertIn(CONVERSION_FAILURE_MESSAGE, logs.output[0])

    def test_a_missing_ffmpeg_is_logged(self):
        """An FFmpeg that cannot be started leaves an error too."""
        logs = self.fail_with(FileNotFoundError)
        self.assertIn(CONVERSION_FAILURE_MESSAGE, logs.output[0])

    def test_a_failure_writes_no_rendition(self):
        """The failing resolution has no directory to be served."""
        self.fail_with(subprocess.CalledProcessError(1, FFMPEG_BINARY))
        self.assertFalse(self.directory(DEFAULT_RESOLUTION).exists())

    def test_a_failing_rendition_leaves_the_others_intact(self):
        """The two resolutions that converted stay playable."""
        self.run_job("480p")
        self.fail_with(FileNotFoundError, FAILING_RESOLUTION)
        self.run_job("1080p")
        survivors = [self.directory("480p"), self.directory("1080p")]
        self.assertTrue(all(path.exists() for path in survivors))

    def test_a_failing_rendition_keeps_its_own_directory_empty(self):
        """The failing resolution leaves no directory behind."""
        self.run_job("480p")
        self.fail_with(FileNotFoundError, FAILING_RESOLUTION)
        self.assertFalse(self.directory(FAILING_RESOLUTION).exists())

    def test_a_failure_leaves_no_staging_directory(self):
        """A failed run cleans up the directory FFmpeg wrote into."""
        self.fail_with(FileNotFoundError)
        self.assertEqual(self.entries(), set())


class MissingVideoConversionTests(TestCase):
    """A job whose video disappeared before the worker took it."""

    def test_the_job_starts_no_process(self):
        """A job for an absent video never reaches FFmpeg."""
        with patch("subprocess.run") as process:
            generate_rendition(MISSING_ID, DEFAULT_RESOLUTION)
        process.assert_not_called()

    def test_a_deleted_video_ends_the_job_quietly(self):
        """A job for a deleted video raises nothing."""
        video = create_video()
        video.delete()
        with patch("subprocess.run"):
            result = generate_rendition(video.pk, DEFAULT_RESOLUTION)
        self.assertIsNone(result)
