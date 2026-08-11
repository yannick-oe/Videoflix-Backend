"""Signal handlers of the video app."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from video_app.models import Video
from video_app.services.thumbnail import queue_thumbnail


@receiver(post_save, sender=Video)
def queue_thumbnail_of_new_video(sender, instance, created, **kwargs):
    """Queue the frame extraction a stored video still needs."""
    if not created:
        return
    if instance.thumbnail:
        return
    video_id = instance.pk
    transaction.on_commit(lambda: queue_thumbnail(video_id))
