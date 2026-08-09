"""Tests for the cookie based JWT authentication class."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import path, reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from core.urls import urlpatterns as project_urlpatterns

EMAIL = "user@example.com"
OTHER_EMAIL = "second@example.com"
PASSWORD = "securepassword"
GARBAGE_TOKEN = "not-a-token"
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE


class ProbeView(APIView):
    """Report the account an authenticated request carries."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the username of the authenticated account."""
        return Response({"username": request.user.username})


urlpatterns = project_urlpatterns + [
    path("probe/", ProbeView.as_view(), name="probe"),
]


@override_settings(ROOT_URLCONF=__name__)
class CookieAuthenticationTests(TestCase):
    """Behaviour of a protected endpoint behind the cookie class."""

    def setUp(self):
        """Create an active account and address the probe view."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        self.url = reverse("probe")

    def login(self):
        """Log the account in so the client holds both cookies."""
        return self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )

    def probe(self):
        """Call the protected endpoint with the held cookies."""
        return self.client.get(self.url)

    def assert_unauthorized(self, response):
        """Assert the answer to a request that does not authorize."""
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.json())

    def test_cookie_from_a_login_authenticates(self):
        """The access cookie a login sets answers 200."""
        self.login()
        self.assertEqual(self.probe().status_code, 200)

    def test_authenticated_request_carries_the_account(self):
        """The view sees the account the access cookie names."""
        self.login()
        self.assertEqual(self.probe().json()["username"], EMAIL)

    def test_missing_cookie_is_rejected(self):
        """A request without the access cookie answers 401."""
        self.assert_unauthorized(self.probe())

    def test_malformed_cookie_is_rejected(self):
        """A cookie that is not a token answers 401."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN
        self.assert_unauthorized(self.probe())

    def test_empty_cookie_is_rejected(self):
        """A cookie without a value answers 401."""
        self.client.cookies[ACCESS_COOKIE] = ""
        self.assert_unauthorized(self.probe())

    def test_expired_cookie_is_rejected(self):
        """An access token past its lifetime answers 401."""
        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.client.cookies[ACCESS_COOKIE] = str(token)
        self.assert_unauthorized(self.probe())

    def test_blacklisted_refresh_token_is_rejected(self):
        """A blacklisted refresh token in the access cookie fails."""
        refresh = RefreshToken.for_user(self.user)
        refresh.blacklist()
        self.client.cookies[ACCESS_COOKIE] = str(refresh)
        self.assert_unauthorized(self.probe())

    def test_cookie_of_a_deactivated_account_is_rejected(self):
        """A token of an account that lost its flag answers 401."""
        self.login()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assert_unauthorized(self.probe())

    def test_cookie_of_a_deleted_account_is_rejected(self):
        """A token of an account that is gone answers 401."""
        self.login()
        self.user.delete()
        self.assert_unauthorized(self.probe())

    def test_logout_ends_the_authenticated_session(self):
        """After a logout the protected endpoint answers 401."""
        self.login()
        self.client.post(reverse("logout"), content_type="application/json")
        self.assert_unauthorized(self.probe())


class StaleCookieTests(TestCase):
    """Public endpoints answered while a stale cookie rides along."""

    def setUp(self):
        """Send a garbage access cookie with every request."""
        self.client.cookies[ACCESS_COOKIE] = GARBAGE_TOKEN

    def test_registration_is_not_blocked(self):
        """A garbage access cookie still allows a registration."""
        response = self.client.post(
            reverse("register"),
            {
                "email": OTHER_EMAIL,
                "password": PASSWORD,
                "confirmed_password": PASSWORD,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_login_is_not_blocked(self):
        """A garbage access cookie still allows a login."""
        User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        response = self.client.post(
            reverse("login"),
            {"email": EMAIL, "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

    def test_password_reset_is_not_blocked(self):
        """A garbage access cookie still allows a reset request."""
        response = self.client.post(
            reverse("password-reset"),
            {"email": EMAIL},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
