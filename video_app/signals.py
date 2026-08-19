"""Signal handlers of the video app."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from video_app.models import Video
from video_app.services.cleanup import (
    remove_replaced_file_on_commit,
    remove_video_files,
)
from video_app.services.conversion import queue_renditions, video_directory
from video_app.services.thumbnail import queue_thumbnail

FILE_REPLACED_FLAG = "replaced_file_name"
SOURCE_FIELD = "video_file"


def writes_source(update_fields):
    """Tell whether this save writes the source file of a video."""
    return update_fields is None or SOURCE_FIELD in update_fields


def replaced_file_name(instance, update_fields):
    """Return the name of the file this save pushes off a video."""
    if not writes_source(update_fields):
        return ""
    stored = Video.objects.filter(pk=instance.pk).first()
    if stored is None or stored.video_file == instance.video_file:
        return ""
    return stored.video_file.name


def queue_jobs(video_id, with_thumbnail):
    """Hand the stored video of this id over to the worker."""
    if with_thumbnail:
        queue_thumbnail(video_id)
    queue_renditions(video_id)


@receiver(pre_save, sender=Video)
def remember_replaced_file(sender, instance, update_fields=None, **kwargs):
    """Note on the video which file this save pushes aside."""
    setattr(
        instance,
        FILE_REPLACED_FLAG,
        replaced_file_name(instance, update_fields),
    )


@receiver(post_save, sender=Video)
def queue_processing_of_video_file(sender, instance, created, **kwargs):
    """Queue the jobs the stored video file of this save needs."""
    replaced = getattr(instance, FILE_REPLACED_FLAG, "")
    if not created and not replaced:
        return
    video_id = instance.pk
    with_thumbnail = bool(replaced) or not instance.thumbnail
    transaction.on_commit(lambda: queue_jobs(video_id, with_thumbnail))
    remove_replaced_file_on_commit(
        instance.video_file.storage, replaced, instance.video_file.name
    )


@receiver(post_delete, sender=Video)
def remove_files_of_deleted_video(sender, instance, **kwargs):
    """Drop the files of this video once its deletion is final."""
    directory = video_directory(instance.pk)
    transaction.on_commit(lambda: remove_video_files(instance, directory))
