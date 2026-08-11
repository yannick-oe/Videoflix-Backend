"""Tests for the route that serves the thumbnail directory."""

import importlib
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import clear_url_caches

import core.urls
from core.urls import THUMBNAIL_URL

THUMBNAIL_NAME = "poster.jpg"
THUMBNAIL_CONTENT = b"frame bytes"
VIDEO_NAME = "clip.mp4"
VIDEO_CONTENT = b"source bytes"
MISSING_NAME = "absent.jpg"
VIDEO_URL = f"{settings.MEDIA_URL}videos/{VIDEO_NAME}"
TRAVERSAL_URL = f"{THUMBNAIL_URL}../videos/{VIDEO_NAME}"


def reload_urlconf():
    """Rebuild the root URL configuration from the current settings."""
    clear_url_caches()
    importlib.reload(core.urls)


def write_file(path, content):
    """Store this content at the path and create its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ThumbnailRouteTests(SimpleTestCase):
    """Reachability of files below the media root over HTTP."""

    @classmethod
    def setUpClass(cls):
        """Fill a served media root with a thumbnail and a video."""
        super().setUpClass()
        root = Path(cls.serve_temporary_media())
        write_file(root / "thumbnails" / THUMBNAIL_NAME, THUMBNAIL_CONTENT)
        write_file(root / "videos" / VIDEO_NAME, VIDEO_CONTENT)

    @classmethod
    def serve_temporary_media(cls):
        """Point the route at a media root this class removes."""
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        cls.addClassCleanup(reload_urlconf)
        override = override_settings(DEBUG=True, MEDIA_ROOT=media.name)
        override.enable()
        cls.addClassCleanup(override.disable)
        reload_urlconf()
        return media.name

    def get(self, url):
        """Return the answer the media route gives for this URL."""
        return self.client.get(url)

    def test_stored_thumbnail_is_served(self):
        """A request for a stored thumbnail answers 200."""
        response = self.get(f"{THUMBNAIL_URL}{THUMBNAIL_NAME}")
        self.assertEqual(response.status_code, 200)

    def test_served_thumbnail_carries_the_stored_bytes(self):
        """The answer hands out the content of the stored file."""
        response = self.get(f"{THUMBNAIL_URL}{THUMBNAIL_NAME}")
        self.assertEqual(
            b"".join(response.streaming_content), THUMBNAIL_CONTENT
        )

    def test_absent_thumbnail_answers_404(self):
        """A thumbnail that was never stored answers 404."""
        response = self.get(f"{THUMBNAIL_URL}{MISSING_NAME}")
        self.assertEqual(response.status_code, 404)

    def test_video_directory_is_out_of_reach(self):
        """A source file below videos/ has no route at all."""
        self.assertEqual(self.get(VIDEO_URL).status_code, 404)

    def test_climbing_out_of_the_thumbnail_directory_fails(self):
        """A path leaving the thumbnail directory is refused."""
        self.assertEqual(self.get(TRAVERSAL_URL).status_code, 400)
