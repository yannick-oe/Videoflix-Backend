"""Tests for what the state of an account gates on the API."""

import tempfile
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from video_app.models import Video
from video_app.services.conversion import PLAYLIST_NAME, video_directory

EMAIL = "user@example.com"
PASSWORD = "securepassword"
TITLE = "Movie Title"
DESCRIPTION = "Movie Description"
CATEGORY = "Drama"
SOURCE_NAME = "videos/clip.mp4"
RESOLUTION = "480p"
SEGMENT_NAME = "000.ts"
MANIFEST_BODY = b"#EXTM3U\n#EXT-X-ENDLIST\n"
SEGMENT_BODY = b"segment bytes"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
REFRESH_COOKIE = settings.AUTH_REFRESH_COOKIE
EXPIRED_LIFETIME = timedelta(seconds=-1)
GRANTED = [200, 200, 200]
REFUSED = [401, 401, 401]


class AccountStateTestCase(TestCase):
    """Account, video and rendition every state test needs."""

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
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.video = Video.objects.create(
            title=TITLE,
            description=DESCRIPTION,
            category=CATEGORY,
            video_file=SOURCE_NAME,
        )
        self.store_rendition()
        self.login()

    def store_rendition(self):
        """Write the playlist and one segment of the rendition."""
        directory = video_directory(self.video.pk) / RESOLUTION
        directory.mkdir(parents=True, exist_ok=True)
        (directory / PLAYLIST_NAME).write_bytes(MANIFEST_BODY)
        (directory / SEGMENT_NAME).write_bytes(SEGMENT_BODY)

    def login(self):
        """Log the account in so the client holds both cookies."""
        return self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )

    def manifest_url(self):
        """Return the manifest URL of the stored rendition."""
        return reverse(
            "video-manifest",
            kwargs={"movie_id": self.video.pk, "resolution": RESOLUTION},
        )

    def segment_url(self):
        """Return the segment URL of the stored rendition."""
        return reverse(
            "video-segment",
            kwargs={
                "movie_id": self.video.pk,
                "resolution": RESOLUTION,
                "segment": SEGMENT_NAME,
            },
        )

    def statuses(self):
        """Return the status of every authenticated read."""
        return [
            self.client.get(reverse("video-list")).status_code,
            self.client.get(self.manifest_url()).status_code,
            self.client.get(self.segment_url()).status_code,
        ]

    def refresh(self):
        """Call the refresh endpoint with the cookies still held."""
        return self.client.post(reverse("token-refresh"))

    def logout(self):
        """Call the logout endpoint with the cookies still held."""
        return self.client.post(reverse("logout"))


class ActiveAccountTests(AccountStateTestCase):
    """An account in good standing reaches every endpoint."""

    def test_every_read_succeeds(self):
        """The list, the manifest and the segment all answer 200."""
        self.assertEqual(self.statuses(), GRANTED)

    def test_the_refresh_succeeds(self):
        """The refresh endpoint answers the held cookie with 200."""
        self.assertEqual(self.refresh().status_code, 200)

    def test_the_refresh_hands_out_an_access_token(self):
        """The answered refresh carries a new access token."""
        self.assertIn("access", self.refresh().json())

    def test_the_logout_succeeds(self):
        """The logout endpoint answers the held cookie with 200."""
        self.assertEqual(self.logout().status_code, 200)


class DeactivatedAccountTests(AccountStateTestCase):
    """An account deactivated after its tokens were issued."""

    def setUp(self):
        """Log in and then take the account out of service."""
        super().setUp()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

    def test_every_read_is_refused(self):
        """The list, the manifest and the segment all answer 401."""
        self.assertEqual(self.statuses(), REFUSED)

    def test_the_refresh_is_refused(self):
        """The refresh of a deactivated account answers 401."""
        self.assertEqual(self.refresh().status_code, 401)

    def test_the_refresh_hands_out_no_access_token(self):
        """The refused refresh carries no new access token."""
        self.assertNotIn("access", self.refresh().json())

    def test_the_logout_still_succeeds(self):
        """A deactivated account can still give up its token."""
        self.assertEqual(self.logout().status_code, 200)


class DeletedAccountTests(AccountStateTestCase):
    """An account whose row is deleted while its tokens live."""

    def setUp(self):
        """Log in and then delete the account behind the token."""
        super().setUp()
        self.user.delete()

    def test_every_read_is_refused(self):
        """The list, the manifest and the segment all answer 401."""
        self.assertEqual(self.statuses(), REFUSED)

    def test_the_refresh_is_refused(self):
        """The refresh of a deleted account answers 401."""
        self.assertEqual(self.refresh().status_code, 401)

    def test_the_refresh_hands_out_no_access_token(self):
        """The refused refresh carries no new access token."""
        self.assertNotIn("access", self.refresh().json())

    def test_the_logout_still_succeeds(self):
        """A deleted account can still give up its token."""
        self.assertEqual(self.logout().status_code, 200)


class ExpiredAccessTokenTests(AccountStateTestCase):
    """An access token whose lifetime ran out before the request."""

    def setUp(self):
        """Log in and then hold an access token past its expiry."""
        super().setUp()
        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=EXPIRED_LIFETIME)
        self.client.cookies[ACCESS_COOKIE] = str(token)

    def test_every_read_is_refused(self):
        """The list, the manifest and the segment all answer 401."""
        self.assertEqual(self.statuses(), REFUSED)


class BlacklistedRefreshTokenTests(AccountStateTestCase):
    """A refresh token the account already logged out with."""

    def setUp(self):
        """Log in, log out and hold the blacklisted token again."""
        super().setUp()
        blacklisted = self.client.cookies[REFRESH_COOKIE].value
        self.logout()
        self.client.cookies[REFRESH_COOKIE] = blacklisted

    def test_the_refresh_is_refused(self):
        """The refresh with a blacklisted token answers 401."""
        self.assertEqual(self.refresh().status_code, 401)

    def test_the_refresh_hands_out_no_access_token(self):
        """The refused refresh carries no new access token."""
        self.assertNotIn("access", self.refresh().json())
