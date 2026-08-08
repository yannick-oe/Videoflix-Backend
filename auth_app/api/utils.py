"""Stateless helpers of the authentication API."""

from django.conf import settings
from rest_framework_simplejwt.settings import api_settings


def set_auth_cookie(response, name, token, lifetime):
    """Store one token in its cookie with the configured flags."""
    response.set_cookie(
        name,
        token,
        max_age=lifetime,
        httponly=settings.AUTH_COOKIE_HTTPONLY,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        secure=settings.AUTH_COOKIE_SECURE,
    )


def set_auth_cookies(response, access, refresh):
    """Store the access and refresh tokens in their cookies."""
    set_auth_cookie(
        response,
        settings.AUTH_ACCESS_COOKIE,
        access,
        api_settings.ACCESS_TOKEN_LIFETIME,
    )
    set_auth_cookie(
        response,
        settings.AUTH_REFRESH_COOKIE,
        refresh,
        api_settings.REFRESH_TOKEN_LIFETIME,
    )
