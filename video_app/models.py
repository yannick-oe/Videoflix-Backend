"""Database models of the video app."""

from django.core.validators import FileExtensionValidator
from django.db import models

VIDEO_EXTENSIONS = [
    "mp4",
    "mov",
    "m4v",
    "mkv",
    "webm",
    "avi",
    "mpg",
    "mpeg",
    "ogv",
    "ts",
]
THUMBNAIL_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]


class Video(models.Model):
    """A film the catalogue offers for streaming."""

    title = models.CharField(max_length=80)
    description = models.CharField(max_length=500)
    category = models.CharField(max_length=40)
    video_file = models.FileField(
        upload_to="videos",
        validators=[FileExtensionValidator(VIDEO_EXTENSIONS)],
    )
    thumbnail = models.FileField(
        upload_to="thumbnails",
        blank=True,
        validators=[FileExtensionValidator(THUMBNAIL_EXTENSIONS)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(category=""),
                name="video_category_not_empty",
            ),
        ]

    def __str__(self):
        """Return the title of this video."""
        return self.title
