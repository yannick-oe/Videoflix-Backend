"""Tests for the activation email and the job that delivers it."""

import html
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from redis.exceptions import ConnectionError as RedisConnectionError

from auth_app.services.activation_email import (
    ACTIVATION_PATH,
    SUBJECT,
    ActivationEmailUnavailable,
    queue_activation_email,
)
from auth_app.services.email_retry import EMAIL_RETRY
from auth_app.tasks import deliver_activation_email

EMAIL = "user@example.com"
PASSWORD = "securepassword"
PAYLOAD = {
    "email": EMAIL,
    "password": PASSWORD,
    "confirmed_password": PASSWORD,
}
URL_PATTERN = r"https?://[^\s\"<>]+"


def extract_link(body):
    """Return the first absolute URL the body carries."""
    return re.search(URL_PATTERN, html.unescape(body)).group()


def activation_url(link):
    """Return the API route the frontend calls for this link."""
    query = parse_qs(urlparse(link).query)
    return reverse(
        "activate",
        kwargs={"uidb64": query["uid"][0], "token": query["token"][0]},
    )


class ActivationEmailEnqueueTests(TestCase):
    """Registration hands the activation email to the queue."""

    def post(self, payload):
        """Post the payload and return the mocked enqueue call."""
        with patch("django_rq.get_queue") as get_queue:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    reverse("register"),
                    payload,
                    content_type="application/json",
                )
        return get_queue.return_value.enqueue

    def register(self):
        """Register the sample account and return the enqueue call."""
        return self.post(PAYLOAD)

    def test_registration_enqueues_one_job(self):
        """A successful registration queues exactly one job."""
        self.assertEqual(self.register().call_count, 1)

    def test_queued_job_is_the_activation_email(self):
        """The queued job delivers the activation email."""
        self.register().assert_called_once_with(
            deliver_activation_email,
            User.objects.get().pk,
            retry=EMAIL_RETRY,
        )

    def test_queued_argument_is_the_account_id(self):
        """The queue receives the id, not the account object."""
        argument = self.register().call_args.args[1]
        self.assertIsInstance(argument, int)

    def test_registration_sends_nothing_itself(self):
        """The request itself delivers no message."""
        self.register()
        self.assertEqual(mail.outbox, [])

    def test_rejected_registration_queues_nothing(self):
        """A rejected payload queues no job."""
        enqueue = self.post(PAYLOAD | {"confirmed_password": "other"})
        enqueue.assert_not_called()


class ActivationEmailTaskTests(TestCase):
    """Behaviour of the job that delivers the activation email."""

    def setUp(self):
        """Create the inactive account the job addresses."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, is_active=False
        )

    def message(self):
        """Run the job and return the delivered message."""
        deliver_activation_email(self.user.pk)
        return mail.outbox[0]

    def bodies(self):
        """Return the plain text and the HTML body of the message."""
        message = self.message()
        return (message.body, message.alternatives[0].content)

    def links(self):
        """Return the activation link of both bodies."""
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
        """The subject is the one the service defines."""
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
        """Text and HTML body point at the same activation link."""
        text_link, html_link = self.links()
        self.assertEqual(text_link, html_link)

    def test_both_links_address_the_frontend_page(self):
        """Both links open the activation page of the frontend."""
        for link in self.links():
            self.assertTrue(link.startswith(settings.FRONTEND_BASE_URL))
            self.assertEqual(urlparse(link).path, ACTIVATION_PATH)

    def test_both_links_carry_the_id_of_the_account(self):
        """Both links carry the base64 id of the account."""
        expected = urlsafe_base64_encode(force_bytes(self.user.pk))
        for link in self.links():
            query = parse_qs(urlparse(link).query)
            self.assertEqual(query["uid"], [expected])

    def test_text_link_activates_the_account(self):
        """The link of the plain text body answers 200."""
        response = self.client.get(activation_url(self.links()[0]))
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_html_link_activates_the_account(self):
        """The link of the HTML body answers 200."""
        response = self.client.get(activation_url(self.links()[1]))
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_gone_account_sends_nothing(self):
        """An id whose account is gone delivers no message."""
        user_id = self.user.pk
        self.user.delete()
        deliver_activation_email(user_id)
        self.assertEqual(mail.outbox, [])


class UnreachableQueueTests(TestCase):
    """Behaviour of the service when the queue refuses the job."""

    def setUp(self):
        """Create the account whose email cannot reach the queue."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, is_active=False
        )

    def queue(self):
        """Queue the activation email against an unreachable queue."""
        with patch("django_rq.get_queue") as get_queue:
            enqueue = get_queue.return_value.enqueue
            enqueue.side_effect = RedisConnectionError()
            queue_activation_email(self.user.pk)

    def reject(self):
        """Queue against the unreachable queue and catch the refusal."""
        with self.assertRaises(ActivationEmailUnavailable) as caught:
            self.queue()
        return caught.exception

    def test_unreachable_queue_is_reported(self):
        """An unreachable queue raises the refusal of the service."""
        self.assertIsInstance(self.reject(), ActivationEmailUnavailable)

    def test_refusal_carries_the_service_unavailable_status(self):
        """The refusal answers 503."""
        self.assertEqual(self.reject().status_code, 503)

    def test_refusal_carries_a_detail(self):
        """The refusal names a reason the frontend can display."""
        self.assertTrue(str(self.reject().detail))

    def test_unreachable_queue_removes_the_account(self):
        """The account does not survive an unreachable queue."""
        self.reject()
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_unreachable_queue_sends_nothing(self):
        """An unreachable queue delivers no message."""
        self.reject()
        self.assertEqual(mail.outbox, [])

    def test_reachable_queue_keeps_the_account(self):
        """A queued job leaves the account in place."""
        with patch("django_rq.get_queue"):
            queue_activation_email(self.user.pk)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())


class FailedEnqueueRegistrationTests(TransactionTestCase):
    """Registration against a queue that refuses the activation job."""

    def register(self, refusal=None):
        """Register the sample account against the mocked queue."""
        with patch("django_rq.get_queue") as get_queue:
            get_queue.return_value.enqueue.side_effect = refusal
            return self.client.post(
                reverse("register"),
                PAYLOAD,
                content_type="application/json",
            )

    def rejected_register(self):
        """Register while the queue refuses the activation job."""
        return self.register(RedisConnectionError())

    def test_failed_enqueue_answers_service_unavailable(self):
        """A refused job turns the registration into a 503."""
        self.assertEqual(self.rejected_register().status_code, 503)

    def test_failed_enqueue_answers_with_a_json_body(self):
        """The 503 carries the JSON body the frontend reads."""
        response = self.rejected_register()
        self.assertIn("application/json", response["Content-Type"])
        self.assertTrue(response.json()["detail"])

    def test_failed_enqueue_leaves_no_account(self):
        """No account survives a registration the queue refused."""
        self.rejected_register()
        self.assertFalse(User.objects.filter(email=EMAIL).exists())

    def test_failed_enqueue_sends_nothing(self):
        """A refused registration delivers no message."""
        self.rejected_register()
        self.assertEqual(mail.outbox, [])

    def test_address_stays_free_after_a_failed_enqueue(self):
        """The address registers again once the queue accepts jobs."""
        self.rejected_register()
        self.assertEqual(self.register().status_code, 201)
