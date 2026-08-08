"""Views of the authentication API."""

from rest_framework import generics
from rest_framework.permissions import AllowAny

from auth_app.api.serializers import RegistrationSerializer


class RegistrationView(generics.CreateAPIView):
    """Create an inactive account and return its activation token."""

    serializer_class = RegistrationSerializer
    permission_classes = [AllowAny]
