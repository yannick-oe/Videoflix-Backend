"""Tests for the activation endpoint."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from auth_app.tokens import activation_token_generator

EMAIL = "user@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "securepassword"
SUCCESS_BODY = {"message": "Account successfully activated."}
FAILURE_BODY = {"message": "Activation link is invalid or expired."}


def create_inactive_user(email):
    """Create and return an inactive account for the address."""
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD, is_active=False
    )


class ActivationTests(TestCase):
    """Behaviour of GET /api/activate/ as seen by a client."""

    def setUp(self):
        """Create the account the activation links point at."""
        self.user = create_inactive_user(EMAIL)

    def link(self, user=None):
        """Return the uid and token of a valid link for the account."""
        target = user or self.user
        return (
            urlsafe_base64_encode(force_bytes(target.pk)),
            activation_token_generator.make_token(target),
        )

    def activate(self, uidb64, token):
        """Call the endpoint with the given link parts."""
        url = reverse("activate", kwargs={"uidb64": uidb64, "token": token})
        return self.client.get(url)

    def assert_rejected(self, response):
        """Assert the shared rejection status and body."""
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content.decode(), FAILURE_BODY)

    def test_valid_link_is_accepted(self):
        """A valid link answers 200."""
        self.assertEqual(self.activate(*self.link()).status_code, 200)

    def test_valid_link_returns_the_documented_body(self):
        """The success body carries the documented message."""
        response = self.activate(*self.link())
        self.assertJSONEqual(response.content.decode(), SUCCESS_BODY)

    def test_valid_link_activates_the_account(self):
        """A valid link flips the account to active."""
        self.activate(*self.link())
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_malformed_uid_is_rejected(self):
        """A uid that is not base64 answers 400."""
        self.assert_rejected(self.activate("!!!", self.link()[1]))

    def test_non_numeric_uid_is_rejected(self):
        """A uid decoding to a non-numeric id answers 400."""
        uidb64 = urlsafe_base64_encode(force_bytes("abc"))
        self.assert_rejected(self.activate(uidb64, self.link()[1]))

    def test_uid_of_unknown_account_is_rejected(self):
        """A uid decoding to no account answers 400."""
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk + 1))
        self.assert_rejected(self.activate(uidb64, self.link()[1]))

    def test_token_of_another_account_is_rejected(self):
        """A token issued for a different account answers 400."""
        other = create_inactive_user(OTHER_EMAIL)
        self.assert_rejected(
            self.activate(self.link()[0], self.link(other)[1])
        )

    def test_tampered_token_is_rejected(self):
        """A modified token answers 400."""
        uidb64, token = self.link()
        self.assert_rejected(self.activate(uidb64, token + "x"))

    def test_rejected_link_leaves_the_account_inactive(self):
        """A rejected link does not activate the account."""
        self.activate(*self.link(create_inactive_user(OTHER_EMAIL)))
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_second_activation_is_rejected(self):
        """Replaying a spent link answers 400."""
        uidb64, token = self.link()
        self.activate(uidb64, token)
        self.assert_rejected(self.activate(uidb64, token))

    def test_second_activation_keeps_the_account_active(self):
        """A rejected replay leaves the account active."""
        uidb64, token = self.link()
        self.activate(uidb64, token)
        self.activate(uidb64, token)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
