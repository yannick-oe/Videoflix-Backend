"""Tests for the password reset request and its email job."""

import html
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from redis.exceptions import ConnectionError as RedisConnectionError

from auth_app.api.views import PASSWORD_RESET_MESSAGE
from auth_app.services.password_reset_email import (
    CONFIRM_PATH,
    ENQUEUE_FAILURE_MESSAGE,
    SUBJECT,
    queue_password_reset_email,
)
from auth_app.tasks import deliver_password_reset_email

EMAIL = "user@example.com"
UNKNOWN_EMAIL = "stranger@example.com"
MALFORMED_EMAIL = "not-an-address"
PASSWORD = "securepassword"
URL_PATTERN = r"https?://[^\s\"<>]+"
LOGGER = "auth_app.services.password_reset_email"


def extract_link(body):
    """Return the first absolute URL the body carries."""
    return re.search(URL_PATTERN, html.unescape(body)).group()


class PasswordResetResponseTests(TestCase):
    """Every request is answered with the same confirmation."""

    def setUp(self):
        """Create the account one of the requests addresses."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )

    def post(self, payload):
        """Post the payload against the reset endpoint."""
        with patch("django_rq.get_queue"):
            return self.client.post(
                reverse("password-reset"),
                payload,
                content_type="application/json",
            )

    def bodies(self):
        """Return the raw answer to each of the four requests."""
        payloads = [
            {"email": EMAIL},
            {"email": UNKNOWN_EMAIL},
            {"email": MALFORMED_EMAIL},
            {},
        ]
        return [self.post(payload).content for payload in payloads]

    def test_known_address_is_confirmed(self):
        """A registered address is answered with 200."""
        response = self.post({"email": EMAIL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": PASSWORD_RESET_MESSAGE})

    def test_unknown_address_is_confirmed(self):
        """An address without an account is answered with 200."""
        response = self.post({"email": UNKNOWN_EMAIL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": PASSWORD_RESET_MESSAGE})

    def test_malformed_address_is_confirmed(self):
        """An address that is no address is answered with 200."""
        response = self.post({"email": MALFORMED_EMAIL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": PASSWORD_RESET_MESSAGE})

    def test_missing_field_is_confirmed(self):
        """A request without the field is answered with 200."""
        response = self.post({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": PASSWORD_RESET_MESSAGE})

    def test_all_four_answers_are_byte_identical(self):
        """None of the four answers differs by a single byte."""
        self.assertEqual(len(set(self.bodies())), 1)

    def test_answer_carries_the_documented_text(self):
        """The confirmation is the text of the documentation."""
        self.assertEqual(
            PASSWORD_RESET_MESSAGE,
            "An email has been sent to reset your password.",
        )


class PasswordResetEnqueueTests(TestCase):
    """The request hands the reset email to the queue."""

    def setUp(self):
        """Create the account the requests address."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )

    def post(self, payload):
        """Post the payload and return the mocked enqueue call."""
        with patch("django_rq.get_queue") as get_queue:
            self.client.post(
                reverse("password-reset"),
                payload,
                content_type="application/json",
            )
        return get_queue.return_value.enqueue

    def test_known_address_enqueues_one_job(self):
        """A registered address queues exactly one job."""
        self.assertEqual(self.post({"email": EMAIL}).call_count, 1)

    def test_queued_job_is_the_reset_email(self):
        """The queued job delivers the password reset email."""
        self.post({"email": EMAIL}).assert_called_once_with(
            deliver_password_reset_email, self.user.pk
        )

    def test_queued_argument_is_the_account_id(self):
        """The queue receives the id, not the account object."""
        argument = self.post({"email": EMAIL}).call_args.args[1]
        self.assertIsInstance(argument, int)

    def test_uppercase_address_reaches_the_account(self):
        """An address in capitals addresses the same account."""
        self.post({"email": EMAIL.upper()}).assert_called_once_with(
            deliver_password_reset_email, self.user.pk
        )

    def test_unknown_address_enqueues_nothing(self):
        """An address without an account queues no job."""
        self.post({"email": UNKNOWN_EMAIL}).assert_not_called()

    def test_malformed_address_enqueues_nothing(self):
        """An address that is no address queues no job."""
        self.post({"email": MALFORMED_EMAIL}).assert_not_called()

    def test_missing_field_enqueues_nothing(self):
        """A request without the field queues no job."""
        self.post({}).assert_not_called()

    def test_request_sends_nothing_itself(self):
        """The request itself delivers no message."""
        self.post({"email": EMAIL})
        self.assertEqual(mail.outbox, [])

    def test_unknown_address_receives_no_mail(self):
        """An address without an account is never written to."""
        self.post({"email": UNKNOWN_EMAIL})
        self.assertEqual(mail.outbox, [])


