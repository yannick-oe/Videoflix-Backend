"""Tests for the login endpoint."""

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.settings import api_settings

EMAIL = "user@example.com"
INACTIVE_EMAIL = "inactive@example.com"
UNKNOWN_EMAIL = "nobody@example.com"
PASSWORD = "securepassword"
SUCCESS_MESSAGE = "Login successful"
FAILURE_MESSAGE = "No active account found with the given credentials"
COOKIE_LIFETIMES = {
    settings.AUTH_ACCESS_COOKIE: api_settings.ACCESS_TOKEN_LIFETIME,
    settings.AUTH_REFRESH_COOKIE: api_settings.REFRESH_TOKEN_LIFETIME,
}


def create_user(email, is_active=True):
    """Create and return an account for the address."""
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=is_active
    )


class LoginTests(TestCase):
    """Behaviour of POST /api/login/ as seen by a client."""

    def setUp(self):
        """Create an active and an inactive account."""
        self.url = reverse("login")
        self.user = create_user(EMAIL)
        create_user(INACTIVE_EMAIL, is_active=False)

    def login(self, **changes):
        """Post the sample credentials with the given fields changed."""
        payload = {"email": EMAIL, "password": PASSWORD} | changes
        return self.client.post(
            self.url, payload, content_type="application/json"
        )

    def test_valid_credentials_are_accepted(self):
        """A correct password on an active account answers 200."""
        self.assertEqual(self.login().status_code, 200)

    def test_response_body_matches_the_contract(self):
        """The body carries the message and the account."""
        self.assertJSONEqual(
            self.login().content.decode(),
            {
                "detail": SUCCESS_MESSAGE,
                "user": {"id": self.user.pk, "username": EMAIL},
            },
        )

    def test_response_body_keeps_the_documented_key_order(self):
        """The raw JSON lists detail before user and id before username."""
        body = self.login().content.decode()
        self.assertLess(body.index('"detail"'), body.index('"user"'))
        self.assertLess(body.index('"id"'), body.index('"username"'))

    def test_response_body_carries_no_token(self):
        """The body exposes neither of the two tokens."""
        response = self.login()
        body = response.content.decode()
        for name in COOKIE_LIFETIMES:
            self.assertNotIn(response.cookies[name].value, body)

    def test_both_cookies_are_set(self):
        """Both configured cookies arrive carrying a value."""
        response = self.login()
        for name in COOKIE_LIFETIMES:
            self.assertTrue(response.cookies[name].value)

    def test_cookies_are_httponly(self):
        """Neither cookie is readable from JavaScript."""
        response = self.login()
        for name in COOKIE_LIFETIMES:
            self.assertTrue(response.cookies[name]["httponly"])

    def test_cookies_match_the_configured_flags(self):
        """Both cookies carry the flags the settings declare."""
        response = self.login()
        for name in COOKIE_LIFETIMES:
            cookie = response.cookies[name]
            self.assertEqual(
                bool(cookie["httponly"]), settings.AUTH_COOKIE_HTTPONLY
            )
            self.assertEqual(cookie["samesite"], settings.AUTH_COOKIE_SAMESITE)
            self.assertEqual(
                bool(cookie["secure"]), settings.AUTH_COOKIE_SECURE
            )

    def test_cookies_match_the_configured_lifetimes(self):
        """Each cookie expires with the token it carries."""
        response = self.login()
        for name, lifetime in COOKIE_LIFETIMES.items():
            self.assertEqual(
                response.cookies[name]["max-age"],
                int(lifetime.total_seconds()),
            )

    def test_the_two_cookies_differ(self):
        """Access and refresh cookie carry different tokens."""
        response = self.login()
        values = {response.cookies[name].value for name in COOKIE_LIFETIMES}
        self.assertEqual(len(values), 2)

    def test_uppercase_address_logs_in(self):
        """The address is matched regardless of its case."""
        self.assertEqual(self.login(email="User@EXAMPLE.com").status_code, 200)

    def test_wrong_password_is_rejected(self):
        """A wrong password answers 401 with the general message."""
        self.assert_rejected(self.login(password="wrongpassword"))

    def test_unknown_address_is_rejected(self):
        """An unregistered address answers 401 with the same message."""
        self.assert_rejected(self.login(email=UNKNOWN_EMAIL))

    def test_inactive_account_is_rejected(self):
        """A correct password on an inactive account answers 401."""
        self.assert_rejected(self.login(email=INACTIVE_EMAIL))

    def assert_rejected(self, response):
        """Assert the shared rejection status and message."""
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], FAILURE_MESSAGE)

    def test_all_rejections_are_indistinguishable(self):
        """The three failures look identical to a client."""
        responses = [
            self.login(password="wrongpassword"),
            self.login(email=UNKNOWN_EMAIL),
            self.login(email=INACTIVE_EMAIL),
        ]
        self.assertEqual({r.status_code for r in responses}, {401})
        self.assertEqual(len({r.content for r in responses}), 1)

    def test_rejected_login_sets_no_cookies(self):
        """A failed login leaves the client without cookies."""
        self.assertEqual(self.login(password="wrongpassword").cookies, {})

    def test_missing_password_is_rejected(self):
        """A payload without a password answers 400 with a body."""
        response = self.client.post(
            self.url, {"email": EMAIL}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())
