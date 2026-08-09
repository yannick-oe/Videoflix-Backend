"""Authentication classes of the API."""

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate a request by the access token in its cookie."""

    def authenticate(self, request):
        """Return the account the access cookie names or None."""
        raw_token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE)
        if raw_token is None:
            return None
        try:
            token = self.get_validated_token(raw_token)
            return self.get_user(token), token
        except AuthenticationFailed:
            return None
