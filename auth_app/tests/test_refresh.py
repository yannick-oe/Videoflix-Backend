"""Tests for the token refresh endpoint."""

import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

EMAIL = "user@example.com"
PASSWORD = "securepassword"
SUCCESS_MESSAGE = "Token refreshed"
MISSING_MESSAGE = "Refresh token cookie was not sent."
GARBAGE_TOKEN = "not-a-token"
OTHER_SIGNING_KEY = "a-different-signing-key-of-sufficient-length"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
REFRESH_COOKIE = settings.AUTH_REFRESH_COOKIE


class RefreshTests(TestCase):
    """Behaviour of POST /api/token/refresh/ as seen by a client."""

    def setUp(self):
        """Log an active account in and keep the cookies it sets."""
        User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.url = reverse("token-refresh")
        self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )

    def refresh(self):
        """Call the endpoint with the cookies the client holds."""
        return self.client.post(self.url, content_type="application/json")

    def cookie(self, name):
        """Return the value of a cookie the client currently holds."""
        return self.client.cookies[name].value

    def test_valid_cookie_is_accepted(self):
        """A refresh cookie from a login answers 200."""
        self.assertEqual(self.refresh().status_code, 200)

    def test_response_body_matches_the_contract(self):
        """The body carries the message and the new access token."""
        response = self.refresh()
        self.assertJSONEqual(
            response.content.decode(),
            {
                "detail": SUCCESS_MESSAGE,
                "access": response.cookies[ACCESS_COOKIE].value,
            },
        )

    def test_response_body_keeps_the_documented_key_order(self):
        """The raw JSON lists detail before access."""
        body = self.refresh().content.decode()
        self.assertLess(body.index('"detail"'), body.index('"access"'))

    def test_access_cookie_is_replaced(self):
        """The refresh hands out a new access cookie."""
        before = self.cookie(ACCESS_COOKIE)
        self.refresh()
        self.assertNotEqual(self.cookie(ACCESS_COOKIE), before)

    def test_refresh_cookie_is_replaced(self):
        """The rotated refresh token reaches the client."""
        before = self.cookie(REFRESH_COOKIE)
        self.refresh()
        self.assertNotEqual(self.cookie(REFRESH_COOKIE), before)

    def test_new_refresh_cookie_is_accepted(self):
        """The cookie the rotation set works for the next refresh."""
        self.refresh()
        self.assertEqual(self.refresh().status_code, 200)

    def test_rotated_refresh_token_is_rejected(self):
        """The refresh token the rotation replaced answers 401."""
        spent = self.cookie(REFRESH_COOKIE)
        self.refresh()
        self.client.cookies[REFRESH_COOKIE] = spent
        self.assert_unauthorized(self.refresh())

    def test_garbage_token_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[REFRESH_COOKIE] = GARBAGE_TOKEN
        self.assert_unauthorized(self.refresh())

    def test_token_signed_with_another_key_is_rejected(self):
        """A well formed token from a foreign signer answers 401."""
        self.client.cookies[REFRESH_COOKIE] = self.forged_token()
        self.assert_unauthorized(self.refresh())

    def forged_token(self):
        """Return the held refresh token signed with another key."""
        payload = jwt.decode(
            self.cookie(REFRESH_COOKIE), options={"verify_signature": False}
        )
        return jwt.encode(payload, OTHER_SIGNING_KEY, algorithm="HS256")

    def assert_unauthorized(self, response):
        """Assert the answer to a token that does not authorize."""
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_missing_cookie_is_rejected(self):
        """A request without the refresh cookie answers 400."""
        self.client.cookies.clear()
        response = self.refresh()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], MISSING_MESSAGE)

    def test_rejected_refresh_sets_no_cookies(self):
        """A failed refresh leaves the held cookies untouched."""
        self.client.cookies[REFRESH_COOKIE] = GARBAGE_TOKEN
        self.assertEqual(self.refresh().cookies, {})
