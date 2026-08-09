"""Test of the lost password journey from end to end."""

import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from auth_app.services.password_reset_email import SUBJECT as RESET_SUBJECT

EMAIL = "user@example.com"
PASSWORD = "securepassword"
NEW_PASSWORD = "brandnewpassword"
REGISTRATION = {
    "email": EMAIL,
    "password": PASSWORD,
    "confirmed_password": PASSWORD,
}
NEW_PAIR = {
    "new_password": NEW_PASSWORD,
    "confirm_password": NEW_PASSWORD,
}
URL_PATTERN = r"https?://[^\s\"<>]+"


def run_at_once(function, *args, **kwargs):
    """Run a queued job in place of the worker."""
    return function(*args, **kwargs)


class ResetFlowTests(TestCase):
    """One client walks a lost password from registration to login."""

    def setUp(self):
        """Let every queued job run at once instead of a worker."""
        patcher = patch("django_rq.get_queue")
        get_queue = patcher.start()
        self.addCleanup(patcher.stop)
        get_queue.return_value.enqueue.side_effect = run_at_once

    def test_the_whole_journey(self):
        """Register, reset through the email link, and log in again."""
        self.register()
        self.assert_login_rejected(PASSWORD)
        uid, token = self.request_reset()
        self.assertEqual(self.confirm(uid, token).status_code, 200)
        self.assert_login_accepted(NEW_PASSWORD)
        self.assert_login_rejected(PASSWORD)
        self.assertEqual(self.confirm(uid, token).status_code, 400)

    def post(self, name, payload, **parts):
        """Post the payload to the named endpoint as JSON."""
        return self.client.post(
            reverse(name, kwargs=parts),
            payload,
            content_type="application/json",
        )

    def register(self):
        """Register the address and let its emails go out."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("register", REGISTRATION)
        self.assertEqual(response.status_code, 201)

    def request_reset(self):
        """Ask for a reset and read the link out of the email."""
        response = self.post("password-reset", {"email": EMAIL})
        self.assertEqual(response.status_code, 200)
        return self.link_parts()

    def link_parts(self):
        """Return the uid and token the delivered link carries."""
        link = re.search(URL_PATTERN, self.reset_message().body).group()
        query = parse_qs(urlparse(link).query)
        return query["uid"][0], query["token"][0]

    def reset_message(self):
        """Return the one reset email the client was sent."""
        sent = [m for m in mail.outbox if m.subject == RESET_SUBJECT]
        self.assertEqual(len(sent), 1)
        return sent[0]

    def confirm(self, uid, token):
        """Post the new password against the link from the email."""
        return self.post("password-confirm", NEW_PAIR, uidb64=uid, token=token)

    def login_status(self, password):
        """Return the status of a login with the given password."""
        payload = {"email": EMAIL, "password": password}
        return self.post("login", payload).status_code

    def assert_login_accepted(self, password):
        """Expect the given password to log the account in."""
        self.assertEqual(self.login_status(password), 200)

    def assert_login_rejected(self, password):
        """Expect the given password to be turned away."""
        self.assertEqual(self.login_status(password), 401)
