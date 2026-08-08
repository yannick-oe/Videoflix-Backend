"""Views of the authentication API."""

from django.contrib.auth.models import User
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from auth_app.api.serializers import RegistrationSerializer
from auth_app.tokens import activation_token_generator

ACTIVATION_SUCCESS_MESSAGE = "Account successfully activated."
ACTIVATION_FAILURE_MESSAGE = "Activation link is invalid or expired."


class RegistrationView(generics.CreateAPIView):
    """Create an inactive account and return its activation token."""

    serializer_class = RegistrationSerializer
    permission_classes = [AllowAny]


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
