"""Extraction and storage of the preview frame of a video."""

import logging
import subprocess
import tempfile
from pathlib import Path

import django_rq
from django.core.files import File
from redis.exceptions import RedisError

FFMPEG_BINARY = "ffmpeg"
FRAME_POSITION = "00:00:01"
FRAME_QUALITY = "2"
FRAME_TIMEOUT = 30
THUMBNAIL_SUFFIX = ".jpg"
INPUT_OPTIONS = ["-nostdin", "-y", "-ss", FRAME_POSITION]
OUTPUT_OPTIONS = ["-frames:v", "1", "-update", "1", "-q:v", FRAME_QUALITY]
EXTRACTION_FAILURE_MESSAGE = "Thumbnail frame could not be extracted."
ENQUEUE_FAILURE_MESSAGE = "Thumbnail extraction could not be queued."

logger = logging.getLogger(__name__)


class ThumbnailUnavailable(Exception):
    """Failure of the external program that grabs the frame."""


def build_command(source, destination):
    """Return the FFmpeg call that grabs one frame of this video."""
    return [
        FFMPEG_BINARY,
        *INPUT_OPTIONS,
        "-i",
        source,
        *OUTPUT_OPTIONS,
        destination,
    ]


def extract_frame(source, destination):
    """Write one frame of the video at source to destination."""
    try:
        subprocess.run(
            build_command(source, destination),
            capture_output=True,
            check=True,
            timeout=FRAME_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ThumbnailUnavailable(EXTRACTION_FAILURE_MESSAGE) from error


def store_thumbnail(video, frame):
    """Attach the frame at this path to the video as its thumbnail."""
    with frame.open("rb") as content:
        video.thumbnail.save(frame.name, File(content), save=False)
    video.save(update_fields=["thumbnail"])


def extract_thumbnail(video):
    """Grab a frame of this video's file and store it as a file."""
    with tempfile.TemporaryDirectory() as directory:
        frame = Path(directory) / f"{video.pk}{THUMBNAIL_SUFFIX}"
        extract_frame(video.video_file.path, str(frame))
        store_thumbnail(video, frame)


def create_thumbnail(video):
    """Store the preview frame of this video or log the failure."""
    try:
        extract_thumbnail(video)
    except ThumbnailUnavailable:
        logger.exception(EXTRACTION_FAILURE_MESSAGE)


def queue_thumbnail(video_id):
    """Queue the frame extraction of this video or log the loss."""
    from video_app.tasks import generate_thumbnail

    try:
        django_rq.get_queue().enqueue(generate_thumbnail, video_id)
    except RedisError:
        logger.exception(ENQUEUE_FAILURE_MESSAGE)
