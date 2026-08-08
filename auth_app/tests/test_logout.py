"""Tests for the logout endpoint."""

from datetime import timedelta

import jwt
from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

EMAIL = "user@example.com"
PASSWORD = "securepassword"
SUCCESS_MESSAGE = (
    "Logout successful! All tokens will be deleted. "
    "Refresh token is now invalid."
)
MISSING_MESSAGE = "Refresh token cookie was not sent."
GARBAGE_TOKEN = "not-a-token"
EXPIRED_LIFETIME = timedelta(days=-1)
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
REFRESH_COOKIE = settings.AUTH_REFRESH_COOKIE


class LogoutTests(TestCase):
    """Behaviour of POST /api/logout/ as seen by a client."""

    def setUp(self):
        """Log an active account in and keep the cookies it sets."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.url = reverse("logout")
        self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )

    def logout(self):
        """Call the endpoint with the cookies the client holds."""
        return self.client.post(self.url, content_type="application/json")

    def refresh(self):
        """Call the refresh endpoint with the cookies the client holds."""
        return self.client.post(
            reverse("token-refresh"), content_type="application/json"
        )

    def cookie(self, name):
        """Return the value of a cookie the client currently holds."""
        return self.client.cookies[name].value

    def token_id(self, token):
        """Return the unique identifier a token carries."""
        return jwt.decode(token, options={"verify_signature": False})["jti"]

    def expired_token(self):
        """Return a refresh token whose lifetime has run out."""
        token = RefreshToken.for_user(self.user)
        token.set_exp(lifetime=EXPIRED_LIFETIME)
        return str(token)

    def assert_cookies_cleared(self, response):
        """Assert the answer clears both authentication cookies."""
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            self.assertEqual(response.cookies[name].value, "")

    def assert_unauthorized(self, response):
        """Assert the answer to a token that cannot be used."""
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_valid_cookie_is_accepted(self):
        """A refresh cookie from a login answers 200."""
        self.assertEqual(self.logout().status_code, 200)

    def test_response_body_matches_the_contract(self):
        """The body carries the documented message and nothing else."""
        self.assertJSONEqual(
            self.logout().content.decode(), {"detail": SUCCESS_MESSAGE}
        )

    def test_response_message_matches_character_for_character(self):
        """The message reads exactly as the documentation prints it."""
        self.assertEqual(self.logout().json()["detail"], SUCCESS_MESSAGE)

    def test_both_cookies_are_deleted(self):
        """The answer sends both cookies back without a value."""
        self.assert_cookies_cleared(self.logout())

    def test_deleted_cookies_expire_at_once(self):
        """Both cleared cookies carry an expiry the browser acts on."""
        response = self.logout()
        for name in (ACCESS_COOKIE, REFRESH_COOKIE):
            self.assertEqual(response.cookies[name]["max-age"], 0)

    def test_client_holds_no_token_afterwards(self):
        """The client keeps no usable cookie after the logout."""
        self.logout()
        self.assertFalse(self.cookie(ACCESS_COOKIE))
        self.assertFalse(self.cookie(REFRESH_COOKIE))

    def test_refresh_token_is_blacklisted(self):
        """The token the cookie carried lands on the blacklist."""
        jti = self.token_id(self.cookie(REFRESH_COOKIE))
        self.logout()
        self.assertTrue(
            BlacklistedToken.objects.filter(token__jti=jti).exists()
        )

    def test_refresh_with_the_blacklisted_token_is_rejected(self):
        """A refresh with the logged out token answers 401."""
        spent = self.cookie(REFRESH_COOKIE)
        self.logout()
        self.client.cookies[REFRESH_COOKIE] = spent
        self.assert_unauthorized(self.refresh())

    def test_refresh_after_logout_is_rejected(self):
        """The client the logout cleared cannot refresh."""
        self.logout()
        response = self.refresh()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], MISSING_MESSAGE)

    def test_second_logout_is_rejected(self):
        """Replaying an already blacklisted token answers 401."""
        spent = self.cookie(REFRESH_COOKIE)
        self.logout()
        self.client.cookies[REFRESH_COOKIE] = spent
        self.assert_unauthorized(self.logout())

    def test_garbage_token_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[REFRESH_COOKIE] = GARBAGE_TOKEN
        self.assert_unauthorized(self.logout())

    def test_expired_token_is_rejected(self):
        """A refresh token past its lifetime answers 401."""
        self.client.cookies[REFRESH_COOKIE] = self.expired_token()
        self.assert_unauthorized(self.logout())

    def test_unusable_token_still_clears_both_cookies(self):
        """A rejected logout leaves the client without cookies."""
        self.client.cookies[REFRESH_COOKIE] = GARBAGE_TOKEN
        self.assert_cookies_cleared(self.logout())

    def test_unusable_token_blacklists_nothing(self):
        """A rejected logout adds no entry to the blacklist."""
        self.client.cookies[REFRESH_COOKIE] = GARBAGE_TOKEN
        self.logout()
        self.assertFalse(BlacklistedToken.objects.exists())

    def test_missing_cookie_is_rejected(self):
        """A request without the refresh cookie answers 400."""
        self.client.cookies.clear()
        response = self.logout()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], MISSING_MESSAGE)

    def test_missing_cookie_still_clears_both_cookies(self):
        """The rejected request still sends both deletions."""
        self.client.cookies.clear()
        self.assert_cookies_cleared(self.logout())

    def test_logout_without_the_access_cookie(self):
        """A client holding only the refresh cookie logs out."""
        del self.client.cookies[ACCESS_COOKIE]
        self.assertEqual(self.logout().status_code, 200)

    def test_logout_with_an_unusable_access_cookie(self):
        """An access token the server would reject does not matter."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN
        self.assertEqual(self.logout().status_code, 200)
