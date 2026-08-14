"""Tests for the retry policy the email jobs are queued with."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django_rq.workers import get_worker_class
from rq import Worker

from auth_app.services.activation_email import queue_activation_email
from auth_app.services.email_retry import (
    EMAIL_ATTEMPTS,
    EMAIL_INTERVALS,
    EMAIL_RETRY,
)
from auth_app.services.password_reset_email import queue_password_reset_email
from core.workers import SchedulingWorker

EMAIL = "user@example.com"
PASSWORD = "test-password-1234"
RATE_LIMIT_WINDOW = 1


class EmailRetryPolicyTests(TestCase):
    """The shape of the policy every email job carries."""

    def test_the_policy_grants_more_than_one_attempt(self):
        """A failed send is tried again instead of being dropped."""
        self.assertGreater(EMAIL_RETRY.max, 0)

    def test_every_attempt_has_its_own_interval(self):
        """No attempt falls back to the interval of another one."""
        self.assertEqual(len(EMAIL_RETRY.intervals), EMAIL_ATTEMPTS)

    def test_no_attempt_follows_immediately(self):
        """An attempt never repeats inside the window it was refused in."""
        self.assertGreater(min(EMAIL_INTERVALS), RATE_LIMIT_WINDOW)

    def test_the_intervals_grow(self):
        """Each further attempt waits longer than the one before."""
        self.assertEqual(EMAIL_INTERVALS, sorted(EMAIL_INTERVALS))


class RetriedJobTests(TestCase):
    """The jobs the policy is attached to when they are queued."""

    def setUp(self):
        """Store the account both email jobs are queued for."""
        self.user = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD
        )

    def enqueue_during(self, action):
        """Return the enqueue mock this action wrote its job to."""
        with patch("django_rq.get_queue") as get_queue:
            action()
        return get_queue.return_value.enqueue

    def test_the_activation_email_is_queued_with_the_policy(self):
        """A lost activation email is delivered on a later attempt."""
        enqueue = self.enqueue_during(
            lambda: queue_activation_email(self.user.pk)
        )
        self.assertIs(enqueue.call_args.kwargs["retry"], EMAIL_RETRY)

    def test_the_reset_email_is_queued_with_the_policy(self):
        """A lost reset email is delivered on a later attempt."""
        enqueue = self.enqueue_during(
            lambda: queue_password_reset_email(self.user.pk)
        )
        self.assertIs(enqueue.call_args.kwargs["retry"], EMAIL_RETRY)


class SchedulingWorkerTests(TestCase):
    """The worker that makes a delayed retry reach the queue again."""

    def test_the_worker_switches_the_scheduler_on(self):
        """The worker runs the scheduler a delayed retry waits for."""
        worker = SchedulingWorker.__new__(SchedulingWorker)
        with patch.object(Worker, "work") as work:
            worker.work()
        self.assertIs(work.call_args.kwargs["with_scheduler"], True)

    def test_the_worker_overrides_a_switched_off_scheduler(self):
        """The command starting without the flag still gets one."""
        worker = SchedulingWorker.__new__(SchedulingWorker)
        with patch.object(Worker, "work") as work:
            worker.work(with_scheduler=False)
        self.assertIs(work.call_args.kwargs["with_scheduler"], True)

    def test_the_worker_passes_its_other_arguments_on(self):
        """The worker changes nothing but the scheduler flag."""
        worker = SchedulingWorker.__new__(SchedulingWorker)
        with patch.object(Worker, "work") as work:
            worker.work(burst=True)
        self.assertIs(work.call_args.kwargs["burst"], True)

    def test_the_worker_returns_what_it_was_given(self):
        """The worker hands the result of the run back unchanged."""
        worker = SchedulingWorker.__new__(SchedulingWorker)
        with patch.object(Worker, "work", return_value=True) as work:
            self.assertIs(worker.work(), work.return_value)

    def test_the_queue_is_served_by_this_worker(self):
        """The setting naming the worker reaches the queue."""
        self.assertIs(get_worker_class(), SchedulingWorker)
