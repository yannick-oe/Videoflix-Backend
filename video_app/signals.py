"""Signal handlers of the video app."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from video_app.models import Video
from video_app.services.cleanup import remove_video_files
from video_app.services.conversion import queue_renditions, video_directory
from video_app.services.thumbnail import queue_thumbnail

FILE_REPLACED_FLAG = "file_replaced"


def file_was_replaced(instance):
    """Tell whether this save puts a new file on a stored video."""
    stored = Video.objects.filter(pk=instance.pk).first()
    if stored is None:
        return False
    return stored.video_file != instance.video_file


def queue_jobs(video_id, with_thumbnail):
    """Hand the stored video of this id over to the worker."""
    if with_thumbnail:
        queue_thumbnail(video_id)
    queue_renditions(video_id)


@receiver(pre_save, sender=Video)
def remember_replaced_file(sender, instance, **kwargs):
    """Note on the video whether this save replaces its file."""
    setattr(instance, FILE_REPLACED_FLAG, file_was_replaced(instance))


@receiver(post_save, sender=Video)
def queue_processing_of_video_file(sender, instance, created, **kwargs):
    """Queue the jobs the stored video file of this save needs."""
    replaced = getattr(instance, FILE_REPLACED_FLAG, False)
    if not created and not replaced:
        return
    video_id = instance.pk
    with_thumbnail = replaced or not instance.thumbnail
    transaction.on_commit(lambda: queue_jobs(video_id, with_thumbnail))


@receiver(post_delete, sender=Video)
def remove_files_of_deleted_video(sender, instance, **kwargs):
    """Drop the files of this video once its deletion is final."""
    directory = video_directory(instance.pk)
    transaction.on_commit(lambda: remove_video_files(instance, directory))
