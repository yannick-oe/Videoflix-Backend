"""Composition and delivery of the account activation email."""

from urllib.parse import urlencode, urljoin

import django_rq
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from redis.exceptions import RedisError
from rest_framework import status
from rest_framework.exceptions import APIException

from auth_app.tokens import activation_token_generator

ACTIVATION_PATH = "/pages/auth/activate.html"
SUBJECT = "Confirm your email"
TEMPLATE = "auth_app/email/activation"


class ActivationEmailUnavailable(APIException):
    """Answer to a registration the queue could not accept."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "Registration is temporarily unavailable. Please try again."
    )


def build_activation_link(user):
    """Return the frontend URL that activates this user's account."""
    query = urlencode(
        {
            "uid": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": activation_token_generator.make_token(user),
        }
    )
    base = urljoin(settings.FRONTEND_BASE_URL, ACTIVATION_PATH)
    return f"{base}?{query}"


def render_bodies(context):
    """Return the plain text and the HTML body of the email."""
    return (
        render_to_string(f"{TEMPLATE}.txt", context),
        render_to_string(f"{TEMPLATE}.html", context),
    )


def send_activation_email(user):
    """Send this account's activation email to its address."""
    context = {"user": user, "activation_link": build_activation_link(user)}
    text, html = render_bodies(context)
    message = EmailMultiAlternatives(
        SUBJECT, text, settings.DEFAULT_FROM_EMAIL, [user.email]
    )
    message.attach_alternative(html, "text/html")
    message.send()


def queue_activation_email(user_id):
    """Queue this account's activation email or drop the account."""
    from auth_app.tasks import deliver_activation_email

    try:
        django_rq.get_queue().enqueue(deliver_activation_email, user_id)
    except RedisError as error:
        User.objects.filter(pk=user_id).delete()
        raise ActivationEmailUnavailable() from error
