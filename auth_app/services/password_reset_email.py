"""Composition and delivery of the password reset email."""

import logging
from urllib.parse import urlencode, urljoin

import django_rq
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from redis.exceptions import RedisError

CONFIRM_PATH = "/pages/auth/confirm_password.html"
SUBJECT = "Reset your password"
TEMPLATE = "auth_app/email/password_reset"
ENQUEUE_FAILURE_MESSAGE = "Password reset email could not be queued."

logger = logging.getLogger(__name__)


def build_reset_link(user):
    """Return the frontend URL that resets this user's password."""
    query = urlencode(
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user),
        }
    )
    base = urljoin(settings.FRONTEND_BASE_URL, CONFIRM_PATH)
    return f"{base}?{query}"


def send_password_reset_email(user):
    """Send this account's password reset email to its address."""
    context = {"user": user, "reset_link": build_reset_link(user)}
    send_mail(
        SUBJECT,
        render_to_string(f"{TEMPLATE}.txt", context),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=render_to_string(f"{TEMPLATE}.html", context),
    )


def queue_password_reset_email(user_id):
    """Queue this account's reset email or log the lost job."""
    from auth_app.tasks import deliver_password_reset_email

    try:
        django_rq.get_queue().enqueue(deliver_password_reset_email, user_id)
    except RedisError:
        logger.exception(ENQUEUE_FAILURE_MESSAGE)


def request_password_reset(email):
    """Queue a reset email if an account holds this address."""
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        return
    queue_password_reset_email(user.pk)