class PasswordResetTaskTests(TestCase):
    """Behaviour of the job that delivers the reset email."""

    def setUp(self):
        """Create the account the job addresses."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )

    def message(self):
        """Run the job and return the delivered message."""
        deliver_password_reset_email(self.user.pk)
        return mail.outbox[0]

    def bodies(self):
        """Return the plain text and the HTML body of the message."""
        message = self.message()
        return (message.body, message.alternatives[0].content)

    def links(self):
        """Return the reset link of both bodies."""
        return tuple(extract_link(body) for body in self.bodies())

    def test_job_sends_one_message(self):
        """Running the job delivers exactly one message."""
        self.message()
        self.assertEqual(len(mail.outbox), 1)

    def test_message_addresses_the_account(self):
        """The message goes to the address of the account."""
        self.assertEqual(self.message().to, [EMAIL])

    def test_message_comes_from_the_configured_sender(self):
        """The message carries the configured sender address."""
        self.assertEqual(
            self.message().from_email, settings.DEFAULT_FROM_EMAIL
        )

    def test_message_carries_the_designed_subject(self):
        """The subject is the one of the delivered design."""
        self.assertEqual(self.message().subject, SUBJECT)

    def test_message_carries_a_plain_text_body(self):
        """The main body is plain text."""
        self.assertEqual(self.message().content_subtype, "plain")

    def test_message_carries_one_html_alternative(self):
        """The message offers exactly one HTML alternative."""
        alternatives = self.message().alternatives
        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0].mimetype, "text/html")

    def test_both_bodies_name_the_product(self):
        """Text and HTML body both speak for Videoflix."""
        for body in self.bodies():
            self.assertIn("Videoflix", body)

    def test_both_bodies_carry_the_same_link(self):
        """Text and HTML body point at the same reset link."""
        text_link, html_link = self.links()
        self.assertEqual(text_link, html_link)

    def test_both_links_address_the_frontend_page(self):
        """Both links open the confirmation page of the frontend."""
        for link in self.links():
            self.assertTrue(link.startswith(settings.FRONTEND_BASE_URL))
            self.assertEqual(urlparse(link).path, CONFIRM_PATH)

    def test_both_links_carry_the_id_of_the_account(self):
        """Both links carry the base64 id of the account."""
        expected = urlsafe_base64_encode(force_bytes(self.user.pk))
        for link in self.links():
            query = parse_qs(urlparse(link).query)
            self.assertEqual(query["uid"], [expected])

    def test_both_links_carry_a_token_of_the_account(self):
        """The token of both links validates for this account."""
        for link in self.links():
            token = parse_qs(urlparse(link).query)["token"][0]
            self.assertTrue(
                default_token_generator.check_token(self.user, token)
            )

    def test_token_belongs_to_no_other_account(self):
        """The token does not validate for a second account."""
        other = User.objects.create_user(
            username=UNKNOWN_EMAIL,
            email=UNKNOWN_EMAIL,
            password=PASSWORD,
        )
        token = parse_qs(urlparse(self.links()[0]).query)["token"][0]
        self.assertFalse(default_token_generator.check_token(other, token))

    def test_unactivated_account_receives_a_message(self):
        """An account that was never activated is written to."""
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.message().to, [EMAIL])

    def test_gone_account_sends_nothing(self):
        """An id whose account is gone delivers no message."""
        user_id = self.user.pk
        self.user.delete()
        deliver_password_reset_email(user_id)
        self.assertEqual(mail.outbox, [])


class UnreachableQueueTests(TestCase):
    """The answer stays the same when the queue refuses the job."""

    def setUp(self):
        """Create the account and let every enqueue fail."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )
        patcher = patch("django_rq.get_queue")
        get_queue = patcher.start()
        self.addCleanup(patcher.stop)
        get_queue.return_value.enqueue.side_effect = RedisConnectionError()

    def post(self, payload):
        """Post the payload against the unreachable queue."""
        return self.client.post(
            reverse("password-reset"),
            payload,
            content_type="application/json",
        )

    def test_known_address_is_still_confirmed(self):
        """A registered address is answered with 200."""
        with self.assertLogs(LOGGER, level="ERROR"):
            response = self.post({"email": EMAIL})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"detail": PASSWORD_RESET_MESSAGE})

    def test_known_and_unknown_answers_are_identical(self):
        """A lost job does not reveal that the account exists."""
        with self.assertLogs(LOGGER, level="ERROR"):
            known = self.post({"email": EMAIL})
        unknown = self.post({"email": UNKNOWN_EMAIL})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.content, unknown.content)

    def test_lost_job_sends_nothing(self):
        """A job the queue refused delivers no message."""
        with self.assertLogs(LOGGER, level="ERROR"):
            self.post({"email": EMAIL})
        self.assertEqual(mail.outbox, [])

    def test_lost_job_is_logged_as_an_error(self):
        """The refused job is recorded on the server."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            queue_password_reset_email(self.user.pk)
        self.assertIn(ENQUEUE_FAILURE_MESSAGE, logs.output[0])

    def test_log_carries_the_traceback(self):
        """The record keeps the exception that caused the loss."""
        with self.assertLogs(LOGGER, level="ERROR") as logs:
            queue_password_reset_email(self.user.pk)
        self.assertIn("ConnectionError", logs.output[0])
