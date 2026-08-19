"""Removal of the files a video leaves behind on disk."""

import contextlib
import logging
import shutil
import tempfile
import time

from django.db import transaction

STAGING_PATTERN = f"{tempfile.gettempprefix()}*"
REMOVAL_FAILURE_MESSAGE = "A file of a video could not be removed."

logger = logging.getLogger(__name__)


def discard_file(stored):
    """Drop this stored file, logging a removal that cannot finish."""
    try:
        stored.delete(save=False)
    except OSError:
        logger.exception(REMOVAL_FAILURE_MESSAGE)


def remove_video_files(video, directory):
    """Drop the renditions, the source and the frame of a video."""
    shutil.rmtree(directory, ignore_errors=True)
    discard_file(video.video_file)
    discard_file(video.thumbnail)


def remove_replaced_file(storage, previous, current):
    """Drop the file a replacement pushed aside, if it holds one."""
    if not previous or previous == current:
        return
    try:
        storage.delete(previous)
    except OSError:
        logger.exception(REMOVAL_FAILURE_MESSAGE)


def remove_replaced_file_on_commit(storage, previous, current):
    """Drop the replaced file once the row replacing it holds."""
    transaction.on_commit(
        lambda: remove_replaced_file(storage, previous, current)
    )


def remove_if_empty(directory):
    """Remove this directory as long as nothing lies in it."""
    with contextlib.suppress(OSError):
        directory.rmdir()


def outlived_every_conversion(staging, lifetime, now):
    """Tell whether no running conversion can own this directory."""
    try:
        return now - staging.stat().st_mtime > lifetime
    except OSError:
        return False


def sweep_staging(directory, lifetime):
    """Remove the staging directories of conversions long gone."""
    now = time.time()
    for staging in directory.glob(STAGING_PATTERN):
        if outlived_every_conversion(staging, lifetime, now):
            shutil.rmtree(staging, ignore_errors=True)
