"""Background jobs of the authentication app."""

from django.contrib.auth.models import User

from auth_app.services.activation_email import send_activation_email
from auth_app.services.password_reset_email import send_password_reset_email


def deliver_activation_email(user_id):
    """Send the activation email of the account this id addresses."""
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    send_activation_email(user)


def deliver_password_reset_email(user_id):
    """Send the reset email of the account this id addresses."""
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    send_password_reset_email(user)
