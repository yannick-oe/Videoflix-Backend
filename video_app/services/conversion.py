"""Conversion of a stored video into its HLS renditions."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import django_rq
from django.conf import settings
from redis.exceptions import RedisError

from video_app.services.cleanup import remove_if_empty, sweep_staging

FFMPEG_BINARY = "ffmpeg"
HLS_DIRECTORY = "hls"
PLAYLIST_NAME = "index.m3u8"
SEGMENT_PATTERN = "%03d.ts"
SEGMENT_SECONDS = "4"
SCALE_WIDTH = "-2"
CONVERSION_TIMEOUT = 600
STAGING_LIFETIME = CONVERSION_TIMEOUT * 2
RENDITIONS = {"480p": "480", "720p": "720", "1080p": "1080"}
INPUT_OPTIONS = ["-nostdin", "-y"]
STREAM_OPTIONS = ["-map", "0:v:0", "-map", "0:a:0?"]
VIDEO_OPTIONS = [
    "-c:v",
    "libx264",
    "-preset",
    "veryfast",
    "-crf",
    "23",
    "-pix_fmt",
    "yuv420p",
    "-force_key_frames",
    f"expr:gte(t,n_forced*{SEGMENT_SECONDS})",
]
AUDIO_OPTIONS = ["-c:a", "aac", "-b:a", "128k"]
PLAYLIST_OPTIONS = [
    "-f",
    "hls",
    "-hls_time",
    SEGMENT_SECONDS,
    "-hls_playlist_type",
    "vod",
]
CONVERSION_FAILURE_MESSAGE = "HLS rendition could not be created."
ENQUEUE_FAILURE_MESSAGE = "HLS conversion could not be queued."

logger = logging.getLogger(__name__)


class RenditionUnavailable(Exception):
    """Failure of the external program that converts the video."""


def video_directory(video_id):
    """Return the directory holding the renditions of a video."""
    return Path(settings.MEDIA_ROOT) / HLS_DIRECTORY / str(video_id)


def output_options(destination, height):
    """Return the options that shape and place one rendition."""
    return [
        "-vf",
        f"scale={SCALE_WIDTH}:{height}",
        *VIDEO_OPTIONS,
        *AUDIO_OPTIONS,
        *PLAYLIST_OPTIONS,
        "-hls_segment_filename",
        str(destination / SEGMENT_PATTERN),
    ]


def build_command(source, destination, height):
    """Return the FFmpeg call that writes one HLS rendition."""
    return [
        FFMPEG_BINARY,
        *INPUT_OPTIONS,
        "-i",
        source,
        *STREAM_OPTIONS,
        *output_options(destination, height),
        str(destination / PLAYLIST_NAME),
    ]


def run_conversion(source, destination, height):
    """Write the HLS rendition of this height into destination."""
    try:
        subprocess.run(
            build_command(source, destination, height),
            capture_output=True,
            check=True,
            timeout=CONVERSION_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RenditionUnavailable(CONVERSION_FAILURE_MESSAGE) from error


def replace_rendition(staging, destination):
    """Put the rendition built in staging where it is served."""
    shutil.rmtree(destination, ignore_errors=True)
    shutil.move(str(staging), str(destination))


def open_staging(parent):
    """Return a staging directory inside the directory of a video."""
    parent.mkdir(parents=True, exist_ok=True)
    try:
        return tempfile.TemporaryDirectory(dir=parent)
    except FileNotFoundError:
        parent.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=parent)


def build_rendition(video, resolution):
    """Convert this video into the rendition of one resolution."""
    parent = video_directory(video.pk)
    with open_staging(parent) as staging:
        height = RENDITIONS[resolution]
        run_conversion(video.video_file.path, Path(staging), height)
        replace_rendition(staging, parent / resolution)


def create_rendition(video, resolution):
    """Store one HLS rendition of this video or log the failure."""
    parent = video_directory(video.pk)
    sweep_staging(parent, STAGING_LIFETIME)
    try:
        build_rendition(video, resolution)
    except RenditionUnavailable:
        logger.exception(CONVERSION_FAILURE_MESSAGE)
    remove_if_empty(parent)


def queue_renditions(video_id):
    """Queue one conversion job for each offered resolution."""
    from video_app.tasks import generate_rendition

    try:
        queue = django_rq.get_queue()
        for resolution in RENDITIONS:
            queue.enqueue(generate_rendition, video_id, resolution)
    except RedisError:
        logger.exception(ENQUEUE_FAILURE_MESSAGE)
