"""Tests for the HLS manifest endpoint."""

import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from video_app.models import Video
from video_app.services.conversion import PLAYLIST_NAME, video_directory

EMAIL = "user@example.com"
PASSWORD = "securepassword"
GARBAGE_TOKEN = "not-a-token"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
RESOLUTION = "480p"
OTHER_RESOLUTION = "1080p"
UNKNOWN_RESOLUTION = "240p"
MANIFEST_TYPE = "application/vnd.apple.mpegurl"
MANIFEST_BODY = b"#EXTM3U\n#EXT-X-VERSION:3\n000.ts\n#EXT-X-ENDLIST\n"
MISSING_ID = 9999


def store_file(path, content):
    """Store this content at the path and create its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class ManifestTestCase(TestCase):
    """Account, video and rendition every request needs."""

    @classmethod
    def setUpClass(cls):
        """Point MEDIA_ROOT at a directory this class removes."""
        super().setUpClass()
        media = tempfile.TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        cls.addClassCleanup(override.disable)

    def setUp(self):
        """Store an account and a video holding one rendition."""
        User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.video = Video.objects.create(
            title="Movie Title",
            description="Movie Description",
            category="Drama",
            video_file="videos/clip.mp4",
        )
        self.manifest = self.manifest_path(RESOLUTION)
        store_file(self.manifest, MANIFEST_BODY)

    def manifest_path(self, resolution):
        """Return the playlist path of one rendition of the video."""
        return video_directory(self.video.pk) / resolution / PLAYLIST_NAME

    def url(self, movie_id=None, resolution=RESOLUTION):
        """Return the manifest URL of a video and a resolution."""
        return reverse(
            "video-manifest",
            kwargs={
                "movie_id": self.video.pk if movie_id is None else movie_id,
                "resolution": resolution,
            },
        )

    def unknown_resolution_url(self):
        """Return a manifest URL naming a resolution nobody offers."""
        return self.url().replace(RESOLUTION, UNKNOWN_RESOLUTION)

    def log_in(self):
        """Log the account in so the client holds both cookies."""
        self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )


class ManifestResponseTests(ManifestTestCase):
    """Answer an authenticated request for a manifest receives."""

    def setUp(self):
        """Log the account in before addressing the endpoint."""
        super().setUp()
        self.log_in()

    def test_stored_manifest_is_served(self):
        """A request for a stored manifest answers 200."""
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_manifest_carries_the_documented_content_type(self):
        """The answer names the HLS media type of the documentation."""
        response = self.client.get(self.url())
        self.assertEqual(response["Content-Type"], MANIFEST_TYPE)

    def test_manifest_body_matches_the_file_on_disk(self):
        """The body hands out the bytes the conversion wrote."""
        response = self.client.get(self.url())
        self.assertEqual(
            b"".join(response.streaming_content), self.manifest.read_bytes()
        )

    def test_every_converted_rendition_is_reachable(self):
        """A second resolution answers on its own URL."""
        store_file(self.manifest_path(OTHER_RESOLUTION), MANIFEST_BODY)
        url = self.url(resolution=OTHER_RESOLUTION)
        self.assertEqual(self.client.get(url).status_code, 200)


class ManifestNotFoundTests(ManifestTestCase):
    """Requests the manifest endpoint answers with 404."""

    def setUp(self):
        """Log the account in before addressing the endpoint."""
        super().setUp()
        self.log_in()

    def test_unknown_video_answers_404(self):
        """A manifest of a video that does not exist answers 404."""
        response = self.client.get(self.url(movie_id=MISSING_ID))
        self.assertEqual(response.status_code, 404)

    def test_unknown_resolution_answers_404(self):
        """A resolution the catalogue never offers answers 404."""
        response = self.client.get(self.unknown_resolution_url())
        self.assertEqual(response.status_code, 404)

    def test_unconverted_resolution_answers_404(self):
        """A resolution this video was not converted into answers 404."""
        response = self.client.get(self.url(resolution=OTHER_RESOLUTION))
        self.assertEqual(response.status_code, 404)

    def test_absent_manifest_answers_404(self):
        """A rendition directory without a playlist answers 404."""
        self.manifest.unlink()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_failed_conversion_answers_404(self):
        """A video whose conversion wrote nothing answers 404."""
        shutil.rmtree(video_directory(self.video.pk))
        self.assertEqual(self.client.get(self.url()).status_code, 404)


class ManifestAuthorizationTests(ManifestTestCase):
    """Requests the manifest endpoint turns away."""

    def test_request_without_a_cookie_is_rejected(self):
        """A request without the access cookie answers 401."""
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_rejected_request_carries_a_json_body(self):
        """The refusal names its reason in a JSON body."""
        self.assertIn("detail", self.client.get(self.url()).json())

    def test_request_with_a_garbage_cookie_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_logged_out_user_cannot_read_the_manifest(self):
        """After a logout the manifest endpoint answers 401."""
        self.log_in()
        self.client.post(reverse("logout"), content_type="application/json")
        self.assertEqual(self.client.get(self.url()).status_code, 401)
