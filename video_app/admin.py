"""Admin registrations of the video app."""

from django.contrib import admin

from video_app.models import Video


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    """Manage the video catalogue from the admin site."""

    list_display = ["title", "category", "created_at", "thumbnail"]
    list_filter = ["category"]
    search_fields = ["title", "description"]
