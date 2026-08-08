"""Test of the authentication journey from end to end."""

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

EMAIL = "user@example.com"
PASSWORD = "securepassword"
REGISTRATION = {
    "email": EMAIL,
    "password": PASSWORD,
    "confirmed_password": PASSWORD,
}
CREDENTIALS = {"email": EMAIL, "password": PASSWORD}
ACCESS_COOKIE = settings.AUTH_ACCESS_COOKIE
REFRESH_COOKIE = settings.AUTH_REFRESH_COOKIE


class AuthFlowTests(TestCase):
    """The seven auth steps as one client with a cookie jar walks them."""

    def test_the_whole_journey(self):
        """Walk one address from registration to a second login."""
        uidb64, token = self.register()
        self.assert_login_rejected()
        self.activate(uidb64, token)
        self.log_in()
        spent = self.cookie(REFRESH_COOKIE)
        self.refresh()
        self.assert_dead(spent)
        live = self.cookie(REFRESH_COOKIE)
        self.log_out()
        self.assert_dead(live)
        self.log_in()

    def post(self, name, payload=None):
        """Post the payload to the named endpoint as JSON."""
        return self.client.post(
            reverse(name), payload, content_type="application/json"
        )

    def cookie(self, name):
        """Return the value of a cookie the client currently holds."""
        return self.client.cookies[name].value

    def register(self):
        """Register the address and return its activation link parts."""
        response = self.post("register", REGISTRATION)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        return (
            urlsafe_base64_encode(force_bytes(body["user"]["id"])),
            body["token"],
        )

    def assert_login_rejected(self):
        """Expect the account to be turned away before activation."""
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 401)

    def activate(self, uidb64, token):
        """Follow the activation link the registration handed out."""
        url = reverse("activate", kwargs={"uidb64": uidb64, "token": token})
        self.assertEqual(self.client.get(url).status_code, 200)

    def log_in(self):
        """Log in and expect both cookies to reach the client."""
        self.assertEqual(self.post("login", CREDENTIALS).status_code, 200)
        self.assertTrue(self.cookie(ACCESS_COOKIE))
        self.assertTrue(self.cookie(REFRESH_COOKIE))

    def refresh(self):
        """Renew the tokens and expect both cookies to change."""
        before = (self.cookie(ACCESS_COOKIE), self.cookie(REFRESH_COOKIE))
        self.assertEqual(self.post("token-refresh").status_code, 200)
        after = (self.cookie(ACCESS_COOKIE), self.cookie(REFRESH_COOKIE))
        self.assertNotEqual(after, before)

    def log_out(self):
        """Log out and expect both cookies to be cleared."""
        self.assertEqual(self.post("logout").status_code, 200)
        self.assertFalse(self.cookie(ACCESS_COOKIE))
        self.assertFalse(self.cookie(REFRESH_COOKIE))

    def assert_dead(self, token):
        """Expect a refresh with the given token to answer 401."""
        held = self.cookie(REFRESH_COOKIE)
        self.client.cookies[REFRESH_COOKIE] = token
        self.assertEqual(self.post("token-refresh").status_code, 401)
        self.client.cookies[REFRESH_COOKIE] = held
