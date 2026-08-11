"""Tests for the video list endpoint."""

import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from video_app.models import Video

EMAIL = "user@example.com"
PASSWORD = "securepassword"
GARBAGE_TOKEN = "not-a-token"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
TITLE = "Movie Title"
DESCRIPTION = "Movie Description"
CATEGORY = "Drama"
THUMBNAIL_NAME = "cover.jpg"
THUMBNAIL_CONTENT = b"binary"
FIELD_ORDER = [
    "id",
    "created_at",
    "title",
    "description",
    "thumbnail_url",
    "category",
]


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


def backdate(video, day):
    """Move the creation date of a video to a day in January 2023."""
    Video.objects.filter(pk=video.pk).update(
        created_at=datetime(2023, 1, day, tzinfo=timezone.utc)
    )


class VideoListTestCase(TestCase):
    """Account, endpoint and media directory every request needs."""

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
        """Create an active account and address the list endpoint."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.url = reverse("video-list")

    def log_in(self):
        """Log the account in so the client holds both cookies."""
        self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )

    def entries(self):
        """Return the body the list endpoint hands out."""
        return self.client.get(self.url).json()


class VideoListResponseTests(VideoListTestCase):
    """Shape of the answer an authenticated request receives."""

    def setUp(self):
        """Store one video with a thumbnail and log the account in."""
        super().setUp()
        self.video = create_video(
            thumbnail=SimpleUploadedFile(THUMBNAIL_NAME, THUMBNAIL_CONTENT)
        )
        self.log_in()

    def entry(self):
        """Return the single entry the list endpoint hands out."""
        return self.entries()[0]

    def test_authenticated_request_is_answered(self):
        """A request carrying the access cookie answers 200."""
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_body_is_a_bare_array(self):
        """The body is a list, not a pagination wrapper."""
        self.assertIsInstance(self.entries(), list)

    def test_entry_carries_the_documented_keys(self):
        """An entry carries the six documented keys, in order."""
        self.assertEqual(list(self.entry()), FIELD_ORDER)

    def test_thumbnail_url_is_absolute(self):
        """The thumbnail URL carries a scheme and a host."""
        parts = urlparse(self.entry()["thumbnail_url"])
        self.assertTrue(parts.scheme and parts.netloc)

    def test_thumbnail_url_points_at_the_uploaded_file(self):
        """The thumbnail URL ends in the path of the stored file."""
        self.assertTrue(
            self.entry()["thumbnail_url"].endswith(self.video.thumbnail.url)
        )

    def test_category_reaches_the_client_filled(self):
        """The category is neither null nor an empty string."""
        self.assertEqual(self.entry()["category"], CATEGORY)


class ThumbnaillessVideoTests(VideoListTestCase):
    """The answer for a video whose thumbnail does not exist yet."""

    def test_thumbnail_url_is_null_without_a_file(self):
        """A video without a thumbnail reports a null URL."""
        create_video()
        self.log_in()
        self.assertIsNone(self.entries()[0]["thumbnail_url"])


class VideoListOrderTests(VideoListTestCase):
    """Order in which the endpoint hands the catalogue out."""

    def titles(self):
        """Return the titles the endpoint lists, in order."""
        return [entry["title"] for entry in self.entries()]

    def test_videos_come_newest_first(self):
        """The list starts with the video created last."""
        backdate(create_video(title="Oldest"), 1)
        backdate(create_video(title="Middle"), 2)
        backdate(create_video(title="Newest"), 3)
        self.log_in()
        self.assertEqual(self.titles(), ["Newest", "Middle", "Oldest"])

    def test_videos_created_together_come_newest_first(self):
        """Videos sharing a creation date keep the newest in front."""
        backdate(create_video(title="First"), 1)
        backdate(create_video(title="Second"), 1)
        self.log_in()
        self.assertEqual(self.titles(), ["Second", "First"])


class EmptyCatalogueTests(VideoListTestCase):
    """The answer while the catalogue holds no video at all."""

    def test_empty_catalogue_is_answered(self):
        """An empty catalogue still answers 200."""
        self.log_in()
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_empty_catalogue_is_an_empty_array(self):
        """An empty catalogue hands out an empty list."""
        self.log_in()
        self.assertEqual(self.entries(), [])


class VideoListAuthorizationTests(VideoListTestCase):
    """Requests the list endpoint turns away."""

    def setUp(self):
        """Store the video every rejected request must not see."""
        super().setUp()
        create_video()

    def assert_unauthorized(self, response):
        """Assert the answer to a request that does not authorize."""
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_request_without_a_cookie_is_rejected(self):
        """A request without the access cookie answers 401."""
        self.assert_unauthorized(self.client.get(self.url))

    def test_request_with_a_garbage_cookie_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN
        self.assert_unauthorized(self.client.get(self.url))

    def test_request_with_a_blacklisted_cookie_is_rejected(self):
        """A blacklisted refresh token in the access cookie fails."""
        refresh = RefreshToken.for_user(self.user)
        refresh.blacklist()
        self.client.cookies[ACCESS_COOKIE] = str(refresh)
        self.assert_unauthorized(self.client.get(self.url))

    def test_logged_out_user_cannot_read_the_list(self):
        """After a logout the list endpoint answers 401."""
        self.log_in()
        self.client.post(reverse("logout"), content_type="application/json")
        self.assert_unauthorized(self.client.get(self.url))
