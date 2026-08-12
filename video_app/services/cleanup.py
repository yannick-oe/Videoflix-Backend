"""Removal of the files a video leaves behind on disk."""

import contextlib
import shutil
import tempfile
import time

STAGING_PATTERN = f"{tempfile.gettempprefix()}*"


def remove_video_files(video, directory):
    """Drop the renditions, the source and the frame of a video."""
    shutil.rmtree(directory, ignore_errors=True)
    video.video_file.delete(save=False)
    video.thumbnail.delete(save=False)


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
