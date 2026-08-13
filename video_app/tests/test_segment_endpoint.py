"""Tests for the HLS segment endpoint."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.http import Http404
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from video_app.api.views import rendition_file
from video_app.models import Video
from video_app.services.conversion import video_directory

EMAIL = "user@example.com"
PASSWORD = "securepassword"
GARBAGE_TOKEN = "not-a-token"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
RESOLUTION = "480p"
UNKNOWN_RESOLUTION = "240p"
SEGMENT_NAME = "000.ts"
LATER_SEGMENT_NAME = "1234.ts"
MISSING_SEGMENT_NAME = "099.ts"
SEGMENT_TYPE = "video/MP2T"
SEGMENT_BODY = bytes(range(256)) * 4
MISSING_ID = 9999
CLIMBING_NAME = "../../../etc/passwd"
TRAVERSAL_NAMES = [
    CLIMBING_NAME,
    "../../videos/clip.mp4",
    "..%2f..%2fvideos%2fclip.mp4",
    "....//....//videos/clip.mp4",
    "000.ts/../../../../etc/passwd",
]


def store_file(path, content):
    """Store this content at the path and create its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class SegmentTestCase(TestCase):
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
        """Store an account and a video holding one segment."""
        User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.video = Video.objects.create(
            title="Movie Title",
            description="Movie Description",
            category="Drama",
            video_file="videos/clip.mp4",
        )
        self.segment = self.segment_path(SEGMENT_NAME)
        store_file(self.segment, SEGMENT_BODY)

    def segment_path(self, name):
        """Return the path one segment of the rendition is stored at."""
        return video_directory(self.video.pk) / RESOLUTION / name

    def url(self, movie_id=None, segment=SEGMENT_NAME, name="video-segment"):
        """Return the segment URL the documentation describes."""
        return reverse(
            name,
            kwargs={
                "movie_id": self.video.pk if movie_id is None else movie_id,
                "resolution": RESOLUTION,
                "segment": segment,
            },
        )

    def bare_url(self, movie_id=None, segment=SEGMENT_NAME):
        """Return the segment URL a player builds from the playlist."""
        return self.url(movie_id, segment, name="video-segment-bare")

    def log_in(self):
        """Log the account in so the client holds both cookies."""
        self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )


class SegmentResponseTests(SegmentTestCase):
    """Answer an authenticated request for a segment receives."""

    def setUp(self):
        """Log the account in before addressing the endpoint."""
        super().setUp()
        self.log_in()

    def test_stored_segment_is_served(self):
        """A request for a stored segment answers 200."""
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_segment_carries_the_documented_content_type(self):
        """The answer names the transport stream type of the doc."""
        response = self.client.get(self.url())
        self.assertEqual(response["Content-Type"], SEGMENT_TYPE)

    def test_segment_body_matches_the_file_on_disk(self):
        """The body hands out the bytes the conversion wrote."""
        response = self.client.get(self.url())
        self.assertEqual(
            b"".join(response.streaming_content), self.segment.read_bytes()
        )

    def test_answer_streams_instead_of_buffering(self):
        """The answer hands the file out as a stream."""
        self.assertTrue(self.client.get(self.url()).streaming)

    def test_segment_beyond_three_digits_is_served(self):
        """A film long enough to number past 999 stays reachable."""
        store_file(self.segment_path(LATER_SEGMENT_NAME), SEGMENT_BODY)
        url = self.url(segment=LATER_SEGMENT_NAME)
        self.assertEqual(self.client.get(url).status_code, 200)


class SegmentTrailingSlashTests(SegmentTestCase):
    """Both spellings of the segment route a player may request."""

    def setUp(self):
        """Log the account in before addressing the endpoint."""
        super().setUp()
        self.log_in()

    def test_documented_url_ends_in_a_slash(self):
        """The route of the documentation carries a trailing slash."""
        self.assertTrue(self.url().endswith(f"/{SEGMENT_NAME}/"))

    def test_url_a_player_builds_carries_no_slash(self):
        """The route resolved from the playlist carries no slash."""
        self.assertTrue(self.bare_url().endswith(f"/{SEGMENT_NAME}"))

    def test_url_without_a_slash_is_answered_directly(self):
        """The URL a player builds answers 200 rather than 301."""
        self.assertEqual(self.client.get(self.bare_url()).status_code, 200)

    def test_url_without_a_slash_is_not_redirected(self):
        """The answer to a slashless request names no new location."""
        self.assertNotIn("Location", self.client.get(self.bare_url()))

    def test_both_spellings_hand_out_the_same_bytes(self):
        """Either spelling of the route serves the stored segment."""
        slashed = self.client.get(self.url())
        bare = self.client.get(self.bare_url())
        self.assertEqual(
            b"".join(bare.streaming_content),
            b"".join(slashed.streaming_content),
        )


