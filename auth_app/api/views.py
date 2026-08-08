"""Views of the authentication API."""

import django_rq
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from auth_app.api.serializers import LoginSerializer, RegistrationSerializer
from auth_app.api.utils import delete_auth_cookies, set_auth_cookies
from auth_app.tasks import deliver_activation_email
from auth_app.tokens import activation_token_generator

ACTIVATION_SUCCESS_MESSAGE = "Account successfully activated."
ACTIVATION_FAILURE_MESSAGE = "Activation link is invalid or expired."
LOGIN_SUCCESS_MESSAGE = "Login successful"
REFRESH_SUCCESS_MESSAGE = "Token refreshed"
REFRESH_MISSING_MESSAGE = "Refresh token cookie was not sent."
LOGOUT_SUCCESS_MESSAGE = (
    "Logout successful! All tokens will be deleted. "
    "Refresh token is now invalid."
)


class RegistrationView(generics.CreateAPIView):
    """Create an inactive account and return its activation token."""

    serializer_class = RegistrationSerializer
    permission_classes = [AllowAny]

    def perform_create(self, serializer):
        """Create the account and queue its activation email."""
        super().perform_create(serializer)
        user_id = serializer.instance.pk
        transaction.on_commit(
            lambda: django_rq.get_queue().enqueue(
                deliver_activation_email, user_id
            )
        )


class ActivationView(APIView):
    """Activate the account a uid and token pair addresses."""

    permission_classes = [AllowAny]

    def get(self, request, uidb64, token):
        """Activate the addressed account and report the outcome."""
        user = self.get_user(uidb64)
        if user is None:
            return self.rejection()
        if not activation_token_generator.check_token(user, token):
            return self.rejection()
        user.is_active = True
        user.save(update_fields=["is_active"])
        return Response({"message": ACTIVATION_SUCCESS_MESSAGE})

    def get_user(self, uidb64):
        """Return the account the uid addresses or None."""
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            return User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None

    def rejection(self):
        """Return the shared answer to every failed activation."""
        return Response(
            {"message": ACTIVATION_FAILURE_MESSAGE},
            status=status.HTTP_400_BAD_REQUEST,
        )


class LoginView(TokenObtainPairView):
    """Log an account in and store its tokens in cookies."""

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """Return the account and set both authentication cookies."""
        response = super().post(request, *args, **kwargs)
        data = response.data
        response.data = {
            "detail": LOGIN_SUCCESS_MESSAGE,
            "user": data["user"],
        }
        set_auth_cookies(response, data["access"], data["refresh"])
        return response


class RefreshCookieMixin:
    """Feed the token view the refresh token its cookie carries."""

    def get_serializer(self, *args, **kwargs):
        """Validate the refresh token the request carries."""
        kwargs["data"] = {"refresh": self.refresh_token()}
        return super().get_serializer(*args, **kwargs)

    def refresh_token(self):
        """Return the refresh token from its cookie or None."""
        return self.request.COOKIES.get(settings.AUTH_REFRESH_COOKIE)

    def rejection(self):
        """Return the answer to a request without a refresh cookie."""
        return Response(
            {"detail": REFRESH_MISSING_MESSAGE},
            status=status.HTTP_400_BAD_REQUEST,
        )


class RefreshView(RefreshCookieMixin, TokenRefreshView):
    """Renew the access token the refresh cookie authorizes."""

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """Return a new access token and renew both cookies."""
        if not self.refresh_token():
            return self.rejection()
        response = super().post(request, *args, **kwargs)
        data = response.data
        response.data = {
            "detail": REFRESH_SUCCESS_MESSAGE,
            "access": data["access"],
        }
        set_auth_cookies(response, data["access"], data["refresh"])
        return response


class LogoutView(RefreshCookieMixin, TokenBlacklistView):
    """Blacklist the refresh token and clear both cookies."""

    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        """Blacklist the refresh token and report the logout."""
        if not self.refresh_token():
            return self.rejection()
        response = super().post(request, *args, **kwargs)
        response.data = {"detail": LOGOUT_SUCCESS_MESSAGE}
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        """Clear both authentication cookies on every answer."""
        finalized = super().finalize_response(
            request, response, *args, **kwargs
        )
        delete_auth_cookies(finalized)
        return finalized
