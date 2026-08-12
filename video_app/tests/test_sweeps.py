"""Tests for the directories a conversion sweeps up after itself."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from video_app.services.cleanup import STAGING_PATTERN
from video_app.services.conversion import (
    PLAYLIST_NAME,
    RENDITIONS,
    STAGING_LIFETIME,
    video_directory,
)
from video_app.tests.test_conversion import (
    DEFAULT_RESOLUTION,
    FAILING_RESOLUTION,
    LOGGER,
    SEGMENT_CONTENT,
    SEGMENT_NAME,
    StoredVideoTestCase,
)

REAL_TEMPORARY_DIRECTORY = tempfile.TemporaryDirectory
AGE_MARGIN = 60
DANGLING_NAME = f"{tempfile.gettempprefix()}dangling"
ABSENT_NAME = "absent"


class SweepTestCase(StoredVideoTestCase):
    """A stored video whose HLS directory these tests inspect."""

    def parent(self):
        """Return the HLS directory of the stored video."""
        return video_directory(self.video.pk)

    def plant_staging(self, age):
        """Return a staging directory of this age in the parent."""
        self.parent().mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=self.parent()))
        (staging / SEGMENT_NAME).write_bytes(SEGMENT_CONTENT)
        stamp = time.time() - age
        os.utime(staging, (stamp, stamp))
        return staging

    def fail_job(self, resolution=DEFAULT_RESOLUTION):
        """Run a job whose FFmpeg cannot be started."""
        with self.assertLogs(LOGGER, level="ERROR"):
            self.run_job(resolution, behaviour=FileNotFoundError)


class EmptyParentTests(SweepTestCase):
    """The directory a video that converted into nothing leaves."""

    def test_a_total_failure_leaves_no_directory(self):
        """Three failed renditions leave nothing below hls/."""
        for resolution in RENDITIONS:
            self.fail_job(resolution)
        self.assertFalse(self.parent().exists())

    def test_a_single_failure_already_removes_it(self):
        """The directory goes as soon as it is left empty."""
        self.fail_job()
        self.assertFalse(self.parent().exists())

    def test_a_repeated_failure_raises_nothing(self):
        """Removing the directory a second time is no error."""
        self.fail_job()
        self.assertIsNone(self.fail_job())

    def test_a_finished_rendition_keeps_the_directory(self):
        """A resolution that converted is not swept away."""
        self.run_job()
        self.assertTrue(self.parent().exists())

    def test_a_failure_beside_a_rendition_keeps_the_directory(self):
        """A failure does not remove the renditions that worked."""
        self.run_job()
        self.fail_job(FAILING_RESOLUTION)
        self.assertTrue(self.directory(DEFAULT_RESOLUTION).exists())

    def test_a_working_sibling_keeps_the_directory(self):
        """A failure beside a running conversion keeps the parent."""
        sibling = self.plant_staging(0)
        self.fail_job(FAILING_RESOLUTION)
        self.assertTrue(sibling.exists())


class StagingSweepTests(SweepTestCase):
    """Staging directories a killed worker could have left behind."""

    def staging_names(self):
        """Return the staging directory names below the parent."""
        return {path.name for path in self.parent().glob(STAGING_PATTERN)}

    def test_a_stale_staging_directory_is_removed(self):
        """A directory older than any running job is swept away."""
        staging = self.plant_staging(STAGING_LIFETIME + AGE_MARGIN)
        self.run_job()
        self.assertFalse(staging.exists())

    def test_a_live_staging_directory_survives(self):
        """A directory a running conversion owns is left alone."""
        staging = self.plant_staging(0)
        self.run_job()
        self.assertTrue(staging.exists())

    def test_a_stale_one_goes_while_a_live_one_stays(self):
        """The sweep tells the two apart in the same directory."""
        self.plant_staging(STAGING_LIFETIME + AGE_MARGIN)
        live = self.plant_staging(0)
        self.run_job()
        self.assertEqual(self.staging_names(), {live.name})

    def test_the_sweep_leaves_the_renditions_alone(self):
        """A rendition of an earlier run survives the sweep."""
        self.run_job()
        self.plant_staging(STAGING_LIFETIME + AGE_MARGIN)
        self.run_job(FAILING_RESOLUTION)
        playlist = self.directory(DEFAULT_RESOLUTION) / PLAYLIST_NAME
        self.assertTrue(playlist.exists())

    def test_a_vanishing_entry_raises_nothing(self):
        """An entry that disappears during the sweep is skipped."""
        self.parent().mkdir(parents=True, exist_ok=True)
        dangling = self.parent() / DANGLING_NAME
        dangling.symlink_to(self.parent() / ABSENT_NAME)
        self.run_job()
        self.assertTrue(self.directory(DEFAULT_RESOLUTION).exists())


class VanishingParentTests(SweepTestCase):
    """A sibling that removes the parent at the worst moment."""

    def setUp(self):
        """Count how often a staging directory was asked for."""
        super().setUp()
        self.attempts = 0

    def staging_missing_once(self, **kwargs):
        """Remove the parent once, then hand out a real directory."""
        self.attempts += 1
        if self.attempts > 1:
            return REAL_TEMPORARY_DIRECTORY(**kwargs)
        Path(kwargs["dir"]).rmdir()
        raise FileNotFoundError

    def convert_against_a_lost_parent(self):
        """Run a job whose first staging directory cannot be made."""
        with patch("tempfile.TemporaryDirectory", self.staging_missing_once):
            self.run_job()

    def test_the_rendition_is_written_anyway(self):
        """The retried staging directory carries the conversion."""
        self.convert_against_a_lost_parent()
        playlist = self.directory(DEFAULT_RESOLUTION) / PLAYLIST_NAME
        self.assertTrue(playlist.exists())

    def test_the_parent_was_really_lost(self):
        """The first attempt did remove the parent it needed."""
        self.convert_against_a_lost_parent()
        self.assertEqual(self.attempts, 2)
