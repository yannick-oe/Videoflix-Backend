"""Retry policy of the jobs that deliver an email."""

from rq import Retry

EMAIL_ATTEMPTS = 3
EMAIL_INTERVALS = [30, 120, 600]

EMAIL_RETRY = Retry(max=EMAIL_ATTEMPTS, interval=EMAIL_INTERVALS)