class SegmentNotFoundTests(SegmentTestCase):
    """Requests the segment endpoint answers with 404."""

    def setUp(self):
        """Log the account in before addressing the endpoint."""
        super().setUp()
        self.log_in()

    def test_unknown_video_answers_404(self):
        """A segment of a video that does not exist answers 404."""
        response = self.client.get(self.url(movie_id=MISSING_ID))
        self.assertEqual(response.status_code, 404)

    def test_unknown_resolution_answers_404(self):
        """A resolution the catalogue never offers answers 404."""
        url = self.url().replace(RESOLUTION, UNKNOWN_RESOLUTION)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_absent_segment_answers_404(self):
        """A segment the conversion never wrote answers 404."""
        url = self.url(segment=MISSING_SEGMENT_NAME)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_failed_conversion_answers_404(self):
        """A video whose conversion wrote nothing answers 404."""
        shutil.rmtree(video_directory(self.video.pk))
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_absent_segment_without_a_slash_answers_404(self):
        """The slashless route refuses an absent segment as well."""
        url = self.bare_url(segment=MISSING_SEGMENT_NAME)
        self.assertEqual(self.client.get(url).status_code, 404)


class SegmentTraversalTests(SegmentTestCase):
    """Segment names that try to leave the rendition directory."""

    def setUp(self):
        """Store a file outside the rendition and log the user in."""
        super().setUp()
        self.outside = Path(settings.MEDIA_ROOT) / "videos" / "clip.mp4"
        store_file(self.outside, SEGMENT_BODY)
        self.log_in()

    def traversal_url(self, name):
        """Return a segment URL whose name tries to climb out."""
        return self.bare_url().replace(SEGMENT_NAME, name)

    def test_traversal_attempts_are_refused(self):
        """No climbing segment name reaches a file below the root."""
        for name in TRAVERSAL_NAMES:
            with self.subTest(name=name):
                response = self.client.get(self.traversal_url(name))
                self.assertEqual(response.status_code, 404)

    def test_traversal_hands_out_no_file_content(self):
        """A refused request never carries the file it aimed at."""
        response = self.client.get(self.traversal_url(CLIMBING_NAME))
        self.assertNotIn(SEGMENT_BODY, response.content)

    def test_traversal_opens_no_file_at_all(self):
        """A climbing name is refused before any file is opened."""
        with patch.object(Path, "open") as opened:
            response = self.client.get(self.traversal_url(CLIMBING_NAME))
        self.assertEqual(response.status_code, 404)
        opened.assert_not_called()


class SegmentAuthorizationTests(SegmentTestCase):
    """Requests the segment endpoint turns away."""

    def test_request_without_a_cookie_is_rejected(self):
        """A request without the access cookie answers 401."""
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_slashless_request_without_a_cookie_is_rejected(self):
        """The slashless route refuses an anonymous request too."""
        self.assertEqual(self.client.get(self.bare_url()).status_code, 401)

    def test_rejected_request_carries_a_json_body(self):
        """The refusal names its reason in a JSON body."""
        self.assertIn("detail", self.client.get(self.url()).json())

    def test_request_with_a_garbage_cookie_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def test_logged_out_user_cannot_read_a_segment(self):
        """After a logout the segment endpoint answers 401."""
        self.log_in()
        self.client.post(reverse("logout"), content_type="application/json")
        self.assertEqual(self.client.get(self.url()).status_code, 401)


class RenditionPathTests(SimpleTestCase):
    """The guard that keeps a file name inside its rendition."""

    def test_plain_name_stays_inside_the_rendition(self):
        """A plain segment name resolves inside the directory."""
        path = rendition_file(1, RESOLUTION, SEGMENT_NAME)
        self.assertEqual(path.parent, video_directory(1) / RESOLUTION)

    def test_climbing_name_is_refused(self):
        """A name climbing out of the rendition raises Http404."""
        with self.assertRaises(Http404):
            rendition_file(1, RESOLUTION, CLIMBING_NAME)
