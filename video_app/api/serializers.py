"""Serializers of the video API."""

from rest_framework import serializers

from video_app.models import Video


class VideoSerializer(serializers.ModelSerializer):
    """Represent a video the way the catalogue lists it."""

    thumbnail_url = serializers.FileField(source="thumbnail", read_only=True)

    class Meta:
        model = Video
        fields = [
            "id",
            "created_at",
            "title",
            "description",
            "thumbnail_url",
            "category",
        ]
