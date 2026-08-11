"""URL configuration for the Videoflix backend."""

from pathlib import Path

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

THUMBNAIL_DIRECTORY = "thumbnails"
THUMBNAIL_URL = f"{settings.MEDIA_URL}{THUMBNAIL_DIRECTORY}/"
THUMBNAIL_ROOT = Path(settings.MEDIA_ROOT) / THUMBNAIL_DIRECTORY

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("auth_app.api.urls")),
    path("api/", include("video_app.api.urls")),
] + static(THUMBNAIL_URL, document_root=THUMBNAIL_ROOT)
