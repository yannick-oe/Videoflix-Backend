"""Background jobs of the video app."""

from video_app.models import Video
from video_app.services.conversion import create_rendition, discard_renditions
from video_app.services.thumbnail import create_thumbnail


def generate_thumbnail(video_id):
    """Store the preview frame of the video this id addresses."""
    video = Video.objects.filter(pk=video_id).first()
    if video is None:
        return
    create_thumbnail(video)


def drop_renditions_of_deleted_video(video_id):
    """Remove what a conversion finished for a row that is gone."""
    if Video.objects.filter(pk=video_id).exists():
        return
    discard_renditions(video_id)


def generate_rendition(video_id, resolution):
    """Store one HLS rendition of the video this id addresses."""
    video = Video.objects.filter(pk=video_id).first()
    if video is None:
        return
    create_rendition(video, resolution)
    drop_renditions_of_deleted_video(video_id)
