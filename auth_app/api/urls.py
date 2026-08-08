"""URL routes of the authentication API."""

from django.urls import path

from auth_app.api.views import (
    ActivationView,
    LoginView,
    LogoutView,
    RefreshView,
    RegistrationView,
)

urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path(
        "activate/<str:uidb64>/<str:token>/",
        ActivationView.as_view(),
        name="activate",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("token/refresh/", RefreshView.as_view(), name="token-refresh"),
]
